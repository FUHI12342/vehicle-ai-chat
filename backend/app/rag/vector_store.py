import logging

import chromadb

from app.config import settings
from app.rag.chunker import Chunk
from app.rag.embedder import embedder
from app.rag.keyword_extractor import extract_keywords

logger = logging.getLogger(__name__)


def _reciprocal_rank_fusion(
    vector_results: list[dict],
    keyword_results: list[dict],
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion (RRF) で2つの検索結果を統合する。

    スコア = 1/(k + rank_vector) + 1/(k + rank_keyword)
    contentをキーにして重複を排除し、RRFスコアで降順ソート。
    """
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}

    for rank, doc in enumerate(vector_results):
        content_key = doc["content"][:100]  # 先頭100文字をキーに
        scores[content_key] = scores.get(content_key, 0) + 1.0 / (k + rank)
        if content_key not in docs:
            docs[content_key] = doc

    for rank, doc in enumerate(keyword_results):
        content_key = doc["content"][:100]
        scores[content_key] = scores.get(content_key, 0) + 1.0 / (k + rank)
        if content_key not in docs:
            docs[content_key] = doc

    sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)

    # Phase 3-2: content_type ブースト
    # troubleshooting/procedure: ×1.3（診断手順を優先）
    # specification: ×1.15（ヒューズ表等の仕様情報も軽くブースト）
    _BOOST_FACTORS: dict[str, float] = {
        "troubleshooting": 1.3,
        "procedure": 1.3,
        "specification": 1.15,
    }
    return [
        {
            **docs[key],
            "score": scores[key] * 60 * _BOOST_FACTORS.get(docs[key].get("content_type", ""), 1.0),
        }
        for key in sorted_keys
        if key in docs
    ]


class VehicleManualStore:
    COLLECTION_NAME = "vehicle_manuals"

    def __init__(self):
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None

    def initialize(self):
        self._client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def _get_collection(self) -> chromadb.Collection:
        if self._collection is None:
            self.initialize()
        return self._collection  # type: ignore

    async def add_chunks(self, chunks: list[Chunk], vehicle_id: str, make: str = "", model: str = "", year: int = 0):
        if not chunks:
            return

        collection = self._get_collection()
        batch_size = 50
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.text for c in batch]
            embeddings = await embedder.embed(texts)

            ids = [f"{vehicle_id}_{i + j}" for j, _ in enumerate(batch)]
            metadatas = [
                {
                    "vehicle_id": vehicle_id,
                    "make": make,
                    "model": model,
                    "year": year,
                    "page": c.page,
                    "section": c.section,
                    "content_type": c.content_type,
                    "has_warning": c.has_warning,
                }
                for c in batch
            ]

            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

    async def search(
        self,
        query: str,
        vehicle_id: str | None = None,
        n_results: int = 5,
        warning_only: bool = False,
    ) -> list[dict]:
        collection = self._get_collection()
        query_embedding = await embedder.embed_single(query)

        where_filter: dict | None = None
        conditions = []
        if vehicle_id:
            conditions.append({"vehicle_id": vehicle_id})
        if warning_only:
            conditions.append({"has_warning": True})

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = collection.query(**kwargs)

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        return [
            {
                "content": doc,
                "page": meta.get("page", 0),
                "section": meta.get("section", ""),
                "content_type": meta.get("content_type", ""),
                "has_warning": meta.get("has_warning", False),
                "score": 1 - dist,
            }
            for doc, meta, dist in zip(documents, metadatas, distances)
        ]

    async def keyword_search(
        self,
        keyword: str,
        vehicle_id: str | None = None,
        n_results: int = 5,
    ) -> list[dict]:
        """ChromaDB where_document $contains によるキーワード検索"""
        collection = self._get_collection()

        where_filter: dict | None = None
        if vehicle_id:
            where_filter = {"vehicle_id": vehicle_id}

        where_document = {"$contains": keyword}

        try:
            results = collection.get(
                where=where_filter,
                where_document=where_document,
                limit=n_results,
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.warning("Keyword search failed for '%s': %s", keyword, e)
            return []

        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        return [
            {
                "content": doc,
                "page": meta.get("page", 0),
                "section": meta.get("section", ""),
                "content_type": meta.get("content_type", ""),
                "has_warning": meta.get("has_warning", False),
                "score": 0.5,  # キーワード検索はスコアなし、固定値
            }
            for doc, meta in zip(documents, metadatas)
        ]

    async def hybrid_search(
        self,
        query: str,
        vehicle_id: str | None = None,
        n_results: int = 10,
    ) -> list[dict]:
        """ベクトル検索 + キーワード検索をRRFで統合するハイブリッド検索"""
        # 1. ベクトル検索
        vector_results = await self.search(query, vehicle_id, n_results=n_results)

        # 2. キーワード検索
        keywords = extract_keywords(query, max_keywords=3)
        keyword_results: list[dict] = []
        for kw in keywords:
            kw_results = await self.keyword_search(kw, vehicle_id, n_results=5)
            keyword_results.extend(kw_results)

        if not keyword_results:
            return vector_results

        # 3. RRF (Reciprocal Rank Fusion) で統合
        merged = _reciprocal_rank_fusion(vector_results, keyword_results, k=60)
        return merged[:n_results]

    def delete_vehicle(self, vehicle_id: str):
        collection = self._get_collection()
        collection.delete(where={"vehicle_id": vehicle_id})

    def get_stats(self) -> dict:
        collection = self._get_collection()
        return {"total_chunks": collection.count()}


vector_store = VehicleManualStore()
