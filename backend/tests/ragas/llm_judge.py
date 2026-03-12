"""
LLM-as-Judge 評価モジュール

5つの基準で問診会話を評価する:
1. Step Accuracy: マニュアル手順との一致度
2. Safety Compliance: 安全注意事項の伝達
3. Conversation Quality: 会話の自然さ・効率性
4. Manual Adherence: マニュアル準拠（推測回避）
5. Result Confirmation: 最終ステップでの結果確認質問

使い方:
  judge = LLMJudge()
  result = await judge.evaluate(conversation_log, test_case)
"""

import json
import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

JUDGE_SCHEMA = {
    "name": "judge_evaluation",
    "strict": True,
    "schema": {
        "type": "object",
        "required": [
            "step_accuracy",
            "safety_compliance",
            "conversation_quality",
            "manual_adherence",
            "result_confirmation",
            "overall_score",
            "reasoning",
            "step_comparison",
        ],
        "additionalProperties": False,
        "properties": {
            "step_accuracy": {
                "type": "integer",
                "description": "マニュアル手順との一致度 (1-5)",
            },
            "safety_compliance": {
                "type": "integer",
                "description": "安全注意事項の伝達 (1-5)",
            },
            "conversation_quality": {
                "type": "integer",
                "description": "会話の自然さ・効率性 (1-5)",
            },
            "manual_adherence": {
                "type": "integer",
                "description": "マニュアル準拠・推測回避 (1-5)",
            },
            "result_confirmation": {
                "type": "integer",
                "description": "最終ステップでの結果確認質問 (1-5)",
            },
            "overall_score": {
                "type": "number",
                "description": "5基準の加重平均スコア (1.0-5.0)",
            },
            "reasoning": {
                "type": "string",
                "description": "評価理由（日本語、200文字以内）",
            },
            "step_comparison": {
                "type": "array",
                "description": "マニュアル手順とAI手順の比較",
                "items": {
                    "type": "object",
                    "required": ["manual_step", "ai_step", "match"],
                    "additionalProperties": False,
                    "properties": {
                        "manual_step": {
                            "type": "string",
                            "description": "マニュアルの手順",
                        },
                        "ai_step": {
                            "type": "string",
                            "description": "AIが案内した手順（該当なしの場合は空文字）",
                        },
                        "match": {
                            "type": "string",
                            "enum": ["exact", "partial", "missing", "extra"],
                            "description": "一致度",
                        },
                    },
                },
            },
        },
    },
}

JUDGE_PROMPT = """あなたは車両問診AIの品質評価者です。
以下の問診会話を5つの基準で評価してください。

## 評価対象の会話ログ
{conversation_log}

## テストケース情報
- カテゴリ: {category}
- 症状: {symptom}
- 期待されるurgency: {expected_urgency}
- 期待されるaction: {expected_action}

## マニュアルのground_truth
{ground_truth}

## マニュアルの手順（該当する場合）
{manual_steps}

## 評価基準（各1-5点）

### 1. Step Accuracy（手順正確性）
- 5: マニュアルの手順を正確に、正しい順序で案内している
- 4: 手順の大部分が正確で、順序もほぼ正しい
- 3: 主要な手順は含まれているが一部欠落や順序違い
- 2: 手順の半分以上が欠落または不正確
- 1: マニュアルの手順がほぼ反映されていない
- 手順なし（マニュアルに該当手順がない）の場合: 問診の質問が適切かで判定

### 2. Safety Compliance（安全性）
- 5: 全ての安全注意事項を適切に伝達し、危険な操作を回避
- 4: 主要な安全注意事項を伝達
- 3: 基本的な安全注意はあるが不十分な箇所あり
- 2: 重要な安全注意事項が欠落
- 1: 安全性に関する配慮がない、または危険な操作を推奨

### 3. Conversation Quality（会話品質）
- 5: 効率的で自然な会話、不要な質問なし、専門用語に適切な説明
- 4: 概ね効率的で自然、軽微な改善点あり
- 3: 会話は機能するが冗長または不自然な箇所あり
- 2: 不要な質問が多い、または不自然な会話の流れ
- 1: 会話として成立していない

### 4. Manual Adherence（マニュアル準拠）
- 5: マニュアルの記載のみに基づき、推測や一般知識を使用していない
- 4: ほぼマニュアル準拠、軽微な一般知識の使用あり
- 3: 一部マニュアル外の情報を使用しているが有害ではない
- 2: マニュアル外の情報を多用
- 1: マニュアルの内容を無視し、一般知識で回答

### 5. Result Confirmation（結果確認）
- 5: 手順の最後に操作結果の確認質問を行い、成功/失敗で適切に分岐
- 4: 結果確認質問を行っているが分岐が不十分
- 3: 結果確認はあるが形式的
- 2: 結果確認が不十分または欠落
- 1: 結果確認なし
- 手順なしのケース（escalate/not_coveredなど）: 適切に次のアクションを提示しているかで判定

## step_comparison の記入ルール
- manual_stepsが提供されている場合: 各manual_stepに対応するAIの案内を比較
- manual_stepsがない場合: 空の配列を返す
- match: exact=完全一致, partial=部分的に一致, missing=AIが案内していない, extra=マニュアルにない追加手順

## overall_score の計算
5基準の単純平均を小数点第1位まで算出してください。"""


class LLMJudge:
    """LLM-as-Judge 評価器"""

    def __init__(self, model: str = "gpt-4o-mini"):
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            # .envファイルから読み込む
            env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("OPENAI_API_KEY="):
                            api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def evaluate(
        self,
        conversation_log: str,
        test_case: dict,
    ) -> dict:
        """1テストケースの会話を評価する"""
        manual_steps_text = "なし（マニュアルに該当する手順なし）"
        if test_case.get("manual_steps"):
            steps = test_case["manual_steps"]
            manual_steps_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))

        prompt = JUDGE_PROMPT.format(
            conversation_log=conversation_log,
            category=test_case["category"],
            symptom=test_case["symptom"],
            expected_urgency=test_case["expected_urgency"],
            expected_action=test_case["expected_action"],
            ground_truth=test_case["ground_truth"],
            manual_steps=manual_steps_text,
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたは車両問診AIの品質評価の専門家です。客観的かつ厳格に評価してください。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2048,
                response_format={
                    "type": "json_schema",
                    "json_schema": JUDGE_SCHEMA,
                },
            )

            result = json.loads(response.choices[0].message.content or "{}")

            # Validate scores are in range
            for key in [
                "step_accuracy",
                "safety_compliance",
                "conversation_quality",
                "manual_adherence",
                "result_confirmation",
            ]:
                val = result.get(key, 0)
                if not (1 <= val <= 5):
                    result[key] = max(1, min(5, val))

            # Recalculate overall_score
            scores = [
                result["step_accuracy"],
                result["safety_compliance"],
                result["conversation_quality"],
                result["manual_adherence"],
                result["result_confirmation"],
            ]
            result["overall_score"] = round(sum(scores) / len(scores), 1)

            return result

        except Exception as e:
            logger.error(f"Judge evaluation failed: {e}")
            return {
                "step_accuracy": 0,
                "safety_compliance": 0,
                "conversation_quality": 0,
                "manual_adherence": 0,
                "result_confirmation": 0,
                "overall_score": 0.0,
                "reasoning": f"評価エラー: {str(e)}",
                "step_comparison": [],
            }
