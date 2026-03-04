"""
E2Eチャットフローテスト

ローカルのFastAPIサーバーにHTTPリクエストを送り、
各テストケースで問診フローを実行して結果を検証する。

前提: バックエンドが起動済み (uvicorn app.main:app)

使い方:
  cd backend
  python -m tests.ragas.run_e2e_chat
"""

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
        # Step 1: セッション作成 + 車両ID送信
        resp = await client.post(f"{BASE_URL}/chat", json={
            "message": tc["vehicle_id"],
        })
        resp.raise_for_status()
        data = resp.json()
        session_id = data["session_id"]
        result["steps"].append({"step": data["current_step"], "action": "vehicle_id"})

        # Step 2: 写真確認 → "はい"
        resp = await client.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "message": "はい",
        })
        resp.raise_for_status()
        data = resp.json()
        result["steps"].append({"step": data["current_step"], "action": "photo_confirm"})

        # Step 3: 症状入力
        resp = await client.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "message": tc["symptom"],
        })
        resp.raise_for_status()
        data = resp.json()
        result["steps"].append({"step": data["current_step"], "action": "symptom_input"})

        # 結果を記録（spec_check or diagnosing の最初のレスポンス）
        result["final_response"] = data
        result["manual_coverage"] = data.get("manual_coverage")

        # urgency情報を取得
        if data.get("urgency"):
            result["urgency_flag"] = data["urgency"].get("level")

        # promptからactionを推定
        current_step = data.get("current_step", "")
        prompt_type = data.get("prompt", {}).get("type", "")
        prompt_message = data.get("prompt", {}).get("message", "")

        if current_step == "spec_check":
            result["action"] = "spec_answer"
        elif current_step == "reservation":
            result["action"] = "escalate"
            if data.get("urgency"):
                result["urgency_flag"] = data["urgency"].get("level")
        elif current_step == "diagnosing":
            # diagnosingステップの場合、選択肢があればask_question
            if data.get("prompt", {}).get("choices"):
                result["action"] = "ask_question"
            else:
                result["action"] = "ask_question"

        # urgency_checkに進んでいればurgencyを取得
        if current_step == "urgency_check":
            if data.get("urgency"):
                result["urgency_flag"] = data["urgency"].get("level")

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

    header = f"{'#':>3} {'カテゴリ':<16} {'期待urgency':<12} {'実際urgency':<12} {'期待action':<14} {'実際action':<14} {'結果':<6}"
    print(header)
    print("-" * 110)

    for r in results:
        if r["error"]:
            print(f"{r['id']:>3} {r['category']:<16} {'ERROR':<60} {r['error'][:50]}")
            continue

        tc = next(t for t in TEST_CASES if t["id"] == r["id"])
        urg_ok = "OK" if r["urgency_flag"] == tc["expected_urgency"] else "NG"
        act_ok = "OK" if r["action"] == tc["expected_action"] else "NG"
        status = "PASS" if urg_ok == "OK" and act_ok == "OK" else "FAIL"

        urg_actual = r["urgency_flag"] or "N/A"
        act_actual = r["action"] or "N/A"

        print(
            f"{r['id']:>3} {r['category']:<16} "
            f"{tc['expected_urgency']:<12} {urg_actual:<12} "
            f"{tc['expected_action']:<14} {act_actual:<14} "
            f"{status:<6}"
        )

    print("-" * 110)
    print(f"\n■ サマリー:")
    print(f"  実行: {summary['total']}件  成功: {summary['successful']}件  エラー: {summary['errors']}件")
    print(f"  urgency一致率: {summary['urgency_match']}/{summary['successful']} ({summary['urgency_rate']:.0%})")
    print(f"  action一致率:  {summary['action_match']}/{summary['successful']} ({summary['action_rate']:.0%})")


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
            "urgency_flag": r["urgency_flag"],
            "action": r["action"],
            "manual_coverage": r["manual_coverage"],
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
    print("=" * 60)
    print("E2E チャットフローテスト")
    print(f"対象API: {BASE_URL}")
    print(f"テストケース数: {len(TEST_CASES)}")
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
            result = await run_chat_flow(client, tc)
            results.append(result)

            if result["error"]:
                print(f"       ERROR: {result['error'][:60]}")
            else:
                print(f"       urgency={result['urgency_flag']}, action={result['action']}")

    # 集計・表示・保存
    summary = evaluate_results(results)
    print_results(results, summary)
    save_results(results, summary)


if __name__ == "__main__":
    asyncio.run(main())
