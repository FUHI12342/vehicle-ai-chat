import logging

from app.config import settings

logger = logging.getLogger(__name__)


class LocalEmbedder:
    """intfloat/multilingual-e5-large-instruct によるローカルembedding"""

    def __init__(self):
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading local embedding model: {settings.local_embedding_model}")
            self._model = SentenceTransformer(settings.local_embedding_model)
            logger.info("Local embedding model loaded")
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        # e5-large-instruct requires "query: " or "passage: " prefix
        # For ingestion (passages), use "passage: " prefix
        # For search queries, use "query: " prefix
        # Default to "passage: " here; search uses embed_query
        prefixed = [f"passage: {t}" for t in texts]
        embeddings = model.encode(prefixed, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]

    async def embed_query(self, text: str) -> list[float]:
        model = self._load_model()
        prefixed = f"query: {text}"
        embedding = model.encode([prefixed], normalize_embeddings=True)
        return embedding[0].tolist()

    async def embed_single(self, text: str) -> list[float]:
        return await self.embed_query(text)


class OpenAIEmbedder:
    """OpenAI APIによるembedding"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from app.llm.registry import provider_registry

        provider = provider_registry.get_embedding_provider()
        if not provider or not provider.is_configured():
            raise RuntimeError("Embedding provider (OpenAI) is not configured")
        response = await provider.embed(texts)
        return response.embeddings

    async def embed_query(self, text: str) -> list[float]:
        result = await self.embed([text])
        return result[0]

    async def embed_single(self, text: str) -> list[float]:
        return await self.embed_query(text)


class Embedder:
    """設定に応じてローカル/OpenAIを切り替えるファサード"""

    def __init__(self):
        self._backend: LocalEmbedder | OpenAIEmbedder | None = None

    def _get_backend(self) -> LocalEmbedder | OpenAIEmbedder:
        if self._backend is None:
            if settings.embedding_provider == "local":
                logger.info("Using local embedding (multilingual-e5-large-instruct)")
                self._backend = LocalEmbedder()
            else:
                logger.info("Using OpenAI embedding")
                self._backend = OpenAIEmbedder()
        return self._backend

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._get_backend().embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._get_backend().embed_query(text)

    async def embed_single(self, text: str) -> list[float]:
        return await self._get_backend().embed_single(text)


embedder = Embedder()
