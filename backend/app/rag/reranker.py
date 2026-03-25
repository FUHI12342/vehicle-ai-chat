"""LLMベースのRerankerモジュール

gpt-4o-miniを使用して検索結果の関連度をスコアリングし、
上位チャンクのみを返すことでContext Precisionを向上させる。
"""

import json
import logging

logger = logging.getLogger(__name__)

_RERANK_PROMPT = """以下の検索クエリに対する各文書の関連度を0-10で評価してください。
関連度の基準:
- 10: クエリの症状に対する直接的な診断手順・対処法が記載
- 7-9: 関連する警告灯や症状について具体的な記載がある
- 4-6: 間接的に関連する情報がある
- 1-3: ほぼ無関係だが同じ車両部品に言及
- 0: 完全に無関係

クエリ: {query}

文書リスト:
{documents}

JSON配列で返してください（他のテキストは不要）: [{{"index": 0, "score": 8}}, ...]"""


async def rerank(
    query: str,
    chunks: list[dict],
    top_n: int = 5,
) -> list[dict]:
    """gpt-4o-miniでチャンクの関連度をスコアリングし、上位を返す。

    Args:
        query: 検索クエリ
        chunks: 検索結果のチャンクリスト
        top_n: 返すチャンク数

    Returns:
        rerankされたチャンクリスト（上位top_n件）
    """
    if len(chunks) <= top_n:
        return chunks

    from app.llm.registry import provider_registry
    provider = provider_registry.get_active()
    if not provider:
        logger.warning("No active LLM provider, skipping rerank")
        return chunks[:top_n]

    # 文書リストをフォーマット
    doc_lines = []
    for i, chunk in enumerate(chunks):
        content_preview = chunk["content"][:300]
        section = chunk.get("section", "")
        page = chunk.get("page", 0)
        doc_lines.append(f"[{i}] 【{section or 'マニュアル'}(p.{page})】{content_preview}")

    formatted_docs = "\n\n".join(doc_lines)
    prompt = _RERANK_PROMPT.format(query=query, documents=formatted_docs)

    try:
        response = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=512,
            json_mode=True,
        )
        content = response.content or "[]"

        # JSON配列をパース
        scores = json.loads(content)
        if not isinstance(scores, list):
            logger.warning("Reranker returned non-list: %s", content[:100])
            return chunks[:top_n]

        # スコア順にソート
        score_map = {item["index"]: item["score"] for item in scores if "index" in item and "score" in item}
        scored_chunks = [
            {**chunks[idx], "rerank_score": score}
            for idx, score in score_map.items()
            if idx < len(chunks)
        ]
        scored_chunks.sort(key=lambda x: x["rerank_score"], reverse=True)

        # rerank_scoreが低い（2以下）ものは除外
        filtered = [c for c in scored_chunks if c["rerank_score"] > 2]
        result = filtered[:top_n] if filtered else scored_chunks[:top_n]

        logger.info(
            "Reranked %d chunks → %d (top scores: %s)",
            len(chunks),
            len(result),
            [c.get("rerank_score", 0) for c in result[:3]],
        )
        return result

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Reranker JSON parse error: %s", e)
        return chunks[:top_n]
    except Exception as e:
        logger.warning("Reranker failed, falling back: %s", e)
        return chunks[:top_n]
