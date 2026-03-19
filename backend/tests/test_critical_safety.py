"""Tests for Fix 1: Critical safety pending — safety steps before escalation.

Covers:
- step3_free_text: critical keyword sets flag, proceeds to DIAGNOSING (not RESERVATION)
- step_diagnosing: critical_safety_pending instruction injection
- step_diagnosing: auto-escalate after 4 turns
"""
import json
from unittest.mock import patch, AsyncMock

import pytest

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo
from app.chat_flow.step_diagnosing import _build_additional_instructions
from tests.conftest import FakeLLMProvider, make_llm_response


_MOCK_RESERVATION_RESP = ChatResponse(
    session_id="t",
    current_step=ChatStep.RESERVATION.value,
    prompt=PromptInfo(type="text", message="予約へ"),
)


# ---------------------------------------------------------------------------
# step3_free_text: critical → flag + DIAGNOSING
# ---------------------------------------------------------------------------

class TestFreeTextCriticalFlag:
    @pytest.mark.asyncio
    async def test_critical_keyword_sets_flag_not_reservation(self):
        """Critical keyword should set flag and proceed to DIAGNOSING, not jump to RESERVATION."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.FREE_TEXT,
            vehicle_id="v1",
        )
        request = ChatRequest(session_id="t", message="ブレーキが効かない")

        fake_provider = FakeLLMProvider(_responses=[make_llm_response()])

        with patch("app.chat_flow.step3_free_text.vector_store") as mock_vs, \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_vs.search = AsyncMock(return_value=[])
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})

            from app.chat_flow.step3_free_text import handle_free_text
            response = await handle_free_text(session, request)

        assert session.critical_safety_pending is True
        assert session.urgency_level == "critical"
        assert session.can_drive is False
        # Should have progressed to DIAGNOSING, not stayed at RESERVATION
        assert session.current_step == ChatStep.DIAGNOSING

    @pytest.mark.asyncio
    async def test_non_critical_keyword_no_flag(self):
        """Non-critical symptoms should not set critical_safety_pending."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.FREE_TEXT,
            vehicle_id="v1",
        )
        request = ChatRequest(session_id="t", message="エアコンが効かない")

        fake_provider = FakeLLMProvider(_responses=[make_llm_response()])

        with patch("app.chat_flow.step3_free_text.vector_store") as mock_vs, \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_vs.search = AsyncMock(return_value=[])
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})

            from app.chat_flow.step3_free_text import handle_free_text
            response = await handle_free_text(session, request)

        assert session.critical_safety_pending is False


# ---------------------------------------------------------------------------
# _build_additional_instructions: critical safety instruction injection
# ---------------------------------------------------------------------------

class TestCriticalSafetyInstructions:
    def test_critical_safety_pending_injects_instruction(self):
        session = SessionState(
            session_id="t",
            critical_safety_pending=True,
        )
        instructions = _build_additional_instructions(session, "テスト", False)
        assert "【緊急】" in instructions
        assert "安全な場所に停車してください" in instructions
        assert "マニュアルの記載のみ使用すること" in instructions

    def test_no_critical_safety_no_injection(self):
        session = SessionState(
            session_id="t",
            critical_safety_pending=False,
        )
        instructions = _build_additional_instructions(session, "テスト", False)
        assert "【緊急】" not in instructions


# ---------------------------------------------------------------------------
# step_diagnosing: auto-escalate after 4 turns with critical_safety_pending
# ---------------------------------------------------------------------------

class TestCriticalAutoEscalate:
    @pytest.mark.asyncio
    async def test_auto_escalate_at_turn_4(self):
        """With critical_safety_pending=True and diagnostic_turn >= 4, should escalate to RESERVATION."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            critical_safety_pending=True,
            urgency_level="critical",
            can_drive=False,
            diagnostic_turn=3,  # will be incremented to 4
            symptom_text="ブレーキ故障",
        )
        request = ChatRequest(session_id="t", message="確認しました")

        mock_handle = AsyncMock(return_value=_MOCK_RESERVATION_RESP)

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag, \
             patch("app.chat_flow.step_reservation.handle_reservation", mock_handle):
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})

            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.current_step == ChatStep.RESERVATION

    @pytest.mark.asyncio
    async def test_no_escalate_before_turn_4(self):
        """With critical_safety_pending=True but diagnostic_turn < 4, should continue diagnosing."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            critical_safety_pending=True,
            urgency_level="critical",
            can_drive=False,
            diagnostic_turn=1,  # will be incremented to 2
            symptom_text="ブレーキ故障",
        )
        request = ChatRequest(session_id="t", message="確認しました")

        fake_provider = FakeLLMProvider(_responses=[make_llm_response()])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            # Provide RAG sources to prevent no-RAG not_covered override
            mock_rag.query = AsyncMock(return_value={
                "answer": "ブレーキ液を確認",
                "sources": [{"content": "test", "page": 1, "section": "s", "score": 0.8}],
            })

            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        # Should still be diagnosing, not reservation
        assert session.current_step == ChatStep.DIAGNOSING
