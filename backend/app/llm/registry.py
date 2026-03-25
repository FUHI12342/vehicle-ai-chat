from app.llm.base import LLMProvider
from app.llm.factory import LLMProviderFactory


class ProviderRegistry:
    def __init__(self):
        self.providers: dict[str, LLMProvider] = {}
        self.active_name: str = "openai"

    def initialize(self):
        from app.config import settings
        self.providers = LLMProviderFactory.create_all()
        # Use configured provider preference
        preferred = settings.llm_provider
        if preferred in self.providers and self.providers[preferred].is_configured():
            self.active_name = preferred
        elif "openai" in self.providers and self.providers["openai"].is_configured():
            self.active_name = "openai"
        elif "bedrock" in self.providers and self.providers["bedrock"].is_configured():
            self.active_name = "bedrock"

    def get_active(self) -> LLMProvider | None:
        return self.providers.get(self.active_name)

    def set_active(self, name: str):
        if name not in self.providers:
            raise ValueError(f"Unknown provider: {name}")
        if not self.providers[name].is_configured():
            raise ValueError(f"Provider '{name}' is not configured")
        self.active_name = name

    def get_embedding_provider(self) -> LLMProvider | None:
        return self.providers.get("openai")


provider_registry = ProviderRegistry()
