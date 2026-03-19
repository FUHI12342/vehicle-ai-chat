"""
ルールベース自動検証

LLM-as-Judgeに頼らない決定論的チェック。
E2Eマルチターン結果のJSONを読み込み、以下を検証:

1. Critical安全メッセージ: critical escalateケースに「停車」を含むか
2. not_covered捏造検出: マニュアル外なのに具体手順を案内していないか
3. ループ検出: 同一応答の繰り返しカウント
4. max_turns到達率: 18件中何件がmax_turnsで終了したか
5. expected_action一致率: 期待アクションとの一致
6. step_comparison集計: exact/partial/missing/extra カバレッジ

使い方:
  # 最新のjudge_eval結果を検証
  cd backend
  python -m tests.ragas.rule_based_checker

  # 特定ファイルを検証
  python -m tests.ragas.rule_based_checker --file test_results/judge_eval_xxx.json
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.ragas.test_cases import TEST_CASES
from app.utils.fabrication_patterns import detect_fabrications

# ---------------------------------------------------------------------------
# Check definitions
# ---------------------------------------------------------------------------

# Critical ケース (#1, #10, #11, #12, #13) で期待するキーワード
SAFETY_KEYWORDS = ["停車", "安全な場所", "運転を中止", "ロードサービス"]

# not_covered ケース (#3, #4, #7, #8, #9, #14, #15, #17) — ground_truth に「記載なし」を含む
NOT_COVERED_CASE_IDS = {
    tc["id"]
    for tc in TEST_CASES
    if "記載なし" in tc["ground_truth"] or "記載されていません" in tc["ground_truth"]
}

# 捏造検出は共通ライブラリ (app.utils.fabrication_patterns) に統合済み

CRITICAL_CASE_IDS = {
    tc["id"]
    for tc in TEST_CASES
    if tc["expected_urgency"] == "critical"
}


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    case_id: int | None = None


@dataclass
class CheckSummary:
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult):
        self.total_checks += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1
        self.results.append(result)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _get_assistant_messages(conversation_log: list[dict]) -> list[str]:
    return [e["content"] for e in conversation_log if e["role"] == "assistant"]


def check_critical_safety_message(case_result: dict, summary: CheckSummary):
    """Check 1: Critical ケースのアシスタント応答に安全メッセージが含まれるか"""
    case_id = case_result["id"]
    if case_id not in CRITICAL_CASE_IDS:
        return

    messages = _get_assistant_messages(case_result.get("conversation_log", []))
    all_text = " ".join(messages)

    found_keywords = [kw for kw in SAFETY_KEYWORDS if kw in all_text]
    passed = len(found_keywords) >= 1

    summary.add(CheckResult(
        name="critical_safety_message",
        passed=passed,
        detail=f"found={found_keywords}" if passed else f"安全キーワードなし: {SAFETY_KEYWORDS}",
        case_id=case_id,
    ))


def check_not_covered_fabrication(case_result: dict, summary: CheckSummary):
    """Check 2: not_covered ケースでマニュアル外の具体的手順を捏造していないか"""
    case_id = case_result["id"]
    if case_id not in NOT_COVERED_CASE_IDS:
        return

    messages = _get_assistant_messages(case_result.get("conversation_log", []))
    all_text = " ".join(messages)

    matched = detect_fabrications(all_text)
    passed = len(matched) == 0
    summary.add(CheckResult(
        name="not_covered_no_fabrication",
        passed=passed,
        detail="捏造なし" if passed else f"捏造疑い: {[m.description for m in matched]}",
        case_id=case_id,
    ))


def check_loop_detection(case_result: dict, summary: CheckSummary):
    """Check 3: 同一応答の繰り返しを検出"""
    messages = _get_assistant_messages(case_result.get("conversation_log", []))
    if len(messages) < 3:
        return

    def _normalize(text: str) -> str:
        return re.sub(r"[？?。、！!.,\s　]+", "", text).lower()

    repeat_count = 0
    for i in range(1, len(messages)):
        norm_cur = _normalize(messages[i])
        norm_prev = _normalize(messages[i - 1])
        if not norm_cur or not norm_prev:
            continue
        if norm_cur == norm_prev:
            repeat_count += 1
            continue
        shorter, longer = sorted([norm_cur, norm_prev], key=len)
        if len(shorter) >= 10 and shorter in longer:
            repeat_count += 1

    passed = repeat_count <= 1  # 1回の重複は許容
    summary.add(CheckResult(
        name="loop_detection",
        passed=passed,
        detail=f"repeats={repeat_count}" if passed else f"ループ検出: {repeat_count}回重複",
        case_id=case_result["id"],
    ))


def check_expected_action(case_result: dict, summary: CheckSummary):
    """Check 5: expected_action との一致"""
    case_id = case_result["id"]
    tc = next((t for t in TEST_CASES if t["id"] == case_id), None)
    if not tc:
        return

    actual = case_result.get("final_action", "")
    expected = tc["expected_action"]

    # escalate は reservation step で判定
    if expected == "escalate":
        passed = actual == "escalate"
    elif expected == "spec_answer":
        passed = actual == "spec_answer"
    elif expected == "ask_question":
        # ask_question は provide_answer も許容（会話が完了した場合）
        passed = actual in ("ask_question", "provide_answer", "escalate")
    else:
        passed = actual == expected

    summary.add(CheckResult(
        name="expected_action_match",
        passed=passed,
        detail=f"expected={expected}, actual={actual}",
        case_id=case_id,
    ))


def check_step_comparison_coverage(case_result: dict, summary: CheckSummary):
    """Check 6: step_comparison の exact/partial/missing/extra 集計"""
    judge = case_result.get("judge", {})
    step_comparison = judge.get("step_comparison", [])
    if not step_comparison:
        return

    counts = {"exact": 0, "partial": 0, "missing": 0, "extra": 0}
    for step in step_comparison:
        match_type = step.get("match", "missing")
        counts[match_type] = counts.get(match_type, 0) + 1

    total = counts["exact"] + counts["partial"] + counts["missing"]
    coverage = (counts["exact"] + counts["partial"]) / total if total > 0 else 0
    passed = coverage >= 0.3  # 30%以上をpass（現状18%なので改善を測れる閾値）

    summary.add(CheckResult(
        name="step_coverage",
        passed=passed,
        detail=f"coverage={coverage:.0%} (exact={counts['exact']}, partial={counts['partial']}, missing={counts['missing']}, extra={counts['extra']})",
        case_id=case_result["id"],
    ))


def check_manual_coverage_accuracy(case_result: dict, summary: CheckSummary):
    """Check 7: manual_coverage がground_truthと整合しているか"""
    case_id = case_result["id"]
    tc = next((t for t in TEST_CASES if t["id"] == case_id), None)
    if not tc:
        return

    gt = tc["ground_truth"]
    is_gt_not_covered = "記載なし" in gt or "記載されていません" in gt

    actual_coverage = case_result.get("manual_coverage", "")
    if not actual_coverage:
        return

    if is_gt_not_covered:
        passed = actual_coverage in ("not_covered", "partially_covered")
        expected = "not_covered or partially_covered"
    else:
        passed = actual_coverage in ("covered", "partially_covered")
        expected = "covered or partially_covered"

    summary.add(CheckResult(
        name="manual_coverage_accuracy",
        passed=passed,
        detail=f"expected={expected}, actual={actual_coverage}",
        case_id=case_id,
    ))


def check_sparse_retrieval_fabrication(case_result: dict, summary: CheckSummary):
    """Check 8: not_coveredケースで全assistantメッセージに捏造パターンがないか（拡張版）"""
    case_id = case_result["id"]
    if case_id not in NOT_COVERED_CASE_IDS:
        return

    messages = _get_assistant_messages(case_result.get("conversation_log", []))
    all_matched = []
    for msg in messages:
        matched = detect_fabrications(msg)
        all_matched.extend(matched)

    passed = len(all_matched) == 0
    summary.add(CheckResult(
        name="sparse_retrieval_no_fabrication",
        passed=passed,
        detail="捏造なし" if passed else f"捏造検出({len(all_matched)}件): {list({m.description for m in all_matched})}",
        case_id=case_id,
    ))


# ---------------------------------------------------------------------------
# Aggregate checks
# ---------------------------------------------------------------------------

def check_max_turns_rate(results: list[dict], summary: CheckSummary):
    """Check 4: max_turns到達率"""
    valid = [r for r in results if not r.get("error")]
    max_turns_count = sum(
        1 for r in valid if r.get("final_action") == "max_turns_reached"
    )
    rate = max_turns_count / len(valid) if valid else 0
    passed = rate <= 0.40  # 40%以下をpass（現状55%=10/18なので改善を測れる）

    summary.add(CheckResult(
        name="max_turns_rate",
        passed=passed,
        detail=f"{max_turns_count}/{len(valid)} ({rate:.0%})",
    ))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all_checks(results: list[dict]) -> CheckSummary:
    """全チェックを実行"""
    summary = CheckSummary()

    for r in results:
        if r.get("error"):
            continue
        check_critical_safety_message(r, summary)
        check_not_covered_fabrication(r, summary)
        check_loop_detection(r, summary)
        check_expected_action(r, summary)
        check_step_comparison_coverage(r, summary)
        check_manual_coverage_accuracy(r, summary)
        check_sparse_retrieval_fabrication(r, summary)

    # Aggregate checks
    check_max_turns_rate(results, summary)

    return summary


def print_summary(summary: CheckSummary):
    """結果をコンソール表示"""
    print("\n" + "=" * 100)
    print("ルールベース自動検証 結果")
    print("=" * 100)

    # Group by check name
    by_name: dict[str, list[CheckResult]] = {}
    for r in summary.results:
        by_name.setdefault(r.name, []).append(r)

    for name, checks in by_name.items():
        passed_count = sum(1 for c in checks if c.passed)
        total = len(checks)
        status = "PASS" if passed_count == total else "FAIL"
        print(f"\n  [{status}] {name}: {passed_count}/{total}")

        for c in checks:
            icon = "  ✓" if c.passed else "  ✗"
            case_label = f"[#{c.case_id:02d}] " if c.case_id else ""
            print(f"    {icon} {case_label}{c.detail}")

    print("\n" + "-" * 100)
    print(f"  合計: {summary.passed}/{summary.total_checks} passed, {summary.failed} failed")
    print("=" * 100)


def find_latest_judge_result() -> str | None:
    """test_results/ から最新の judge_eval_*.json を探す"""
    results_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_results")
    if not os.path.isdir(results_dir):
        return None
    files = sorted(
        [f for f in os.listdir(results_dir) if f.startswith("judge_eval_") and f.endswith(".json")],
        reverse=True,
    )
    return os.path.join(results_dir, files[0]) if files else None


def main():
    parser = argparse.ArgumentParser(description="ルールベース自動検証")
    parser.add_argument("--file", type=str, help="検証するJSONファイルパス", default=None)
    args = parser.parse_args()

    filepath = args.file or find_latest_judge_result()
    if not filepath or not os.path.exists(filepath):
        print("エラー: 検証対象のJSONファイルが見つかりません。")
        print("  --file で指定するか、run_judge_eval.py を先に実行してください。")
        sys.exit(1)

    print(f"検証対象: {filepath}")

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results", [])
    if not results:
        print("エラー: results が空です。")
        sys.exit(1)

    summary = run_all_checks(results)
    print_summary(summary)

    # Exit code: 0 if all passed, 1 if any failed
    sys.exit(0 if summary.failed == 0 else 1)


if __name__ == "__main__":
    main()
