from app.llm.base import LLMProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.bedrock_provider import BedrockProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.watson_provider import WatsonProvider


class LLMProviderFactory:
    _registry: dict[str, type[LLMProvider]] = {
        "openai": OpenAIProvider,
        "bedrock": BedrockProvider,
        "gemini": GeminiProvider,
        "watson": WatsonProvider,
    }

    @classmethod
    def create(cls, name: str) -> LLMProvider:
        provider_class = cls._registry.get(name)
        if not provider_class:
            raise ValueError(f"Unknown provider: {name}")
        return provider_class()

    @classmethod
    def create_all(cls) -> dict[str, LLMProvider]:
        return {name: cls.create(name) for name in cls._registry}
