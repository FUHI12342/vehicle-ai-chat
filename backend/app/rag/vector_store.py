import chromadb

from app.config import settings
from app.rag.chunker import Chunk
from app.rag.embedder import embedder


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

    def delete_vehicle(self, vehicle_id: str):
        collection = self._get_collection()
        collection.delete(where={"vehicle_id": vehicle_id})

    def get_stats(self) -> dict:
        collection = self._get_collection()
        return {"total_chunks": collection.count()}


vector_store = VehicleManualStore()
