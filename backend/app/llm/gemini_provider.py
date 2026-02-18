from app.llm.base import LLMProvider, LLMResponse, EmbeddingResponse


class GeminiProvider(LLMProvider):
    name = "gemini"
    display_name = "Google Gemini"

    def is_configured(self) -> bool:
        return False

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2048, json_mode: bool = False) -> LLMResponse:
        raise NotImplementedError("Gemini provider not yet implemented")

    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        raise NotImplementedError("Gemini provider not yet implemented")

    async def health_check(self) -> bool:
        return False
