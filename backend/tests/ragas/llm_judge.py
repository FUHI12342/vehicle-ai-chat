"""
LLM-as-Judge 評価モジュール

4つの基準で問診会話を評価する:
1. Step Accuracy: マニュアル手順との一致度
2. Safety Compliance: 安全注意事項の伝達（低リスク症状はN/A）
3. Manual Adherence: マニュアル準拠（推測回避）+ 禁止用語チェック
4. Diagnostic Completeness: 手順案内の完了度（premature escalate検出）

v2.0: conversation_quality廃止（情報量ゼロ）、Diagnostic Completeness追加、
      safety N/A条件、forbidden_terms連携、step_comparison整合チェック

使い方:
  judge = LLMJudge()
  result = await judge.evaluate(conversation_log, test_case)
"""

import json
import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# 低リスク症状カテゴリ: safety_compliance をN/A扱いにする
LOW_RISK_CATEGORIES = frozenset({
    "エアコン不調",
    "燃費悪化",
    "ワイパー故障",
    "走行中異音",
    "走行中振動",
    "ハンドル重い",
    "仕様確認系",
    "セレクトレバー不動",
})

JUDGE_SCHEMA = {
    "name": "judge_evaluation",
    "strict": True,
    "schema": {
        "type": "object",
        "required": [
            "step_accuracy",
            "safety_compliance",
            "manual_adherence",
            "diagnostic_completeness",
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
                "description": "安全注意事項の伝達 (1-5)。低リスク症状では後処理でN/A扱い",
            },
            "manual_adherence": {
                "type": "integer",
                "description": "マニュアル準拠・推測回避 (1-5)",
            },
            "diagnostic_completeness": {
                "type": "integer",
                "description": "手順案内の完了度・早期escalate回避 (1-5)",
            },
            "overall_score": {
                "type": "number",
                "description": "有効な基準の加重平均スコア (1.0-5.0)",
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
以下の問診会話を4つの基準で評価してください。

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

## 期待される最終アクション
{expected_final_action}

## 最大期待ターン数
{max_expected_turns}
{forbidden_terms_section}
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

### 3. Manual Adherence（マニュアル準拠）
- 5: マニュアルの記載のみに基づき、推測や一般知識を使用していない
- 4: ほぼマニュアル準拠、軽微な一般知識の使用あり
- 3: 一部マニュアル外の情報を使用しているが有害ではない
- 2: マニュアル外の情報を多用
- 1: マニュアルの内容を無視し、一般知識で回答
{forbidden_terms_rubric}
### 4. Diagnostic Completeness（診断完了度）
- 5: マニュアルの全手順を1ステップずつ案内し、最終確認質問で完了している
- 4: 主要な手順を案内したが、一部省略がある
- 3: 手順の半分程度を案内した、または早期にescalateしたが安全上の理由がある
- 2: 手順のごく一部しか案内せず、不必要にescalateした
- 1: 手順を一切案内せず即座にescalateした（expected_final_actionがescalateの場合を除く）
- expected_final_action が escalate の場合: 適切なタイミングでescalateしたかで判定（即座のescalateが正解）
- expected_final_action が provide_answer の場合: 全手順案内後にprovide_answerに到達したかで判定

## step_comparison の記入ルール
- manual_stepsが提供されている場合: 各manual_stepに対応するAIの案内を比較
- manual_stepsがない場合: 空の配列を返す
- match: exact=完全一致, partial=部分的に一致, missing=AIが案内していない, extra=マニュアルにない追加手順

## overall_score の計算
有効な基準の単純平均を小数点第1位まで算出してください。"""


def _build_forbidden_terms_section(forbidden_terms: list[str] | None) -> str:
    """forbidden_terms がある場合、Judge プロンプト用のセクションを構築する。"""
    if not forbidden_terms:
        return ""
    terms_str = "、".join(f"「{t}」" for t in forbidden_terms)
    return f"\n## 禁止用語（これらが会話に含まれる場合はマニュアル外の推測）\n{terms_str}\n"


def _build_forbidden_terms_rubric(forbidden_terms: list[str] | None) -> str:
    """forbidden_terms がある場合、Manual Adherence ルーブリックへの追加テキストを構築する。"""
    if not forbidden_terms:
        return ""
    terms_str = "、".join(f"「{t}」" for t in forbidden_terms)
    return (
        f"\n- 追加ルール: 以下の禁止用語が会話に含まれる場合、マニュアル外の推測と判断し "
        f"manual_adherence を最大3に制限すること: {terms_str}\n"
    )


def _enforce_step_comparison_consistency(result: dict) -> dict:
    """step_comparison の missing 率から score の下限を強制する後処理。

    missing率が高い場合、step_accuracy と diagnostic_completeness が
    不当に高くならないよう、自動で下限を設定する。
    """
    comparisons = result.get("step_comparison", [])
    if not comparisons:
        return result

    total = len(comparisons)
    missing_count = sum(1 for c in comparisons if c.get("match") == "missing")
    missing_rate = missing_count / total if total > 0 else 0.0

    # missing率に基づくスコア上限
    if missing_rate >= 0.8:
        score_cap = 1
    elif missing_rate >= 0.6:
        score_cap = 2
    elif missing_rate >= 0.4:
        score_cap = 3
    elif missing_rate >= 0.2:
        score_cap = 4
    else:
        return result  # missing率20%未満は制約なし

    # step_accuracy と diagnostic_completeness にキャップ適用
    updated = dict(result)
    if updated.get("step_accuracy", 0) > score_cap:
        updated["step_accuracy"] = score_cap
    if updated.get("diagnostic_completeness", 0) > score_cap:
        updated["diagnostic_completeness"] = score_cap

    return updated


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

        # forbidden_terms セクション構築
        forbidden_terms = test_case.get("forbidden_terms")
        forbidden_terms_section = _build_forbidden_terms_section(forbidden_terms)
        forbidden_terms_rubric = _build_forbidden_terms_rubric(forbidden_terms)

        prompt = JUDGE_PROMPT.format(
            conversation_log=conversation_log,
            category=test_case["category"],
            symptom=test_case["symptom"],
            expected_urgency=test_case["expected_urgency"],
            expected_action=test_case["expected_action"],
            ground_truth=test_case["ground_truth"],
            manual_steps=manual_steps_text,
            expected_final_action=test_case.get("expected_final_action", "N/A"),
            max_expected_turns=test_case.get("max_expected_turns", "N/A"),
            forbidden_terms_section=forbidden_terms_section,
            forbidden_terms_rubric=forbidden_terms_rubric,
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
                "manual_adherence",
                "diagnostic_completeness",
            ]:
                val = result.get(key, 0)
                if not (1 <= val <= 5):
                    result[key] = max(1, min(5, val))

            # step_comparison 整合性チェック: missing率からスコア下限を強制
            result = _enforce_step_comparison_consistency(result)

            # forbidden_terms 自動減点: 会話に禁止用語が含まれていればmanual_adherenceを制限
            if forbidden_terms:
                conversation_lower = conversation_log.lower()
                found_terms = [
                    t for t in forbidden_terms
                    if t.lower() in conversation_lower
                ]
                if found_terms:
                    logger.info(
                        "Forbidden terms found in conversation: %s", found_terms
                    )
                    result["manual_adherence"] = min(result["manual_adherence"], 3)

            # Safety N/A: 低リスクカテゴリではsafety_complianceをoverall計算から除外
            category = test_case.get("category", "")
            is_low_risk = category in LOW_RISK_CATEGORIES
            result["safety_na"] = is_low_risk

            # Calculate overall_score from active dimensions
            active_scores = [
                result["step_accuracy"],
                result["manual_adherence"],
                result["diagnostic_completeness"],
            ]
            if not is_low_risk:
                active_scores.append(result["safety_compliance"])

            result["overall_score"] = round(
                sum(active_scores) / len(active_scores), 1
            )

            return result

        except Exception as e:
            logger.error(f"Judge evaluation failed: {e}")
            return {
                "step_accuracy": 0,
                "safety_compliance": 0,
                "manual_adherence": 0,
                "diagnostic_completeness": 0,
                "overall_score": 0.0,
                "reasoning": f"評価エラー: {str(e)}",
                "step_comparison": [],
                "safety_na": False,
            }
