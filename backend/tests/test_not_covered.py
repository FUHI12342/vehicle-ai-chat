"""Tests for Fix 2: not_covered detection and Fix B: covered high-confidence override."""
import json
from unittest.mock import patch, AsyncMock

import pytest

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo, RAGSource
from app.chat_flow.step_diagnosing import _validate_manual_coverage
from tests.conftest import FakeLLMProvider, make_llm_response

_MOCK_RESERVATION_RESP = ChatResponse(
    session_id="t",
    current_step=ChatStep.RESERVATION.value,
    prompt=PromptInfo(type="text", message="予約へ"),
)


class TestNotCoveredCounter:
    @pytest.mark.asyncio
    async def test_single_not_covered_increments_counter(self):
        """Single not_covered should increment counter but not escalate."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="ハンドルが重い",
            not_covered_count=0,
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(manual_coverage="not_covered")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})

            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.not_covered_count == 1
        assert session.current_step == ChatStep.DIAGNOSING

    @pytest.mark.asyncio
    async def test_not_covered_with_turn_ge_2_escalates(self):
        """not_covered_count>=1 + diagnostic_turn>=2 should force escalate to RESERVATION."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="ハンドルが重い",
            not_covered_count=0,
            diagnostic_turn=1,  # will become 2 after increment → triggers escalation
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(manual_coverage="not_covered")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag, \
             patch("app.chat_flow.step_reservation.handle_reservation", new_callable=AsyncMock, return_value=_MOCK_RESERVATION_RESP):
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.not_covered_count == 1
        assert session.current_step == ChatStep.RESERVATION

    @pytest.mark.asyncio
    async def test_not_covered_turn_1_no_escalate(self):
        """not_covered on turn 1 should NOT escalate (allow initial question)."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="ハンドルが重い",
            not_covered_count=0,
            diagnostic_turn=0,  # will become 1 after increment → too early
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(manual_coverage="not_covered")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.not_covered_count == 1
        assert session.current_step == ChatStep.DIAGNOSING

    @pytest.mark.asyncio
    async def test_covered_resets_counter(self):
        """A covered response after not_covered should reset the counter."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="エンジンがかからない",
            not_covered_count=1,
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(manual_coverage="covered")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            # Provide RAG sources so the no-RAG override doesn't trigger
            mock_rag.query = AsyncMock(return_value={
                "answer": "ブレーキ液を確認してください",
                "sources": [{"content": "test", "page": 1, "section": "s", "score": 0.8}],
            })

            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.not_covered_count == 0

    @pytest.mark.asyncio
    async def test_not_covered_escalation_message(self):
        """Escalation message should mention manual and dealer."""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="ハンドルが重い",
            not_covered_count=0,
            diagnostic_turn=1,  # will become 2 → triggers escalation with not_covered
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(manual_coverage="not_covered")
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag, \
             patch("app.chat_flow.step_reservation.handle_reservation", new_callable=AsyncMock, return_value=_MOCK_RESERVATION_RESP):
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={"answer": "", "sources": []})

            from app.chat_flow.step_diagnosing import handle_diagnosing
            await handle_diagnosing(session, request)

        # Check escalation message was added to conversation history
        last_assistant = [
            e for e in session.conversation_history if e["role"] == "assistant"
        ][-1]
        assert "マニュアルに該当する記載が見つかりませんでした" in last_assistant["content"]
        assert "ディーラー" in last_assistant["content"]


