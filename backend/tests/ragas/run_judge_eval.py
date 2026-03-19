"""
LLM-as-Judge マルチターン評価オーケストレーター

全18ケースでマルチターン会話を実行し、LLM-as-Judgeで5基準評価を行う。

前提: バックエンドが起動済み (uvicorn app.main:app)

使い方:
  cd backend
  python -m tests.ragas.run_judge_eval
  python -m tests.ragas.run_judge_eval --cases 1,5,10
  python -m tests.ragas.run_judge_eval --max-turns 8
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.ragas.llm_judge import LLMJudge
from tests.ragas.test_cases import TEST_CASES

BASE_URL = os.environ.get("CHAT_API_URL", "http://localhost:8000/api")
TIMEOUT = 30.0
DEFAULT_MAX_TURNS = 12


async def run_multi_turn_flow(
    client: httpx.AsyncClient,
    tc: dict,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> dict:
    """1テストケースのマルチターン問診フローを実行し、会話ログを返す"""
    result = {
        "id": tc["id"],
        "category": tc["category"],
        "symptom": tc["symptom"],
        "conversation_log": [],
        "turns": 0,
        "final_step": None,
        "final_action": None,
        "urgency_flag": None,
        "error": None,
    }

    try:
        # Step 1: セッション作成
        resp = await client.post(f"{BASE_URL}/chat", json={})
        resp.raise_for_status()
        data = resp.json()
        session_id = data["session_id"]

        # Step 2: 車両選択
        resp = await client.post(
            f"{BASE_URL}/chat",
            json={
                "session_id": session_id,
                "action": "select_vehicle",
                "action_value": tc["vehicle_id"],
            },
        )
        resp.raise_for_status()

        # Step 3: 写真確認
        resp = await client.post(
            f"{BASE_URL}/chat",
            json={
                "session_id": session_id,
                "action": "confirm",
                "action_value": "yes",
            },
        )
        resp.raise_for_status()

        # Step 4: 症状入力
        resp = await client.post(
            f"{BASE_URL}/chat",
            json={
                "session_id": session_id,
                "message": tc["symptom"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # 初回レスポンスを記録
        prompt_msg = data.get("prompt", {}).get("message", "")
        result["conversation_log"].append({
            "role": "user",
            "content": tc["symptom"],
        })
        result["conversation_log"].append({
            "role": "assistant",
            "content": prompt_msg,
            "step": data.get("current_step"),
            "choices": data.get("prompt", {}).get("choices"),
        })
        result["turns"] = 1

        # urgency情報を取得
        if data.get("urgency"):
            result["urgency_flag"] = data["urgency"].get("level")

        current_step = data.get("current_step", "")

        # escalateケース: reservation に直行 → 完了
        if current_step in ("reservation", "done"):
            result["final_step"] = current_step
            result["final_action"] = "escalate"
            return result

        # spec_checkケース
        if current_step == "spec_check":
            result["final_step"] = current_step
            result["final_action"] = "spec_answer"
            return result

        # Transition choice values that require action/action_value
        _TRANSITION_VALUES = {"guide_start", "yes", "no"}

        # マルチターン: 選択肢の最初を自動選択して会話を進行
        for turn in range(2, max_turns + 1):
            choices = data.get("prompt", {}).get("choices")
            prompt_msg = data.get("prompt", {}).get("message", "")

            request_body: dict = {"session_id": session_id}

            if not choices:
                # 選択肢なし → 自由入力で「はい」と回答
                user_msg = "はい"
                request_body["message"] = user_msg
            else:
                first_choice = choices[0] if isinstance(choices[0], dict) else {"label": str(choices[0])}
                user_msg = first_choice.get("label", first_choice.get("text", "はい"))
                choice_value = first_choice.get("value", "")

                # Transition choices (guide_start/yes/no) → send as action
                if choice_value in _TRANSITION_VALUES:
                    request_body["message"] = user_msg
                    request_body["action"] = "resolved"
                    request_body["action_value"] = choice_value
                else:
                    request_body["message"] = user_msg

            resp = await client.post(
                f"{BASE_URL}/chat",
                json=request_body,
            )
            resp.raise_for_status()
            data = resp.json()

            result["conversation_log"].append({
                "role": "user",
                "content": user_msg,
            })

            assistant_msg = data.get("prompt", {}).get("message", "")
            result["conversation_log"].append({
                "role": "assistant",
                "content": assistant_msg,
                "step": data.get("current_step"),
                "choices": data.get("prompt", {}).get("choices"),
            })
            result["turns"] = turn

            if data.get("urgency"):
                result["urgency_flag"] = data["urgency"].get("level")

            current_step = data.get("current_step", "")

            # 終了条件
            if current_step in ("reservation", "done", "urgency_check"):
                result["final_step"] = current_step
                if current_step == "reservation":
                    result["final_action"] = "escalate"
                else:
                    result["final_action"] = "provide_answer"
                return result

            # provide_answer検出（step_diagnosingでも最終回答の場合がある）
            if current_step == "diagnosing" and not data.get("prompt", {}).get("choices"):
                result["final_step"] = current_step
                result["final_action"] = "provide_answer"
                return result

        # max_turns到達
        result["final_step"] = current_step
        result["final_action"] = "max_turns_reached"

    except httpx.ConnectError:
        result["error"] = f"接続エラー: {BASE_URL} に接続できません"
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"

    return result


def format_conversation_log(log: list[dict]) -> str:
    """会話ログをテキスト形式に変換"""
    lines = []
    for entry in log:
        role = "ユーザー" if entry["role"] == "user" else "AI"
        content = entry["content"]
        step = entry.get("step", "")
        step_label = f" [{step}]" if step else ""
        lines.append(f"【{role}{step_label}】{content}")

        choices = entry.get("choices")
        if choices and entry["role"] == "assistant":
            choice_labels = []
            for c in choices:
                if isinstance(c, dict):
                    choice_labels.append(c.get("label", c.get("text", str(c))))
                else:
                    choice_labels.append(str(c))
            lines.append(f"  選択肢: {' / '.join(choice_labels)}")
    return "\n".join(lines)


def print_judge_results(results: list[dict]):
    """Judge評価結果をコンソール表示"""
    print("\n" + "=" * 120)
    print("LLM-as-Judge 評価結果")
    print("=" * 120)

    header = (
        f"{'#':>3} {'カテゴリ':<14} {'turns':>5} "
        f"{'StepAcc':>7} {'Safety':>7} {'ConvQ':>7} {'ManAdh':>7} {'ResConf':>7} "
        f"{'Overall':>7} {'action':<16} {'結果':<6}"
    )
    print(header)
    print("-" * 120)

    total_scores = {
        "step_accuracy": 0,
        "safety_compliance": 0,
        "conversation_quality": 0,
        "manual_adherence": 0,
        "result_confirmation": 0,
        "overall_score": 0.0,
    }
    evaluated = 0

    for r in results:
        if r.get("error"):
            print(f"{r['id']:>3} {r['category']:<14} ERROR: {r['error'][:80]}")
            continue

        judge = r.get("judge", {})
        if not judge or judge.get("overall_score", 0) == 0:
            print(f"{r['id']:>3} {r['category']:<14} JUDGE ERROR")
            continue

        evaluated += 1
        for key in total_scores:
            total_scores[key] += judge.get(key, 0)

        overall = judge.get("overall_score", 0)
        status = "GOOD" if overall >= 3.5 else "FAIR" if overall >= 2.5 else "POOR"

        print(
            f"{r['id']:>3} {r['category']:<14} {r['turns']:>5} "
            f"{judge['step_accuracy']:>7} {judge['safety_compliance']:>7} "
            f"{judge['conversation_quality']:>7} {judge['manual_adherence']:>7} "
            f"{judge['result_confirmation']:>7} "
            f"{overall:>7.1f} {r.get('final_action', 'N/A'):<16} {status:<6}"
        )

    print("-" * 120)

    if evaluated > 0:
        print(f"\n{'■ 平均スコア':}")
        for key, label in [
            ("step_accuracy", "Step Accuracy"),
            ("safety_compliance", "Safety Compliance"),
            ("conversation_quality", "Conversation Quality"),
            ("manual_adherence", "Manual Adherence"),
            ("result_confirmation", "Result Confirmation"),
            ("overall_score", "Overall"),
        ]:
            avg = total_scores[key] / evaluated
            print(f"  {label:<25} {avg:.2f} / 5.0")

    # 評価理由サマリー
    print(f"\n{'■ 評価理由（先頭150文字）':}")
    for r in results:
        if r.get("error"):
            continue
        judge = r.get("judge", {})
        reasoning = judge.get("reasoning", "")[:150].replace("\n", " ")
        print(f"  [{r['id']:02d}] {reasoning}")


def save_results(results: list[dict]):
    """結果をJSONファイルに保存"""
    output = {
        "timestamp": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "evaluator": "LLM-as-Judge (gpt-4o-mini)",
        "results": [],
    }

    evaluated_count = 0
    total_overall = 0.0

    for r in results:
        case_output = {
            "id": r["id"],
            "category": r["category"],
            "symptom": r["symptom"],
            "turns": r.get("turns", 0),
            "final_step": r.get("final_step"),
            "final_action": r.get("final_action"),
            "urgency_flag": r.get("urgency_flag"),
            "error": r.get("error"),
            "judge": r.get("judge"),
            "conversation_log": r.get("conversation_log", []),
        }
        output["results"].append(case_output)

        if r.get("judge") and r["judge"].get("overall_score", 0) > 0:
            evaluated_count += 1
            total_overall += r["judge"]["overall_score"]

    output["summary"] = {
        "total": len(results),
        "evaluated": evaluated_count,
        "average_overall": round(total_overall / evaluated_count, 2) if evaluated_count > 0 else 0,
    }

    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_results")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(
        output_dir, f"judge_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n結果を保存しました: {output_path}")
    return output_path


async def main():
    parser = argparse.ArgumentParser(description="LLM-as-Judge マルチターン評価")
    parser.add_argument("--cases", type=str, help="評価するケースID (カンマ区切り)", default=None)
    parser.add_argument("--max-turns", type=int, help="最大ターン数", default=DEFAULT_MAX_TURNS)
    args = parser.parse_args()

    case_ids = None
    if args.cases:
        case_ids = [int(x) for x in args.cases.split(",")]

    cases = TEST_CASES if case_ids is None else [
        tc for tc in TEST_CASES if tc["id"] in case_ids
    ]

    print("=" * 80)
    print("LLM-as-Judge マルチターン評価")
    print(f"対象API: {BASE_URL}")
    print(f"テストケース数: {len(cases)}")
    print(f"最大ターン数: {args.max_turns}")
    print("=" * 80)

    # 接続確認
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            health = await client.get(f"{BASE_URL}/health")
            print(f"\nヘルスチェック: {health.status_code}")
        except httpx.ConnectError:
            print(f"\nエラー: {BASE_URL} に接続できません。")
            print("バックエンドを起動してください: cd backend && uvicorn app.main:app --reload")
            sys.exit(1)

        judge = LLMJudge()
        results = []

        for tc in cases:
            print(f"\n  [{tc['id']:02d}] {tc['category']}: {tc['symptom'][:30]}...")

            # マルチターン会話実行
            flow_result = await run_multi_turn_flow(client, tc, max_turns=args.max_turns)

            if flow_result["error"]:
                print(f"       ERROR: {flow_result['error'][:60]}")
                results.append(flow_result)
                continue

            print(
                f"       turns={flow_result['turns']}, "
                f"action={flow_result.get('final_action')}, "
                f"urgency={flow_result.get('urgency_flag')}"
            )

            # Judge評価
            conversation_text = format_conversation_log(flow_result["conversation_log"])
            print(f"       Evaluating with LLM-as-Judge...")
            judge_result = await judge.evaluate(conversation_text, tc)
            flow_result["judge"] = judge_result

            overall = judge_result.get("overall_score", 0)
            print(f"       Judge score: {overall:.1f}/5.0")

            results.append(flow_result)

    # 結果表示・保存
    print_judge_results(results)
    save_results(results)


if __name__ == "__main__":
    asyncio.run(main())
