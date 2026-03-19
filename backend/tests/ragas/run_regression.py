"""
回帰テスト — 3修正の効果検証

4つの問題ケースに対して E2E マルチターン会話を実行し、
修正が正しく機能しているか具体的にアサーションする:

- Case #1 (ブレーキ故障): 「停車」→ 確認手順 → escalate の流れ
- Case #8 (ハンドル重い): not_covered → escalate（捏造なし）
- Case #10 (オーバーヒート): 安全手順を案内してからescalate
- Case #12 (火災兆候): not_covered → escalate（消火手順捏造なし）

前提: バックエンドが起動済み (uvicorn app.main:app)

使い方:
  cd backend
  python -m tests.ragas.run_regression
  python -m tests.ragas.run_regression --max-turns 8
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.ragas.test_cases import TEST_CASES
from tests.ragas.run_judge_eval import run_multi_turn_flow, format_conversation_log
from app.utils.fabrication_patterns import detect_fabrications

BASE_URL = os.environ.get("CHAT_API_URL", "http://localhost:8000/api")
TIMEOUT = 30.0

REGRESSION_CASE_IDS = [1, 8, 10, 12]

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

# 捏造検出は共通ライブラリ (app.utils.fabrication_patterns) に統合済み


def _assistant_messages(log: list[dict]) -> list[str]:
    return [e["content"] for e in log if e["role"] == "assistant"]


def _all_assistant_text(log: list[dict]) -> str:
    return " ".join(_assistant_messages(log))


class AssertionResult:
    def __init__(self, case_id: int, name: str, passed: bool, detail: str):
        self.case_id = case_id
        self.name = name
        self.passed = passed
        self.detail = detail


# ---------------------------------------------------------------------------
# Per-case assertions
# ---------------------------------------------------------------------------

def assert_case_1(result: dict) -> list[AssertionResult]:
    """Case #1: ブレーキ故障 — 安全手順 → escalate"""
    assertions = []
    log = result.get("conversation_log", [])
    text = _all_assistant_text(log)
    msgs = _assistant_messages(log)

    # Fix 1: 「停車」が会話に含まれる（即escalateではなく安全手順あり）
    has_stop = "停車" in text or "安全な場所" in text
    assertions.append(AssertionResult(
        1, "safety_stop_message", has_stop,
        "「停車」メッセージあり" if has_stop else "「停車」メッセージなし — 安全手順スキップ",
    ))

    # Fix 1: 1ターンで即escalateしていない（2ターン以上の会話がある）
    turns = result.get("turns", 0)
    multi_turn = turns >= 2
    assertions.append(AssertionResult(
        1, "not_instant_escalate", multi_turn,
        f"turns={turns}" if multi_turn else "1ターンで即escalate — 安全手順なし",
    ))

    # 最終的にescalate/reservationに到達
    final_action = result.get("final_action", "")
    final_step = result.get("final_step", "")
    reached_escalate = final_action == "escalate" or final_step == "reservation"
    assertions.append(AssertionResult(
        1, "reaches_escalate", reached_escalate,
        f"final_action={final_action}" if reached_escalate else f"escalateに未到達: action={final_action}",
    ))

    # ブレーキ関連の確認手順が含まれる（ブレーキ液 or ペダル）
    has_brake_check = "ブレーキ液" in text or "ペダル" in text or "ブレーキ" in text
    assertions.append(AssertionResult(
        1, "brake_check_mentioned", has_brake_check,
        "ブレーキ確認手順あり" if has_brake_check else "ブレーキ確認手順なし",
    ))

    return assertions


def assert_case_8(result: dict) -> list[AssertionResult]:
    """Case #8: ハンドル重い — not_covered → escalate（捏造なし）"""
    assertions = []
    log = result.get("conversation_log", [])
    text = _all_assistant_text(log)

    # Fix 2: パワステオイル等の捏造がない
    matched = detect_fabrications(text)
    no_fabrication = len(matched) == 0
    assertions.append(AssertionResult(
        8, "no_fabrication", no_fabrication,
        "捏造なし" if no_fabrication else f"捏造検出: {[m.description for m in matched]}",
    ))

    # ディーラー/販売店への誘導がある
    has_dealer = "ディーラー" in text or "販売店" in text or "点検" in text
    assertions.append(AssertionResult(
        8, "dealer_recommendation", has_dealer,
        "ディーラー推奨あり" if has_dealer else "ディーラー推奨なし",
    ))

    # max_turnsに到達していない（ループしていない）
    final_action = result.get("final_action", "")
    not_max_turns = final_action != "max_turns_reached"
    assertions.append(AssertionResult(
        8, "no_max_turns", not_max_turns,
        f"action={final_action}" if not_max_turns else "max_turns到達 — ループまたは解決不能",
    ))

    return assertions


