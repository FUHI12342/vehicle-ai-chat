"""Shared fixtures for backend unit tests."""
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest
from app.llm.base import LLMResponse


@dataclass
class FakeLLMProvider:
    """Configurable fake LLM provider for tests."""

    _responses: list[dict] | None = None
    _call_count: int = 0

    def is_configured(self) -> bool:
        return True

    async def chat(self, **kwargs) -> LLMResponse:
        if self._responses and self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return LLMResponse(content=json.dumps(resp))
        return LLMResponse(content=json.dumps(self._default_response()))

    def _default_response(self) -> dict:
        return {
            "action": "ask_question",
            "message": "テスト質問です。",
            "urgency_flag": "none",
            "reasoning": "test",
            "choices": ["はい", "いいえ"],
            "can_drive": True,
            "confidence_to_answer": 0.3,
            "rewritten_query": "テスト",
            "manual_coverage": "covered",
            "visit_urgency": None,
            "question_topic": "",
        }


@pytest.fixture
def session() -> SessionState:
    """Basic session at DIAGNOSING step."""
    return SessionState(
        session_id="test-session",
        current_step=ChatStep.DIAGNOSING,
        vehicle_id="test-vehicle",
        vehicle_make="Honda",
        vehicle_model="Accord",
        vehicle_year=2020,
        symptom_text="ブレーキが効かない",
    )


@pytest.fixture
def request_msg() -> ChatRequest:
    """Basic chat request with a message."""
    return ChatRequest(session_id="test-session", message="はい")


def make_llm_response(**overrides) -> dict:
    """Build a diagnostic LLM response dict with defaults."""
    base = {
        "action": "ask_question",
        "message": "テスト質問です。",
        "urgency_flag": "none",
        "reasoning": "test",
        "choices": ["はい", "いいえ"],
        "can_drive": True,
        "confidence_to_answer": 0.3,
        "rewritten_query": "テスト",
        "manual_coverage": "covered",
        "visit_urgency": None,
        "question_topic": "",
    }
    base.update(overrides)
    return base