class TestIdentifyingPhaseTurnLimit:
    """Fix A2 (Phase5-3): identifyingフェーズ4ターン到達時の強制遷移"""

    @pytest.mark.asyncio
    async def test_not_covered_4_turns_escalates(self):
        """not_covered + 4 turns + identifying → escalate to RESERVATION"""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="エアコンから冷たい風が出ない",
            diagnostic_turn=3,  # will become 4
            guide_phase="identifying",
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(
            action="ask_question",
            manual_coverage="not_covered",
            confidence_to_answer=0.4,
        )
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag, \
             patch("app.chat_flow.step_reservation.handle_reservation", new_callable=AsyncMock, return_value=_MOCK_RESERVATION_RESP):
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={
                "answer": "エアコン操作方法",
                "sources": [{"content": "test", "page": 1, "section": "s", "score": 0.4}],
            })
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.current_step == ChatStep.RESERVATION

    @pytest.mark.asyncio
    async def test_covered_4_turns_promotes_to_guide(self):
        """covered + 4 turns + identifying → provide_answer → guide_offered"""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="タイヤ空気圧警告",
            diagnostic_turn=3,  # will become 4
            guide_phase="identifying",
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(
            action="ask_question",
            manual_coverage="covered",
            confidence_to_answer=0.4,
        )
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={
                "answer": "タイヤ空気圧",
                "sources": [{"content": "TPMS", "page": 10, "section": "s", "score": 0.8}],
            })
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        # covered → promote to provide_answer → guide_offered
        assert session.guide_phase == "guide_offered"

    @pytest.mark.asyncio
    async def test_high_confidence_no_forced_escalate(self):
        """High confidence → Fix B triggers first → guide_offered"""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="ABSランプが点灯",
            diagnostic_turn=3,
            guide_phase="identifying",
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(
            action="ask_question",
            manual_coverage="covered",
            confidence_to_answer=0.8,
        )
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={
                "answer": "ABS警告灯",
                "sources": [{"content": "ABS", "page": 53, "section": "s", "score": 0.9}],
            })
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        # Fix B triggers → provide_answer → guide_offered
        assert session.guide_phase == "guide_offered"

    @pytest.mark.asyncio
    async def test_turn_3_no_forced_transition(self):
        """turn < 4 → no forced transition even with low confidence"""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="エアコンから冷たい風が出ない",
            diagnostic_turn=2,  # will become 3, below threshold of 4
            guide_phase="identifying",
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(
            action="ask_question",
            manual_coverage="covered",
            confidence_to_answer=0.4,
        )
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            # RAG score >= 0.70 so _validate_manual_coverage() trusts LLM's "covered"
            mock_rag.query = AsyncMock(return_value={
                "answer": "エアコン操作方法",
                "sources": [{"content": "test", "page": 1, "section": "s", "score": 0.75}],
            })
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        # turn=3 < 4, so forced transition should not trigger
        assert session.current_step == ChatStep.DIAGNOSING


class TestCoveredHighConfidenceOverride:
    """Fix B: covered + confidence>=0.8 + turn>=2 → ask_question を provide_answer に上書き"""

    @pytest.mark.asyncio
    async def test_high_confidence_covered_overrides_ask_question(self):
        """covered + high confidence + turn>=2 → provide_answer に上書きされる"""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="ABSランプが点灯",
            diagnostic_turn=1,  # will become 2
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(
            action="ask_question",
            manual_coverage="covered",
            confidence_to_answer=0.85,
            message="ABS警告灯の診断結果です。",
        )
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={
                "answer": "ABS警告灯について",
                "sources": [{"content": "ABS", "page": 53, "section": "s", "score": 0.9}],
            })
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        # Should have been overridden to provide_answer (guide_offered)
        assert session.guide_phase == "guide_offered"

    @pytest.mark.asyncio
    async def test_low_confidence_no_override(self):
        """covered + low confidence → ask_question のまま"""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="ABSランプが点灯",
            diagnostic_turn=1,
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(
            action="ask_question",
            manual_coverage="covered",
            confidence_to_answer=0.5,
            message="テスト質問です。",
        )
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            # RAG score >= 0.70 so coverage stays "covered"
            mock_rag.query = AsyncMock(return_value={
                "answer": "ABS警告灯について",
                "sources": [{"content": "ABS", "page": 53, "section": "s", "score": 0.75}],
            })
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        # Should remain as ask_question (guide_phase stays identifying)
        assert session.guide_phase == "identifying"

    @pytest.mark.asyncio
    async def test_turn_1_no_override(self):
        """covered + high confidence but turn 1 → ask_question のまま"""
        session = SessionState(
            session_id="t",
            current_step=ChatStep.DIAGNOSING,
            symptom_text="ABSランプが点灯",
            diagnostic_turn=0,  # will become 1
        )
        request = ChatRequest(session_id="t", message="はい")

        resp = make_llm_response(
            action="ask_question",
            manual_coverage="covered",
            confidence_to_answer=0.9,
            message="テスト質問です。",
        )
        fake_provider = FakeLLMProvider(_responses=[resp])

        with patch("app.chat_flow.step_diagnosing.keyword_urgency_check", return_value=None), \
             patch("app.chat_flow.step_diagnosing.provider_registry") as mock_reg, \
             patch("app.chat_flow.step_diagnosing.rag_service") as mock_rag:
            mock_reg.get_active.return_value = fake_provider
            mock_rag.query = AsyncMock(return_value={
                "answer": "ABS警告灯について",
                "sources": [{"content": "ABS", "page": 53, "section": "s", "score": 0.9}],
            })
            from app.chat_flow.step_diagnosing import handle_diagnosing
            response = await handle_diagnosing(session, request)

        assert session.guide_phase == "identifying"