def assert_case_10(result: dict) -> list[AssertionResult]:
    """Case #10: オーバーヒート — 安全手順を案内してからescalate"""
    assertions = []
    log = result.get("conversation_log", [])
    text = _all_assistant_text(log)
    msgs = _assistant_messages(log)

    # Fix 1: 「停車」が会話に含まれる
    has_stop = "停車" in text or "安全な場所" in text
    assertions.append(AssertionResult(
        10, "safety_stop_message", has_stop,
        "「停車」メッセージあり" if has_stop else "「停車」メッセージなし",
    ))

    # 1ターン即escalateしていない
    turns = result.get("turns", 0)
    multi_turn = turns >= 2
    assertions.append(AssertionResult(
        10, "not_instant_escalate", multi_turn,
        f"turns={turns}" if multi_turn else "1ターンで即escalate",
    ))

    # オーバーヒート関連の確認手順が含まれる
    oh_keywords = ["冷却", "水温", "蒸気", "ボンネット", "エンジン"]
    found = [kw for kw in oh_keywords if kw in text]
    has_oh_steps = len(found) >= 2
    assertions.append(AssertionResult(
        10, "overheat_steps_mentioned", has_oh_steps,
        f"関連キーワード: {found}" if has_oh_steps else f"オーバーヒート手順不足: {found}",
    ))

    # 最終的にescalateに到達
    final_action = result.get("final_action", "")
    final_step = result.get("final_step", "")
    reached_escalate = final_action == "escalate" or final_step == "reservation"
    assertions.append(AssertionResult(
        10, "reaches_escalate", reached_escalate,
        f"final_action={final_action}" if reached_escalate else f"escalateに未到達: action={final_action}",
    ))

    return assertions


def assert_case_12(result: dict) -> list[AssertionResult]:
    """Case #12: 火災兆候 — not_covered → escalate（消火手順捏造なし）"""
    assertions = []
    log = result.get("conversation_log", [])
    text = _all_assistant_text(log)

    # Fix 2: 消火手順の捏造がない
    matched = detect_fabrications(text)
    no_fabrication = len(matched) == 0
    assertions.append(AssertionResult(
        12, "no_fabrication", no_fabrication,
        "捏造なし" if no_fabrication else f"捏造検出: {[m.description for m in matched]}",
    ))

    # escalate に到達（火災は即escalateが正しい）
    final_action = result.get("final_action", "")
    final_step = result.get("final_step", "")
    reached_escalate = final_action == "escalate" or final_step == "reservation"
    assertions.append(AssertionResult(
        12, "reaches_escalate", reached_escalate,
        f"final_action={final_action}" if reached_escalate else f"escalateに未到達: action={final_action}",
    ))

    # 避難・通報の案内がある
    has_evac = any(kw in text for kw in ("避難", "車外", "離れ", "119", "通報", "消防", "緊急サービス"))
    assertions.append(AssertionResult(
        12, "evacuation_mentioned", has_evac,
        "避難/通報案内あり" if has_evac else "避難/通報案内なし",
    ))

    # max_turnsに到達していない
    not_max_turns = final_action != "max_turns_reached"
    assertions.append(AssertionResult(
        12, "no_max_turns", not_max_turns,
        f"action={final_action}" if not_max_turns else "max_turns到達",
    ))

    return assertions


