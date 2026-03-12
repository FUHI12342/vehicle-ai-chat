"""
ground_truth候補抽出ヘルパー

ChromaDBから各テストケースの症状でRAG検索し、
マニュアルの該当チャンクを表示する。
ground_truthの手動レビュー・再作成用。

使い方:
  cd backend
  python -m tests.ragas.extract_ground_truth
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.rag.vector_store import vector_store
from tests.ragas.test_cases import TEST_CASES, VEHICLE_ID


async def extract_for_case(tc: dict, n_results: int = 8) -> list[dict]:
    """1テストケースの症状でRAG検索し、上位チャンクを返す"""
    results = await vector_store.search(
        query=tc["symptom"],
        vehicle_id=VEHICLE_ID,
        n_results=n_results,
    )
    return results


async def main():
    case_ids = None
    if len(sys.argv) > 1:
        case_ids = [int(x) for x in sys.argv[1].split(",")]

    cases = TEST_CASES if case_ids is None else [
        tc for tc in TEST_CASES if tc["id"] in case_ids
    ]

    print("=" * 100)
    print("ground_truth候補抽出 (ChromaDB RAG検索)")
    print(f"対象: {len(cases)}ケース  vehicle_id: {VEHICLE_ID}")
    print("=" * 100)

    for tc in cases:
        print(f"\n{'─' * 100}")
        print(f"[{tc['id']:02d}] {tc['category']}: {tc['symptom']}")
        print(f"     期待urgency: {tc['expected_urgency']}  期待action: {tc['expected_action']}")
        print(f"{'─' * 100}")

        results = await extract_for_case(tc)

        if not results:
            print("  ⚠ 検索結果なし")
            print("  → ground_truth: マニュアルに該当記載なし。ディーラーでの点検を推奨。")
            continue

        for i, r in enumerate(results):
            score = r["score"]
            page = r["page"]
            section = r["section"]
            has_warning = r["has_warning"]
            content = r["content"][:300].replace("\n", " ")

            warning_mark = " ⚠警告" if has_warning else ""
            print(f"  [{i+1}] score={score:.3f}  P.{page}  [{section}]{warning_mark}")
            print(f"      {content}")
            if len(r["content"]) > 300:
                print(f"      ...({len(r['content'])}文字)")
            print()

        # 候補ground_truthを生成
        top = results[0]
        pages = sorted(set(r["page"] for r in results[:3]))
        page_refs = ", ".join(f"P.{p}" for p in pages)
        print(f"  → 参照ページ候補: {page_refs}")
        print(f"  → 現在のground_truth (先頭100文字): {tc['ground_truth'][:100]}...")

    print(f"\n{'=' * 100}")
    print("完了。上記のRAG検索結果を参考にground_truthを再作成してください。")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
