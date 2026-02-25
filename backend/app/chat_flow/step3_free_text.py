import logging

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo
from app.services.urgency_assessor import keyword_urgency_check
from app.rag.vector_store import vector_store

logger = logging.getLogger(__name__)


def _should_route_to_spec_check(
    rag_results: list[dict],
    keyword_result: dict | None,
) -> tuple[bool, list[dict]]:
    """Determine if the symptom should be routed to SPEC_CHECK.

    Safety gates (any one blocks spec path):
    1. keyword urgency is critical or high
    2. Any RAG result has has_warning=True
    3. High-score results contain "warning" or "troubleshooting" content_type

    Spec path conditions (all must be met):
    - At least one result with score >= 0.50
    - 2+ results of type "procedure"/"specification"/"general" among high-score results
    - Spec-type ratio >= 60% among high-score results
    """
    # Safety gate 1: keyword urgency
    if keyword_result and keyword_result["level"] in ("critical", "high"):
        return False, []

    if not rag_results:
        return False, []

    # Safety gate 2: has_warning
    if any(r.get("has_warning", False) for r in rag_results):
        return False, []

    # Filter to high-score results
    high_score = [r for r in rag_results if r.get("score", 0) >= 0.50]
    if not high_score:
        return False, []

    # Safety gate 3: warning/troubleshooting in high-score results
    danger_types = {"warning", "troubleshooting"}
    if any(r.get("content_type", "") in danger_types for r in high_score):
        return False, []

    # Spec path conditions
    spec_types = {"procedure", "specification", "general"}
    spec_results = [r for r in high_score if r.get("content_type", "") in spec_types]

    if len(spec_results) < 2:
        return False, []

    spec_ratio = len(spec_results) / len(high_score)
    if spec_ratio < 0.60:
        return False, []

    return True, spec_results


async def handle_free_text(session: SessionState, request: ChatRequest) -> ChatResponse:
    if not request.message or not request.message.strip():
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.FREE_TEXT.value,
            prompt=PromptInfo(
                type="text",
                message="症状やお困りごとを入力してください。",
            ),
        )

    symptom = request.message.strip()
    session.symptom_text = symptom

    # 1. Keyword urgency check
    keyword_result = keyword_urgency_check(symptom)
    if keyword_result and keyword_result["level"] == "critical":
        session.urgency_level = "critical"
        session.can_drive = False
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # 2. RAG search
    try:
        rag_results = await vector_store.search(
            query=symptom,
            vehicle_id=session.vehicle_id,
            n_results=5,
        )
    except Exception as e:
        logger.warning(f"RAG search failed in free_text: {e}")
        rag_results = []

    # 3. Spec path routing
    should_spec, spec_results = _should_route_to_spec_check(rag_results, keyword_result)
    if should_spec:
        session.spec_rag_sources = spec_results
        session.current_step = ChatStep.SPEC_CHECK
        from app.chat_flow.step_spec_check import handle_spec_check
        return await handle_spec_check(session, request)

    # 4. Default → DIAGNOSING
    session.current_step = ChatStep.DIAGNOSING
    from app.chat_flow.step_diagnosing import handle_diagnosing
    return await handle_diagnosing(session, request)
