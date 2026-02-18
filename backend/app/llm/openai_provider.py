from openai import AsyncOpenAI

from app.config import settings
from app.llm.base import LLMProvider, LLMResponse, EmbeddingResponse


class OpenAIProvider(LLMProvider):
    name = "openai"
    display_name = "OpenAI GPT-4"

    def __init__(self):
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    def is_configured(self) -> bool:
        return bool(settings.openai_api_key and settings.openai_api_key != "sk-your-openai-api-key")

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
        response_format: dict | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        kwargs: dict = {
            "model": settings.openai_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            # Structured Outputs (JSON Schema)
            kwargs["response_format"] = response_format
        elif json_mode:
            # Legacy json_mode for backward compatibility
            kwargs["response_format"] = {"type": "json_object"}

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        )

    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        client = self._get_client()
        response = await client.embeddings.create(
            model=settings.openai_embedding_model,
            input=texts,
        )
        embeddings = [item.embedding for item in response.data]
        return EmbeddingResponse(
            embeddings=embeddings,
            usage={"total_tokens": response.usage.total_tokens if response.usage else 0},
        )

    async def health_check(self) -> bool:
        if not self.is_configured():
            return False
        try:
            client = self._get_client()
            await client.models.list()
            return True
        except Exception:
            return False