# ---------------------------------------------------------------------------
# RAG score-based coverage validation
# ---------------------------------------------------------------------------

class TestValidateManualCoverage:
    """_validate_manual_coverage(): RAGスコアベースのcoverage外部検証"""

    def test_no_rag_sources_overrides_covered(self):
        """RAGソースなし + LLM 'covered' → 'not_covered'"""
        result = _validate_manual_coverage("covered", [])
        assert result == "not_covered"

    def test_no_rag_sources_keeps_not_covered(self):
        """RAGソースなし + LLM 'not_covered' → そのまま"""
        result = _validate_manual_coverage("not_covered", [])
        assert result == "not_covered"

    def test_rag_score_below_055_overrides_covered(self):
        """RAGスコア0.4 + LLM 'covered' → 'not_covered'"""
        sources = [RAGSource(content="test", page=1, section="s", score=0.4)]
        result = _validate_manual_coverage("covered", sources)
        assert result == "not_covered"

    def test_rag_score_055_to_070_partially_covered(self):
        """RAGスコア0.6 + LLM 'covered' → 'partially_covered'"""
        sources = [RAGSource(content="test", page=1, section="s", score=0.6)]
        result = _validate_manual_coverage("covered", sources)
        assert result == "partially_covered"

    def test_rag_score_above_070_trusts_llm(self):
        """RAGスコア0.75 + LLM 'covered' → 'covered' (LLM信頼)"""
        sources = [RAGSource(content="test", page=1, section="s", score=0.75)]
        result = _validate_manual_coverage("covered", sources)
        assert result == "covered"

    def test_rag_score_high_with_not_covered_llm(self):
        """RAGスコア0.9 + LLM 'not_covered' → 'not_covered' (LLM判断を尊重)"""
        sources = [RAGSource(content="test", page=1, section="s", score=0.9)]
        result = _validate_manual_coverage("not_covered", sources)
        assert result == "not_covered"

    def test_max_score_used_from_multiple_sources(self):
        """複数RAGソースの場合、最高スコアで判定"""
        sources = [
            RAGSource(content="a", page=1, section="s", score=0.3),
            RAGSource(content="b", page=2, section="s", score=0.75),
        ]
        result = _validate_manual_coverage("covered", sources)
        assert result == "covered"

    def test_boundary_054_is_not_covered(self):
        """境界値: スコア0.54 + LLM 'covered' → not_covered (0.54 < 0.55)"""
        sources = [RAGSource(content="test", page=1, section="s", score=0.54)]
        result = _validate_manual_coverage("covered", sources)
        assert result == "not_covered"

    def test_boundary_055_is_partially_covered(self):
        """境界値: スコア0.55 + LLM 'covered' → partially_covered (0.55 < 0.70)"""
        sources = [RAGSource(content="test", page=1, section="s", score=0.55)]
        result = _validate_manual_coverage("covered", sources)
        assert result == "partially_covered"

    def test_boundary_069_is_partially_covered(self):
        """境界値: スコア0.69 + LLM 'covered' → partially_covered (0.69 < 0.70)"""
        sources = [RAGSource(content="test", page=1, section="s", score=0.69)]
        result = _validate_manual_coverage("covered", sources)
        assert result == "partially_covered"

    def test_boundary_070_is_covered(self):
        """境界値: スコア0.70 + LLM 'covered' → covered (>= 0.70)"""
        sources = [RAGSource(content="test", page=1, section="s", score=0.70)]
        result = _validate_manual_coverage("covered", sources)
        assert result == "covered"
