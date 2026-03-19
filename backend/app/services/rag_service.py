import json
import logging

from openai import AsyncOpenAI

from app.config import settings
from app.rag.reranker import rerank
from app.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

_ALT_QUERY_PROMPT = """車両トラブル診断のための検索クエリを生成してください。

元の症状: {symptom}

この症状に関連する別の視点からの検索クエリを2つ生成してください。
- 同じ症状を別の表現で表したもの
- 関連する部品名や技術用語を含むもの

JSON配列で返してください（他のテキストは不要）: ["クエリ1", "クエリ2"]"""


async def _generate_alt_queries(symptom: str) -> list[str]:
    """LLMで追加の検索クエリを2つ生成する。"""
    if not settings.openai_api_key:
        return []

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": _ALT_QUERY_PROMPT.format(symptom=symptom)}],
            temperature=0.3,
            max_tokens=200,
        )
        content = response.choices[0].message.content or "[]"
        queries = json.loads(content)
        if isinstance(queries, list):
            return [q for q in queries[:2] if isinstance(q, str)]
    except Exception as e:
        logger.warning("Alt query generation failed: %s", e)

    return []


def _deduplicate_results(all_results: list[dict]) -> list[dict]:
    """content先頭100文字をキーに重複を除去する。"""
    seen: set[str] = set()
    unique: list[dict] = []
    for r in all_results:
        key = r["content"][:100]
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


class RAGService:
    async def query(
        self,
        symptom: str,
        vehicle_id: str | None = None,
        make: str = "",
        model: str = "",
        year: int = 0,
        n_results: int = 10,
    ) -> dict:
        # 1. メインクエリでハイブリッド検索
        main_results = await vector_store.hybrid_search(
            query=symptom,
            vehicle_id=vehicle_id,
            n_results=n_results,
        )

        # 2. Multi-Query: LLMで追加クエリ2つ生成して検索
        alt_queries = await _generate_alt_queries(symptom)
        all_results = list(main_results)

        for alt_q in alt_queries:
            alt_results = await vector_store.search(
                query=alt_q,
                vehicle_id=vehicle_id,
                n_results=5,
            )
            all_results.extend(alt_results)

        # 3. 重複除去 + スコア閾値フィルタ
        unique = _deduplicate_results(all_results)
        candidates = [r for r in unique if r["score"] > 0.3]

        if not candidates:
            return {
                "answer": "関連するマニュアル情報はありません。",
                "sources": [],
            }

        # 4. Rerankで上位5件に絞る
        reranked = await rerank(query=symptom, chunks=candidates, top_n=5)

        sources = [
            {
                "content": r["content"],
                "page": r["page"],
                "section": r["section"],
                "score": r["score"],
            }
            for r in reranked
        ]

        return {
            "answer": "関連するマニュアル情報はありません。",
            "sources": sources,
        }

    async def get_warnings(self, vehicle_id: str | None, symptom: str) -> list[dict]:
        return await vector_store.search(
            query=symptom,
            vehicle_id=vehicle_id,
            n_results=3,
            warning_only=True,
        )


rag_service = RAGService()
