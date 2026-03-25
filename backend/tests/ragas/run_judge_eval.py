"""
LLM-as-Judge マルチターン評価オーケストレーター

全21ケースでマルチターン会話を実行し、LLM-as-Judgeで4基準評価を行う。

前提: バックエンドが起動済み (uvicorn app.main:app)

使い方:
  cd backend
  python -m tests.ragas.run_judge_eval
  python -m tests.ragas.run_judge_eval --cases 1,5,10
  python -m tests.ragas.run_judge_eval --max-turns 8
  python -m tests.ragas.run_judge_eval --user-pattern uncertain
  python -m tests.ragas.run_judge_eval --full  # 全パターンで実行
  python -m tests.ragas.run_judge_eval --rejudge test_results/judge_eval_XXXX.json
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

# ---------------------------------------------------------------------------
# Simulated user patterns
# ---------------------------------------------------------------------------
USER_PATTERNS = {
    "cooperative": {
        "description": "第1選択肢を選択、選択肢なしは「はい」",
        "choice_strategy": "first",
        "no_choice_response": "はい",
    },
    "uncertain": {
        "description": "「わからない」を選択、自由入力は「よくわかりません」",
        "choice_strategy": "dont_know",
        "no_choice_response": "よくわかりません",
    },
    "verbose": {
        "description": "冗長な自由入力で追加情報を提供",
        "choice_strategy": "first_with_detail",
        "no_choice_response": "はい、確認しました。特に他に変わったことはないと思いますが、最近少し気になっていました。",
    },
}


def _select_user_response(
    choices: list | None,
    pattern_name: str,
    ai_message: str = "",
    response_overrides: dict[str, str] | None = None,
) -> tuple[str, dict | None]:
    """パターンに基づいてユーザー応答を選択する。

    Args:
        choices: AIが提示した選択肢
        pattern_name: ユーザーパターン名
        ai_message: AIのメッセージ（オーバーライド判定用）
        response_overrides: テストケース固有の応答オーバーライド

    Returns:
        (user_message, selected_choice_dict or None)
    """
    pattern = USER_PATTERNS[pattern_name]

    # テストケース固有の応答オーバーライド:
    # AIの質問が症状と矛盾する回答を誘発する場合に上書きする
    if response_overrides and ai_message:
        for trigger, override_response in response_overrides.items():
            if trigger in ai_message:
                return override_response, None

    if not choices:
        return pattern["no_choice_response"], None

    strategy = pattern["choice_strategy"]

    if strategy == "dont_know":
        # 「わからない」選択肢を探す
        for c in choices:
            choice_obj = c if isinstance(c, dict) else {"label": str(c)}
            value = choice_obj.get("value", "")
            label = choice_obj.get("label", "")
            if value == "dont_know" or "わからない" in label:
                return label, choice_obj
        # なければ第1選択肢
        first = choices[0] if isinstance(choices[0], dict) else {"label": str(choices[0])}
        return first.get("label", "はい"), first

    if strategy == "first_with_detail":
        first = choices[0] if isinstance(choices[0], dict) else {"label": str(choices[0])}
        label = first.get("label", "はい")
        return f"{label}（少し前から気になっていました）", first

    # cooperative (first)
    first = choices[0] if isinstance(choices[0], dict) else {"label": str(choices[0])}
    return first.get("label", first.get("text", "はい")), first


# ---------------------------------------------------------------------------
# Component metrics (deterministic)
# ---------------------------------------------------------------------------

def compute_component_metrics(
    flow_result: dict,
    test_case: dict,
    judge_result: dict,
) -> dict:
    """Judge評価とは別の決定論的メトリクスを計算する。"""
    metrics = {}

    # 1. Coverage Accuracy: AI返却coverage vs expected_coverage
    conversation_log = flow_result.get("conversation_log", [])
    ai_coverages = []
    for entry in conversation_log:
        if entry.get("role") == "assistant" and entry.get("manual_coverage"):
            ai_coverages.append(entry["manual_coverage"])
    # 最後に返されたcoverage（flow_result直接には含まれないためJudge側からは取れない）
    # → flow_result の全体coverageで代用
    expected = test_case.get("expected_coverage")
    if expected:
        # flow_result に manual_coverage が入っている場合
        actual_coverage = flow_result.get("manual_coverage")
        metrics["coverage_accuracy"] = 1.0 if actual_coverage == expected else 0.0
        metrics["expected_coverage"] = expected
        metrics["actual_coverage"] = actual_coverage
    else:
        metrics["coverage_accuracy"] = None

    # 2. Escalation Timing: escalateしたターン数 vs max_expected_turns
    max_expected = test_case.get("max_expected_turns")
    actual_turns = flow_result.get("turns", 0)
    if max_expected and max_expected > 0:
        metrics["escalation_timing_ratio"] = round(actual_turns / max_expected, 2)
        metrics["actual_turns"] = actual_turns
        metrics["max_expected_turns"] = max_expected
    else:
        metrics["escalation_timing_ratio"] = None

    # 3. RAG Precision@5 (step_comparison based approximation)
    # missing/total で間接的にRAG品質を推定
    comparisons = judge_result.get("step_comparison", [])
    if comparisons:
        relevant_count = sum(
            1 for c in comparisons
            if c.get("match") in ("exact", "partial")
        )
        metrics["rag_precision_at_5"] = round(relevant_count / len(comparisons), 2)
    else:
        metrics["rag_precision_at_5"] = None

    # 4. Action accuracy
    expected_action = test_case.get("expected_final_action")
    actual_action = flow_result.get("final_action")
    if expected_action:
        metrics["action_accuracy"] = 1.0 if actual_action == expected_action else 0.0
        metrics["expected_final_action"] = expected_action
        metrics["actual_final_action"] = actual_action
    else:
        metrics["action_accuracy"] = None

    return metrics


def _is_repeated_response(prev: str, current: str) -> bool:
    """AIの回答が前回とほぼ同一かどうかを判定する。

    診断完了後にAIが同じ結論を繰り返す場合を検出する。
    先頭80文字が一致すれば繰り返しと見なす。
    """
    if not prev or not current:
        return False
    return prev[:80] == current[:80]


# Transition choice values that require action/action_value
_TRANSITION_VALUES = {"guide_start", "yes", "no"}


async def run_multi_turn_flow(
    client: httpx.AsyncClient,
    tc: dict,
    max_turns: int = DEFAULT_MAX_TURNS,
    user_pattern: str = "cooperative",
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
        "manual_coverage": None,
        "error": None,
        "user_pattern": user_pattern,
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
            "manual_coverage": data.get("manual_coverage"),
        })
        result["turns"] = 1
        result["manual_coverage"] = data.get("manual_coverage")

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

        # マルチターン: パターンに基づいて自動選択して会話を進行
        response_overrides = tc.get("user_response_overrides")
        prev_assistant_msg = ""
        for turn in range(2, max_turns + 1):
            choices = data.get("prompt", {}).get("choices")

            # パターンに基づいてユーザー応答を決定
            ai_msg = data.get("prompt", {}).get("message", "")
            user_msg, selected_choice = _select_user_response(
                choices, user_pattern, ai_msg, response_overrides,
            )

            request_body: dict = {"session_id": session_id}

            if selected_choice:
                choice_value = selected_choice.get("value", "")
                if choice_value in _TRANSITION_VALUES:
                    request_body["message"] = user_msg
                    request_body["action"] = "resolved"
                    request_body["action_value"] = choice_value
                else:
                    request_body["message"] = user_msg
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
                "manual_coverage": data.get("manual_coverage"),
            })
            result["turns"] = turn

            if data.get("manual_coverage"):
                result["manual_coverage"] = data["manual_coverage"]

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

            # 繰り返し検出: AIが前回とほぼ同じ回答を返した場合は診断完了と見なす
            if (
                current_step == "diagnosing"
                and prev_assistant_msg
                and _is_repeated_response(prev_assistant_msg, assistant_msg)
            ):
                result["final_step"] = current_step
                result["final_action"] = "provide_answer"
                return result

            prev_assistant_msg = assistant_msg

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
    print("\n" + "=" * 130)
    print("LLM-as-Judge 評価結果 (v2: 4次元)")
    print("=" * 130)

    header = (
        f"{'#':>3} {'カテゴリ':<14} {'pat':<5} {'turns':>5} "
        f"{'StepAcc':>7} {'Safety':>7} {'ManAdh':>7} {'DiagCmp':>7} "
        f"{'Overall':>7} {'action':<16} {'結果':<6}"
    )
    print(header)
    print("-" * 130)

    total_scores = {
        "step_accuracy": 0,
        "safety_compliance": 0,
        "manual_adherence": 0,
        "diagnostic_completeness": 0,
        "overall_score": 0.0,
    }
    evaluated = 0
    safety_counted = 0

    for r in results:
        if r.get("error"):
            print(f"{r['id']:>3} {r['category']:<14} ERROR: {r['error'][:80]}")
            continue

        judge = r.get("judge", {})
        if not judge or judge.get("overall_score", 0) == 0:
            print(f"{r['id']:>3} {r['category']:<14} JUDGE ERROR")
            continue

        evaluated += 1
        total_scores["step_accuracy"] += judge.get("step_accuracy", 0)
        total_scores["manual_adherence"] += judge.get("manual_adherence", 0)
        total_scores["diagnostic_completeness"] += judge.get("diagnostic_completeness", 0)
        total_scores["overall_score"] += judge.get("overall_score", 0)

        safety_na = judge.get("safety_na", False)
        safety_display = "N/A" if safety_na else str(judge.get("safety_compliance", 0))
        if not safety_na:
            total_scores["safety_compliance"] += judge.get("safety_compliance", 0)
            safety_counted += 1

        overall = judge.get("overall_score", 0)
        status = "GOOD" if overall >= 3.5 else "FAIR" if overall >= 2.5 else "POOR"
        pattern = r.get("user_pattern", "co")[:3]

        print(
            f"{r['id']:>3} {r['category']:<14} {pattern:<5} {r['turns']:>5} "
            f"{judge['step_accuracy']:>7} {safety_display:>7} "
            f"{judge['manual_adherence']:>7} {judge['diagnostic_completeness']:>7} "
            f"{overall:>7.1f} {r.get('final_action', 'N/A'):<16} {status:<6}"
        )

    print("-" * 130)

    if evaluated > 0:
        print(f"\n{'■ 平均スコア':}")
        for key, label in [
            ("step_accuracy", "Step Accuracy"),
            ("safety_compliance", "Safety Compliance"),
            ("manual_adherence", "Manual Adherence"),
            ("diagnostic_completeness", "Diagnostic Completeness"),
            ("overall_score", "Overall"),
        ]:
            if key == "safety_compliance":
                divisor = safety_counted if safety_counted > 0 else 1
                avg = total_scores[key] / divisor
                print(f"  {label:<25} {avg:.2f} / 5.0 ({safety_counted} cases, excl. N/A)")
            else:
                avg = total_scores[key] / evaluated
                print(f"  {label:<25} {avg:.2f} / 5.0")

    # コンポーネントメトリクス表示
    _print_component_metrics(results)

    # 評価理由サマリー
    print(f"\n{'■ 評価理由（先頭150文字）':}")
    for r in results:
        if r.get("error"):
            continue
        judge = r.get("judge", {})
        reasoning = judge.get("reasoning", "")[:150].replace("\n", " ")
        print(f"  [{r['id']:02d}] {reasoning}")


def _print_component_metrics(results: list[dict]):
    """コンポーネント別メトリクスを表示する。"""
    metrics_list = [r.get("component_metrics") for r in results if r.get("component_metrics")]
    if not metrics_list:
        return

    print(f"\n{'■ コンポーネントメトリクス':}")

    # Coverage Accuracy
    coverage_vals = [m["coverage_accuracy"] for m in metrics_list if m.get("coverage_accuracy") is not None]
    if coverage_vals:
        avg_coverage = sum(coverage_vals) / len(coverage_vals)
        print(f"  Coverage Accuracy:        {avg_coverage:.0%} ({sum(int(v) for v in coverage_vals)}/{len(coverage_vals)})")

    # Action Accuracy
    action_vals = [m["action_accuracy"] for m in metrics_list if m.get("action_accuracy") is not None]
    if action_vals:
        avg_action = sum(action_vals) / len(action_vals)
        print(f"  Action Accuracy:          {avg_action:.0%} ({sum(int(v) for v in action_vals)}/{len(action_vals)})")

    # Escalation Timing
    timing_vals = [m["escalation_timing_ratio"] for m in metrics_list if m.get("escalation_timing_ratio") is not None]
    if timing_vals:
        avg_timing = sum(timing_vals) / len(timing_vals)
        print(f"  Escalation Timing (avg):  {avg_timing:.2f}x of expected")

    # RAG Precision
    rag_vals = [m["rag_precision_at_5"] for m in metrics_list if m.get("rag_precision_at_5") is not None]
    if rag_vals:
        avg_rag = sum(rag_vals) / len(rag_vals)
        print(f"  RAG Precision@5 (approx): {avg_rag:.0%}")


def save_results(results: list[dict], user_pattern: str = "cooperative"):
    """結果をJSONファイルに保存"""
    output = {
        "timestamp": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "evaluator": "LLM-as-Judge v2 (gpt-4o-mini, 4-dim)",
        "user_pattern": user_pattern,
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
            "manual_coverage": r.get("manual_coverage"),
            "user_pattern": r.get("user_pattern"),
            "error": r.get("error"),
            "judge": r.get("judge"),
            "component_metrics": r.get("component_metrics"),
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

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pattern_suffix = f"_{user_pattern}" if user_pattern != "cooperative" else ""
    output_path = os.path.join(output_dir, f"judge_eval_{timestamp}{pattern_suffix}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n結果を保存しました: {output_path}")
    return output_path


async def rejudge_from_file(filepath: str, judge: LLMJudge):
    """保存済み会話ログを再Judgeする（会話は再実行しない）"""
    with open(filepath, encoding="utf-8") as f:
        saved = json.load(f)

    results = []
    for saved_result in saved.get("results", []):
        case_id = saved_result["id"]
        tc = next((t for t in TEST_CASES if t["id"] == case_id), None)
        if not tc:
            print(f"  [{case_id:02d}] テストケース未発見、スキップ")
            continue

        conversation_log = saved_result.get("conversation_log", [])
        if not conversation_log:
            print(f"  [{case_id:02d}] 会話ログなし、スキップ")
            continue

        print(f"  [{case_id:02d}] {tc['category']}: Re-judging...")
        conversation_text = format_conversation_log(conversation_log)
        judge_result = await judge.evaluate(conversation_text, tc)

        r = {
            **saved_result,
            "judge": judge_result,
        }
        # コンポーネントメトリクス再計算
        r["component_metrics"] = compute_component_metrics(r, tc, judge_result)

        overall = judge_result.get("overall_score", 0)
        print(f"       Judge score: {overall:.1f}/5.0")
        results.append(r)

    return results


async def run_single_pattern(
    client: httpx.AsyncClient,
    cases: list[dict],
    judge: LLMJudge,
    max_turns: int,
    user_pattern: str,
) -> list[dict]:
    """1つのユーザーパターンで全ケースを実行・評価する。"""
    results = []

    for tc in cases:
        print(f"\n  [{tc['id']:02d}] {tc['category']}: {tc['symptom'][:30]}... (pattern={user_pattern})")

        flow_result = await run_multi_turn_flow(
            client, tc, max_turns=max_turns, user_pattern=user_pattern,
        )

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

        # コンポーネントメトリクス
        flow_result["component_metrics"] = compute_component_metrics(
            flow_result, tc, judge_result,
        )

        overall = judge_result.get("overall_score", 0)
        print(f"       Judge score: {overall:.1f}/5.0")

        results.append(flow_result)

    return results


def merge_pattern_results(all_pattern_results: dict[str, list[dict]]) -> list[dict]:
    """複数パターンの結果を統合し、各ケースの最低スコアを採用する。"""
    # ケースIDごとに全パターンの結果を集約
    case_results: dict[int, list[dict]] = {}
    for _pattern, results in all_pattern_results.items():
        for r in results:
            case_id = r["id"]
            if case_id not in case_results:
                case_results[case_id] = []
            case_results[case_id].append(r)

    merged = []
    for case_id in sorted(case_results.keys()):
        variants = case_results[case_id]
        # 最低overall_scoreのものを採用
        best = min(
            variants,
            key=lambda r: r.get("judge", {}).get("overall_score", 999),
        )
        best["all_pattern_scores"] = {
            r.get("user_pattern", "?"): r.get("judge", {}).get("overall_score", 0)
            for r in variants
        }
        merged.append(best)

    return merged


async def main():
    parser = argparse.ArgumentParser(description="LLM-as-Judge マルチターン評価 v2")
    parser.add_argument("--cases", type=str, help="評価するケースID (カンマ区切り)", default=None)
    parser.add_argument("--max-turns", type=int, help="最大ターン数", default=DEFAULT_MAX_TURNS)
    parser.add_argument("--user-pattern", type=str, help="ユーザーパターン (cooperative/uncertain/verbose)", default="cooperative")
    parser.add_argument("--full", action="store_true", help="全パターンで実行し最低スコアを採用")
    parser.add_argument("--rejudge", type=str, help="既存結果ファイルを再Judge", default=None)
    args = parser.parse_args()

    case_ids = None
    if args.cases:
        case_ids = [int(x) for x in args.cases.split(",")]

    cases = TEST_CASES if case_ids is None else [
        tc for tc in TEST_CASES if tc["id"] in case_ids
    ]

    patterns = list(USER_PATTERNS.keys()) if args.full else [args.user_pattern]

    print("=" * 80)
    print("LLM-as-Judge マルチターン評価 v2 (4次元)")
    print(f"対象API: {BASE_URL}")
    print(f"テストケース数: {len(cases)}")
    print(f"最大ターン数: {args.max_turns}")
    print(f"ユーザーパターン: {', '.join(patterns)}")
    if args.rejudge:
        print(f"再Judge対象: {args.rejudge}")
    print("=" * 80)

    judge = LLMJudge()

    # 再Judgeモード
    if args.rejudge:
        results = await rejudge_from_file(args.rejudge, judge)
        print_judge_results(results)
        save_results(results, user_pattern="rejudge")
        return

    # 接続確認
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            health = await client.get(f"{BASE_URL}/health")
            print(f"\nヘルスチェック: {health.status_code}")
        except httpx.ConnectError:
            print(f"\nエラー: {BASE_URL} に接続できません。")
            print("バックエンドを起動してください: cd backend && uvicorn app.main:app --reload")
            sys.exit(1)

        if len(patterns) == 1:
            # 単一パターンモード
            results = await run_single_pattern(
                client, cases, judge, args.max_turns, patterns[0],
            )
            print_judge_results(results)
            save_results(results, user_pattern=patterns[0])
        else:
            # 全パターンモード: 各パターンで実行して最低スコアを採用
            all_pattern_results: dict[str, list[dict]] = {}
            for pattern in patterns:
                print(f"\n{'='*60}")
                print(f"  パターン: {pattern} — {USER_PATTERNS[pattern]['description']}")
                print(f"{'='*60}")
                pattern_results = await run_single_pattern(
                    client, cases, judge, args.max_turns, pattern,
                )
                all_pattern_results[pattern] = pattern_results

            # 統合: 各ケースの最低スコアを採用
            merged = merge_pattern_results(all_pattern_results)
            print(f"\n{'='*60}")
            print("  統合結果（各ケースの最低スコアを採用）")
            print(f"{'='*60}")
            print_judge_results(merged)
            save_results(merged, user_pattern="full_min")


if __name__ == "__main__":
    asyncio.run(main())
