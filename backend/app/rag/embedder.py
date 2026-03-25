import asyncio
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

BEDROCK_EMBED_MODEL = "amazon.titan-embed-text-v2:0"
BEDROCK_EMBED_REGION = "us-east-1"
BEDROCK_EMBED_DIMENSIONS = 1024


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


class BedrockEmbedder:
    """AWS Bedrock Titan Embeddings V2 によるembedding"""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=BEDROCK_EMBED_REGION,
            )
        return self._client

    def _invoke(self, text: str, input_type: str = "search_document") -> list[float]:
        """Bedrock Titan Embeddings V2 を同期呼び出しで1テキストembedding。"""
        client = self._get_client()
        body = json.dumps({
            "inputText": text[:8000],  # Titan V2 max 8192 tokens
            "dimensions": BEDROCK_EMBED_DIMENSIONS,
            "normalize": True,
        })
        response = client.invoke_model(
            modelId=BEDROCK_EMBED_MODEL,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        # バッチ処理: Titan V2はバッチAPIがないので1件ずつ
        embeddings = []
        for text in texts:
            embedding = await loop.run_in_executor(
                None, self._invoke, text, "search_document"
            )
            embeddings.append(embedding)
        return embeddings

    async def embed_query(self, text: str) -> list[float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._invoke, text, "search_query"
        )

    async def embed_single(self, text: str) -> list[float]:
        return await self.embed_query(text)


class Embedder:
    """設定に応じてローカル/OpenAI/Bedrockを切り替えるファサード"""

    def __init__(self):
        self._backend: LocalEmbedder | OpenAIEmbedder | BedrockEmbedder | None = None

    def _get_backend(self) -> LocalEmbedder | OpenAIEmbedder | BedrockEmbedder:
        if self._backend is None:
            if settings.embedding_provider == "local":
                logger.info("Using local embedding (multilingual-e5-large-instruct)")
                self._backend = LocalEmbedder()
            elif settings.embedding_provider == "bedrock":
                logger.info("Using Bedrock Titan Embeddings V2")
                self._backend = BedrockEmbedder()
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
