"""Tests for Fix 3: Conversation loop detection and forced escalation."""
import json
from unittest.mock import patch, AsyncMock

import pytest

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo
from app.chat_flow.step_diagnosing import _is_repeated_response
from tests.conftest import FakeLLMProvider, make_llm_response

_MOCK_RESERVATION_RESP = ChatResponse(
    session_id="t",
    current_step=ChatStep.RESERVATION.value,
    prompt=PromptInfo(type="text", message="予約へ"),
)


# ---------------------------------------------------------------------------
# _is_repeated_response unit tests
# ---------------------------------------------------------------------------

class TestIsRepeatedResponse:
    def test_exact_duplicate(self):
        history = [
            {"role": "assistant", "content": "ブレーキペダルを踏んだ感触を教えてください。"},
        ]
        assert _is_repeated_response("ブレーキペダルを踏んだ感触を教えてください。", history) is True

    def test_normalized_duplicate(self):
        """Punctuation and whitespace differences should still detect as duplicate."""
        history = [
            {"role": "assistant", "content": "ブレーキペダルを踏んだ感触を教えてください？"},
        ]
        assert _is_repeated_response("ブレーキペダルを踏んだ感触を教えてください。", history) is True

    def test_substring_match(self):
        """Shorter message (>= 10 chars) contained in longer one should match."""
        history = [
            {"role": "assistant", "content": "ボンネットを開けて冷却液のリザーバータンクの液面を確認してください"},
        ]
        assert _is_repeated_response(
            "冷却液のリザーバータンクの液面を確認してください", history
        ) is True

    def test_short_substring_no_match(self):
        """Very short messages (< 10 chars normalized) should not match on substring."""
        history = [
            {"role": "assistant", "content": "はいどうぞ"},
        ]
        # "はい" normalized is too short for substring check
        assert _is_repeated_response("はい", history) is False

    def test_different_content_no_match(self):
        history = [
            {"role": "assistant", "content": "エンジンオイルの量を確認してください。"},
        ]
        assert _is_repeated_response("タイヤの空気圧を確認してください。", history) is False

    def test_only_checks_recent_3_assistant(self):
        """Should only check last 3 assistant messages from last 6 entries."""
        history = [
            {"role": "assistant", "content": "古い質問です。"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "別の古い質問です。"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "最近の質問A。"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "最近の質問B。"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "最近の質問C。"},
        ]
        # "古い質問です" is outside the last 6 entries window
        assert _is_repeated_response("古い質問です。", history) is False
        # "最近の質問C" is within window
        assert _is_repeated_response("最近の質問C。", history) is True

    def test_empty_history(self):
        assert _is_repeated_response("テスト質問", []) is False

    def test_user_only_history(self):
        history = [
            {"role": "user", "content": "ブレーキが効かない"},
        ]
        assert _is_repeated_response("ブレーキが効かない", history) is False


# ---------------------------------------------------------------------------
# Integration: loop detection in handle_diagnosing
# ---------------------------------------------------------------------------

class TestLoopDetectionIntegration:
    @pytest.mark.asyncio
    async def test_first_repeat_increments_counter(self):
        """First repeated response should increment counter but not escalate."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="エンジン異音",
            repeated_response_count=0,
            conversation_history=[
                {"role": "assistant", "content": "テスト質問です。"},
            ],
        )
        request = ChatRequest(session_id="t", message="はい")

        # LLM returns same message as previous assistant response
        resp = make_llm_response(message="テスト質問です。")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})

            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.repeated_response_count == 1
        assert session.current_step == ChatStep.DIAGNOSING

    @pytest.mark.asyncio
    async def test_second_repeat_escalates(self):
        """Second consecutive repeated response should force escalate."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="エンジン異音",
            repeated_response_count=1,  # already 1 from previous
            conversation_history=[
                {"role": "assistant", "content": "テスト質問です。"},
            ],
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(message="テスト質問です。")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag, \
             patch("app.chat_flow.step_reservation.handle_reservation", new_callable=AsyncMock, return_value=_MOCK_RESERVATION_RESP):
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.repeated_response_count == 2
        assert session.current_step == ChatStep.RESERVATION

    @pytest.mark.asyncio
    async def test_different_response_resets_counter(self):
        """A different response should reset repeated_response_count to 0."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="エンジン異音",
            repeated_response_count=1,
            conversation_history=[
                {"role": "assistant", "content": "前回の質問です。"},
            ],
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(message="新しい別の質問です。")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})

            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.repeated_response_count == 0

    @pytest.mark.asyncio
    async def test_loop_escalation_message(self):
        """Escalation message should apologize and suggest dealer visit."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="エンジン異音",
            repeated_response_count=1,
            conversation_history=[
                {"role": "assistant", "content": "テスト質問です。"},
            ],
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(message="テスト質問です。")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag, \
             patch("app.chat_flow.step_reservation.handle_reservation", new_callable=AsyncMock, return_value=_MOCK_RESERVATION_RESP):
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})
            from app.chat_flow.step_diagnosing import handle_diagnosing
            await handle_diagnosing(session, request)

        last_assistant = [
            e for e in session.conversation_history if e["role"] == "assistant"
        ][-1]
        assert "繰り返してしまい" in last_assistant["content"]
        assert "ディーラー" in last_assistant["content"]