CASE_ASSERTORS = {
    1: assert_case_1,
    8: assert_case_8,
    10: assert_case_10,
    12: assert_case_12,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_regression(max_turns: int) -> dict:
    """E2E実行 + アサーション"""
    cases = [tc for tc in TEST_CASES if tc["id"] in REGRESSION_CASE_IDS]

    print("=" * 80)
    print("回帰テスト — 3修正の効果検証")
    print(f"対象API: {BASE_URL}")
    print(f"対象ケース: {REGRESSION_CASE_IDS}")
    print(f"最大ターン数: {max_turns}")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            health = await client.get(f"{BASE_URL}/health")
            print(f"\nヘルスチェック: {health.status_code}")
        except httpx.ConnectError:
            print(f"\nエラー: {BASE_URL} に接続できません。")
            print("バックエンドを起動してください: cd backend && uvicorn app.main:app --reload")
            sys.exit(1)

        flow_results = {}
        for tc in cases:
            print(f"\n  [#{tc['id']:02d}] {tc['category']}: {tc['symptom'][:30]}...")
            flow_result = await run_multi_turn_flow(client, tc, max_turns=max_turns)

            if flow_result.get("error"):
                print(f"       ERROR: {flow_result['error'][:60]}")
            else:
                print(f"       turns={flow_result['turns']}, action={flow_result.get('final_action')}")

            flow_results[tc["id"]] = flow_result

    # Run assertions
    all_assertions: list[AssertionResult] = []
    for case_id, assertor in CASE_ASSERTORS.items():
        result = flow_results.get(case_id)
        if not result or result.get("error"):
            all_assertions.append(AssertionResult(
                case_id, "e2e_execution", False, f"E2E実行エラー: {result.get('error', 'no result')}",
            ))
            continue
        all_assertions.extend(assertor(result))

    return {
        "flow_results": flow_results,
        "assertions": all_assertions,
    }


def print_regression_report(all_assertions: list[AssertionResult]):
    """結果表示"""
    print("\n" + "=" * 100)
    print("回帰テスト結果")
    print("=" * 100)

    by_case: dict[int, list[AssertionResult]] = {}
    for a in all_assertions:
        by_case.setdefault(a.case_id, []).append(a)

    total_passed = 0
    total_failed = 0

    for case_id in sorted(by_case.keys()):
        assertions = by_case[case_id]
        case_passed = sum(1 for a in assertions if a.passed)
        case_total = len(assertions)
        tc = next((t for t in TEST_CASES if t["id"] == case_id), None)
        category = tc["category"] if tc else "?"

        status = "PASS" if case_passed == case_total else "FAIL"
        print(f"\n  [{status}] Case #{case_id} ({category}): {case_passed}/{case_total}")

        for a in assertions:
            icon = "  ✓" if a.passed else "  ✗"
            print(f"    {icon} {a.name}: {a.detail}")

        total_passed += case_passed
        total_failed += (case_total - case_passed)

    total = total_passed + total_failed
    print("\n" + "-" * 100)
    print(f"  合計: {total_passed}/{total} passed, {total_failed} failed")

    if total_failed == 0:
        print("  全アサーション PASS — 3修正の回帰テスト合格")
    else:
        print("  一部アサーション FAIL — 修正の効果が不十分な箇所あり")
    print("=" * 100)


def save_regression_results(
    flow_results: dict, assertions: list[AssertionResult]
) -> str:
    output = {
        "timestamp": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "cases": REGRESSION_CASE_IDS,
        "results": [],
    }

    for case_id in REGRESSION_CASE_IDS:
        fr = flow_results.get(case_id, {})
        case_assertions = [a for a in assertions if a.case_id == case_id]
        output["results"].append({
            "case_id": case_id,
            "turns": fr.get("turns", 0),
            "final_action": fr.get("final_action"),
            "error": fr.get("error"),
            "assertions": [
                {"name": a.name, "passed": a.passed, "detail": a.detail}
                for a in case_assertions
            ],
            "conversation_log": fr.get("conversation_log", []),
        })

    total = sum(1 for a in assertions if a.passed)
    output["summary"] = {
        "total_assertions": len(assertions),
        "passed": total,
        "failed": len(assertions) - total,
    }

    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_results")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(
        output_dir, f"regression_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n結果を保存しました: {output_path}")
    return output_path


async def main():
    parser = argparse.ArgumentParser(description="回帰テスト — 3修正の効果検証")
    parser.add_argument("--max-turns", type=int, default=12, help="最大ターン数")
    args = parser.parse_args()

    result = await run_regression(args.max_turns)
    print_regression_report(result["assertions"])
    save_regression_results(result["flow_results"], result["assertions"])

    # Exit code
    failed = sum(1 for a in result["assertions"] if not a.passed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
