from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    usage: dict | None = None


@dataclass
class EmbeddingResponse:
    embeddings: list[list[float]]
    usage: dict | None = None


class LLMProvider(ABC):
    name: str = ""
    display_name: str = ""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
        response_format: dict | None = None,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        ...
