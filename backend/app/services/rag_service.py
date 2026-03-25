import json
import logging

from app.config import settings
from app.rag.keyword_extractor import extract_keywords
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
    """アクティブLLMプロバイダーで追加の検索クエリを2つ生成する。"""
    from app.llm.registry import provider_registry
    provider = provider_registry.get_active()
    if not provider:
        return []

    try:
        response = await provider.chat(
            messages=[{"role": "user", "content": _ALT_QUERY_PROMPT.format(symptom=symptom)}],
            temperature=0.3,
            max_tokens=200,
            json_mode=True,
        )
        queries = json.loads(response.content)
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


def _ensure_inferred_keyword_coverage(
    reranked: list[dict],
    candidates: list[dict],
    symptom: str,
) -> list[dict]:
    """推論キーワードの仕様チャンクがリランク結果に含まれるよう保証する。

    リランカーは直接的な症状チャンクを優先するため、間接的に関連する
    仕様情報（例: ヒューズ配置表）を落とすことがある。推論キーワードの
    specification型チャンクが結果にない場合、候補から1件復活させる。
    """
    inferred_kws = [
        kw for kw in extract_keywords(symptom, max_keywords=3)
        if kw not in symptom
    ]
    if not inferred_kws:
        return reranked

    reranked_keys = {r["content"][:100] for r in reranked}
    rescued = list(reranked)

    for kw in inferred_kws[:1]:
        # 仕様(specification)チャンクが既にリランク結果にあるか確認
        has_spec = any(
            r.get("content_type") == "specification" and kw in r["content"][:200]
            for r in reranked
        )
        if has_spec:
            continue

        # 候補からspecificationチャンクを探す
        best = None
        for c in candidates:
            if c["content"][:100] in reranked_keys:
                continue
            if c.get("content_type") == "specification" and kw in c["content"][:200]:
                if best is None or c["score"] > best["score"]:
                    best = c

        if best:
            rescued.append(best)
            logger.info(
                "Rescued specification chunk for '%s': page=%s score=%.2f",
                kw, best.get("page", "?"), best["score"],
            )

    return rescued


def _build_rerank_query(symptom: str) -> str:
    """リランカー用クエリを構築する。推論キーワードをヒントとして付加。

    keyword_extractorの暗黙マッピングで導出されたキーワード（クエリ自体に
    含まれない語）をリランカーに伝えることで、間接的に関連するチャンク
    （例: ヒューズ仕様表）の評価を向上させる。
    """
    keywords = extract_keywords(symptom, max_keywords=3)
    inferred = [kw for kw in keywords if kw not in symptom]
    if inferred:
        hint = ", ".join(inferred[:3])
        return f"{symptom} (関連部品: {hint})"
    return symptom


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

        # 2b. 推論キーワード検索: 暗黙マッピングで導出された部品名で追加検索
        # 例: "ワイパーが動かない" → "ワイパー ヒューズ" で検索してヒューズ仕様ページを取得
        inferred_kws = [
            kw for kw in extract_keywords(symptom, max_keywords=3)
            if kw not in symptom
        ]
        for kw in inferred_kws[:2]:
            kw_results = await vector_store.search(
                query=f"{symptom} {kw}",
                vehicle_id=vehicle_id,
                n_results=3,
            )
            all_results.extend(kw_results)

        # 3. 重複除去 + スコア閾値フィルタ（Phase 3-3: 0.3→0.45に引き上げ）
        unique = _deduplicate_results(all_results)
        candidates = [r for r in unique if r["score"] > 0.45]

        if not candidates:
            return {
                "answer": "関連するマニュアル情報はありません。",
                "sources": [],
            }

        # 4. Rerankで上位N件に絞る（推論キーワードをヒントとして付加）
        rerank_query = _build_rerank_query(symptom)
        reranked = await rerank(query=rerank_query, chunks=candidates, top_n=7)

        # 4b. 推論キーワードの専用チャンク保証（rerankerで落ちた仕様チャンクを復活）
        reranked = _ensure_inferred_keyword_coverage(
            reranked, candidates, symptom,
        )

        # 5. Phase 3-1: Corrective RAG — rerank_scoreに基づく3段階ゲート
        reranked = await self._corrective_rag_gate(
            reranked, symptom, vehicle_id, n_results,
        )

        sources = [
            {
                "content": r["content"],
                "page": r["page"],
                "section": r["section"],
                "score": r["score"],
                "content_type": r.get("content_type", ""),
            }
            for r in reranked
        ]

        return {
            "answer": "関連するマニュアル情報はありません。",
            "sources": sources,
        }

    async def _corrective_rag_gate(
        self,
        reranked: list[dict],
        symptom: str,
        vehicle_id: str | None,
        n_results: int,
    ) -> list[dict]:
        """Corrective RAG: rerank_scoreに基づく3段階ゲート。

        - score >= 7: Correct → そのまま使用
        - score 4-6: Ambiguous → クエリ分解して再検索
        - score < 4: Incorrect → リライトして再検索（1回のみ）
        """
        if not reranked:
            return reranked

        max_score = max(r.get("rerank_score", 5) for r in reranked)

        if max_score >= 7:
            # Correct: そのまま使用
            return reranked

        if max_score >= 4:
            # Ambiguous: クエリ分解して再検索を試行
            logger.info(
                "CRAG Ambiguous gate (max_rerank_score=%.1f): attempting query decomposition",
                max_score,
            )
            alt_queries = await _generate_alt_queries(symptom)
            if alt_queries:
                additional_results = []
                for alt_q in alt_queries:
                    alt_results = await vector_store.hybrid_search(
                        query=alt_q,
                        vehicle_id=vehicle_id,
                        n_results=5,
                    )
                    additional_results.extend(alt_results)

                if additional_results:
                    combined = list(reranked) + _deduplicate_results(additional_results)
                    combined = _deduplicate_results(combined)
                    re_reranked = await rerank(query=symptom, chunks=combined, top_n=7)
                    return re_reranked

            return reranked

        # Incorrect (max_score < 4): リライトして再検索（1回のみ）
        logger.info(
            "CRAG Incorrect gate (max_rerank_score=%.1f): attempting query rewrite",
            max_score,
        )
        alt_queries = await _generate_alt_queries(symptom)
        if not alt_queries:
            return reranked

        # リライトクエリで再検索
        rewrite_results = []
        for alt_q in alt_queries:
            results = await vector_store.hybrid_search(
                query=alt_q,
                vehicle_id=vehicle_id,
                n_results=n_results,
            )
            rewrite_results.extend(results)

        if not rewrite_results:
            return reranked

        unique = _deduplicate_results(rewrite_results)
        candidates = [r for r in unique if r["score"] > 0.45]
        if not candidates:
            return reranked

        re_reranked = await rerank(query=symptom, chunks=candidates, top_n=5)
        # リライト結果がオリジナルより良い場合のみ採用
        new_max = max(r.get("rerank_score", 0) for r in re_reranked) if re_reranked else 0
        if new_max > max_score:
            logger.info("CRAG rewrite improved: %.1f → %.1f", max_score, new_max)
            return re_reranked

        return reranked

    async def get_warnings(self, vehicle_id: str | None, symptom: str) -> list[dict]:
        return await vector_store.search(
            query=symptom,
            vehicle_id=vehicle_id,
            n_results=3,
            warning_only=True,
        )


rag_service = RAGService()
