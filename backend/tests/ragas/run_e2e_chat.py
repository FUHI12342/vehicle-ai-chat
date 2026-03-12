"""
E2Eチャットフローテスト

ローカルのFastAPIサーバーにHTTPリクエストを送り、
各テストケースで問診フローを実行して結果を検証する。

前提: バックエンドが起動済み (uvicorn app.main:app)

使い方:
  cd backend
  python -m tests.ragas.run_e2e_chat              # 単一ターン（従来）
  python -m tests.ragas.run_e2e_chat --multi-turn  # マルチターン
  python -m tests.ragas.run_e2e_chat --multi-turn --max-turns 8
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.ragas.test_cases import TEST_CASES

BASE_URL = os.environ.get("CHAT_API_URL", "http://localhost:8000/api")
TIMEOUT = 30.0
DEFAULT_MAX_TURNS = 12


async def run_chat_flow(client: httpx.AsyncClient, tc: dict) -> dict:
    """1テストケースの問診フローを実行"""
    result = {
        "id": tc["id"],
        "category": tc["category"],
        "symptom": tc["symptom"],
        "steps": [],
        "final_response": None,
        "urgency_flag": None,
        "action": None,
        "manual_coverage": None,
        "error": None,
    }

    try:
        # Step 1: セッション作成（初回リクエストでセッション取得）
        resp = await client.post(f"{BASE_URL}/chat", json={})
        resp.raise_for_status()
        data = resp.json()
        session_id = data["session_id"]
        result["steps"].append({"step": data["current_step"], "action": "session_create"})

        # Step 2: 車両選択（action: select_vehicle）
        resp = await client.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "action": "select_vehicle",
            "action_value": tc["vehicle_id"],
        })
        resp.raise_for_status()
        data = resp.json()
        result["steps"].append({"step": data["current_step"], "action": "vehicle_select"})

        # Step 3: 写真確認（action: confirm, value: yes）
        resp = await client.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "action": "confirm",
            "action_value": "yes",
        })
        resp.raise_for_status()
        data = resp.json()
        result["steps"].append({"step": data["current_step"], "action": "photo_confirm"})

        # Step 4: 症状入力
        resp = await client.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "message": tc["symptom"],
        })
        resp.raise_for_status()
        data = resp.json()
        result["steps"].append({"step": data["current_step"], "action": "symptom_input"})

        # 結果を記録
        result["final_response"] = data
        result["manual_coverage"] = data.get("manual_coverage")
        result["current_step"] = data.get("current_step", "")
        result["prompt_message"] = data.get("prompt", {}).get("message", "")[:200]

        current_step = data.get("current_step", "")

        # urgency情報を取得
        if data.get("urgency"):
            result["urgency_flag"] = data["urgency"].get("level")

        # current_stepからactionを判定
        if current_step == "reservation":
            result["action"] = "escalate"
        elif current_step == "spec_check":
            result["action"] = "spec_answer"
        elif current_step == "diagnosing":
            result["action"] = "ask_question"
        elif current_step == "urgency_check":
            # urgency_checkに直接進んだ場合
            result["action"] = "ask_question"

    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        result["error"] = f"接続エラー: {BASE_URL} に接続できません。バックエンドが起動しているか確認してください。"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"

    return result


def evaluate_results(results: list[dict]) -> dict:
    """テスト結果を集計"""
    total = len(results)
    errors = sum(1 for r in results if r["error"])
    successful = total - errors

    urgency_match = 0
    action_match = 0

    for r in results:
        if r["error"]:
            continue

        tc = next(t for t in TEST_CASES if t["id"] == r["id"])

        if r["urgency_flag"] == tc["expected_urgency"]:
            urgency_match += 1

        if r["action"] == tc["expected_action"]:
            action_match += 1

    return {
        "total": total,
        "successful": successful,
        "errors": errors,
        "urgency_match": urgency_match,
        "urgency_rate": urgency_match / successful if successful > 0 else 0,
        "action_match": action_match,
        "action_rate": action_match / successful if successful > 0 else 0,
    }


def print_results(results: list[dict], summary: dict):
    """結果をコンソール表示"""
    print("\n" + "=" * 110)
    print("E2E チャットフロー テスト結果")
    print("=" * 110)

    header = f"{'#':>3} {'カテゴリ':<16} {'step':<14} {'期待urg':<10} {'実際urg':<10} {'期待act':<14} {'実際act':<14} {'coverage':<12} {'結果':<6}"
    print(header)
    print("-" * 120)

    for r in results:
        if r["error"]:
            print(f"{r['id']:>3} {r['category']:<16} {'ERROR':<80} {r['error'][:50]}")
            continue

        tc = next(t for t in TEST_CASES if t["id"] == r["id"])
        act_ok = r["action"] == tc["expected_action"]
        # urgencyは初回ターンでcritical以外返らないので、critical以外はactionのみで判定
        if tc["expected_urgency"] == "critical":
            urg_ok = r["urgency_flag"] == tc["expected_urgency"]
            status = "PASS" if urg_ok and act_ok else "FAIL"
        else:
            urg_ok = True  # 初回ターンでは未判定（後続ターンで判定される）
            status = "PASS" if act_ok else "FAIL"

        urg_actual = r["urgency_flag"] or "-"
        act_actual = r["action"] or "N/A"
        step = r.get("current_step", "?")
        coverage = r.get("manual_coverage") or "-"

        print(
            f"{r['id']:>3} {r['category']:<16} "
            f"{step:<14} "
            f"{tc['expected_urgency']:<10} {urg_actual:<10} "
            f"{tc['expected_action']:<14} {act_actual:<14} "
            f"{coverage:<12} "
            f"{status:<6}"
        )

    print("-" * 120)

    # レスポンスメッセージも表示
    print("\n■ 各ケースの応答メッセージ（先頭100文字）:")
    for r in results:
        if r["error"]:
            continue
        msg = r.get("prompt_message", "")[:100].replace("\n", " ")
        print(f"  [{r['id']:02d}] {msg}")

    print(f"\n■ サマリー:")
    print(f"  実行: {summary['total']}件  成功: {summary['successful']}件  エラー: {summary['errors']}件")
    print(f"  action一致率: {summary['action_match']}/{summary['successful']} ({summary['action_rate']:.0%})")
    print(f"  urgency一致率 (critical判定): {summary['urgency_match']}/{summary['successful']} ({summary['urgency_rate']:.0%})")


async def run_multi_turn_flow(
    client: httpx.AsyncClient, tc: dict, max_turns: int = DEFAULT_MAX_TURNS
) -> dict:
    """1テストケースのマルチターン問診フローを実行"""
    result = {
        "id": tc["id"],
        "category": tc["category"],
        "symptom": tc["symptom"],
        "steps": [],
        "conversation_log": [],
        "final_response": None,
        "urgency_flag": None,
        "action": None,
        "manual_coverage": None,
        "turns": 0,
        "error": None,
    }

    try:
        # Steps 1-3: session → vehicle → photo (same as single-turn)
        resp = await client.post(f"{BASE_URL}/chat", json={})
        resp.raise_for_status()
        data = resp.json()
        session_id = data["session_id"]
        result["steps"].append({"step": data["current_step"], "action": "session_create"})

        resp = await client.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "action": "select_vehicle",
            "action_value": tc["vehicle_id"],
        })
        resp.raise_for_status()
        data = resp.json()
        result["steps"].append({"step": data["current_step"], "action": "vehicle_select"})

        resp = await client.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "action": "confirm",
            "action_value": "yes",
        })
        resp.raise_for_status()
        data = resp.json()
        result["steps"].append({"step": data["current_step"], "action": "photo_confirm"})

        # Step 4: 症状入力
        resp = await client.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "message": tc["symptom"],
        })
        resp.raise_for_status()
        data = resp.json()
        result["steps"].append({"step": data["current_step"], "action": "symptom_input"})

        # 初回レスポンスを記録
        result["conversation_log"].append({"role": "user", "content": tc["symptom"]})
        prompt_msg = data.get("prompt", {}).get("message", "")
        result["conversation_log"].append({
            "role": "assistant",
            "content": prompt_msg,
            "step": data.get("current_step"),
            "choices": data.get("prompt", {}).get("choices"),
        })
        result["turns"] = 1
        result["final_response"] = data
        result["manual_coverage"] = data.get("manual_coverage")
        result["current_step"] = data.get("current_step", "")
        result["prompt_message"] = prompt_msg[:200]

        if data.get("urgency"):
            result["urgency_flag"] = data["urgency"].get("level")

        current_step = data.get("current_step", "")

        # 初回で終了するケース
        if current_step == "reservation":
            result["action"] = "escalate"
            return result
        if current_step == "spec_check":
            result["action"] = "spec_answer"
            return result

        result["action"] = "ask_question"

        # マルチターンループ
        for turn in range(2, max_turns + 1):
            choices = data.get("prompt", {}).get("choices")

            if not choices:
                user_msg = "はい"
            else:
                if isinstance(choices[0], dict):
                    user_msg = choices[0].get("label", choices[0].get("text", "はい"))
                else:
                    user_msg = str(choices[0])

            resp = await client.post(f"{BASE_URL}/chat", json={
                "session_id": session_id,
                "message": user_msg,
            })
            resp.raise_for_status()
            data = resp.json()

            result["conversation_log"].append({"role": "user", "content": user_msg})
            assistant_msg = data.get("prompt", {}).get("message", "")
            result["conversation_log"].append({
                "role": "assistant",
                "content": assistant_msg,
                "step": data.get("current_step"),
                "choices": data.get("prompt", {}).get("choices"),
            })
            result["turns"] = turn
            result["final_response"] = data
            result["current_step"] = data.get("current_step", "")
            result["prompt_message"] = assistant_msg[:200]

            if data.get("urgency"):
                result["urgency_flag"] = data["urgency"].get("level")
            if data.get("manual_coverage"):
                result["manual_coverage"] = data["manual_coverage"]

            current_step = data.get("current_step", "")

            if current_step in ("reservation", "done", "urgency_check"):
                result["action"] = "escalate" if current_step == "reservation" else "provide_answer"
                return result

            if current_step == "diagnosing" and not data.get("prompt", {}).get("choices"):
                result["action"] = "provide_answer"
                return result

        result["action"] = "max_turns_reached"

    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        result["error"] = f"接続エラー: {BASE_URL} に接続できません。"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"

    return result


def save_results(results: list[dict], summary: dict):
    """結果をJSONファイルに保存"""
    output = {
        "timestamp": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "summary": summary,
        "results": [],
    }

    for r in results:
        case_output = {
            "id": r["id"],
            "category": r["category"],
            "symptom": r["symptom"],
            "current_step": r.get("current_step"),
            "urgency_flag": r["urgency_flag"],
            "action": r["action"],
            "manual_coverage": r["manual_coverage"],
            "prompt_message": r.get("prompt_message"),
            "error": r["error"],
            "steps_count": len(r["steps"]),
        }
        output["results"].append(case_output)

    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_results")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"e2e_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n結果を保存しました: {output_path}")


async def main():
    parser = argparse.ArgumentParser(description="E2E チャットフローテスト")
    parser.add_argument("--multi-turn", action="store_true", help="マルチターンモードで実行")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="最大ターン数")
    args = parser.parse_args()

    mode = "マルチターン" if args.multi_turn else "単一ターン"
    print("=" * 60)
    print(f"E2E チャットフローテスト（{mode}）")
    print(f"対象API: {BASE_URL}")
    print(f"テストケース数: {len(TEST_CASES)}")
    if args.multi_turn:
        print(f"最大ターン数: {args.max_turns}")
    print("=" * 60)

    # 接続確認
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            health = await client.get(f"{BASE_URL}/health")
            print(f"\nヘルスチェック: {health.status_code}")
        except httpx.ConnectError:
            print(f"\nエラー: {BASE_URL} に接続できません。")
            print("バックエンドを起動してください: cd backend && uvicorn app.main:app --reload")
            sys.exit(1)

        # 各テストケースを順次実行
        results = []
        for tc in TEST_CASES:
            print(f"\n  [{tc['id']:02d}] {tc['category']}: {tc['symptom'][:30]}...")

            if args.multi_turn:
                result = await run_multi_turn_flow(client, tc, max_turns=args.max_turns)
            else:
                result = await run_chat_flow(client, tc)
            results.append(result)

            if result["error"]:
                print(f"       ERROR: {result['error'][:60]}")
            else:
                turns_info = f", turns={result['turns']}" if args.multi_turn else ""
                print(f"       urgency={result['urgency_flag']}, action={result['action']}{turns_info}")

    # 集計・表示・保存
    summary = evaluate_results(results)
    print_results(results, summary)
    save_results(results, summary)


if __name__ == "__main__":
    asyncio.run(main())
