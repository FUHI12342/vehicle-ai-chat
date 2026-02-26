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
        logger.info(
            "spec_check blocked: keyword urgency=%s", keyword_result["level"]
        )
        return False, []

    if not rag_results:
        logger.info("spec_check blocked: no RAG results")
        return False, []

    # Safety gate 2: has_warning
    if any(r.get("has_warning", False) for r in rag_results):
        logger.info("spec_check blocked: has_warning=True in RAG results")
        return False, []

    # Filter to high-score results
    high_score = [r for r in rag_results if r.get("score", 0) >= 0.50]
    if not high_score:
        scores = [r.get("score", 0) for r in rag_results]
        logger.info("spec_check blocked: no high-score results (scores=%s)", scores)
        return False, []

    # Safety gate 3: Block only when danger results outnumber spec results
    danger_types = {"warning", "troubleshooting"}
    spec_types = {"procedure", "specification", "general"}
    ct_counts = {}
    for r in high_score:
        ct = r.get("content_type", "")
        ct_counts[ct] = ct_counts.get(ct, 0) + 1
    danger_count = sum(ct_counts.get(dt, 0) for dt in danger_types)
    spec_count_hs = sum(ct_counts.get(st, 0) for st in spec_types)
    if danger_count > spec_count_hs:
        logger.info(
            "spec_check blocked: danger_count=%d > spec_count=%d (breakdown=%s)",
            danger_count,
            spec_count_hs,
            ct_counts,
        )
        return False, []

    # Spec path conditions
    spec_results = [r for r in high_score if r.get("content_type", "") in spec_types]

    # Relaxed minimum: 1 result OK if top score >= 0.70, otherwise need 2+
    top_spec_score = max((r.get("score", 0) for r in spec_results), default=0)
    min_spec_count = 1 if top_spec_score >= 0.70 else 2
    if len(spec_results) < min_spec_count:
        logger.info(
            "spec_check blocked: spec_results=%d < %d (top_score=%.2f, breakdown=%s)",
            len(spec_results),
            min_spec_count,
            top_spec_score,
            ct_counts,
        )
        return False, []

    spec_ratio = len(spec_results) / len(high_score)
    if spec_ratio < 0.50:
        logger.info(
            "spec_check blocked: spec_ratio=%.2f < 0.50 (breakdown=%s)",
            spec_ratio,
            ct_counts,
        )
        return False, []

    logger.info(
        "spec_check routed: spec_ratio=%.2f, spec_results=%d, breakdown=%s",
        spec_ratio,
        len(spec_results),
        ct_counts,
    )
    return True, spec_results


def _should_hint_spec(
    rag_results: list[dict],
    keyword_result: dict | None,
) -> bool:
    """Return True if spec hint should be set for DIAGNOSING (softer threshold than routing)."""
    # Same safety gates as _should_route_to_spec_check
    if keyword_result and keyword_result["level"] in ("critical", "high"):
        return False
    if not rag_results:
        return False
    if any(r.get("has_warning", False) for r in rag_results):
        return False

    high_score = [r for r in rag_results if r.get("score", 0) >= 0.50]
    if not high_score:
        return False

    danger_types = {"warning", "troubleshooting"}
    spec_types = {"procedure", "specification", "general"}
    ct_counts: dict[str, int] = {}
    for r in high_score:
        ct = r.get("content_type", "")
        ct_counts[ct] = ct_counts.get(ct, 0) + 1
    danger_count = sum(ct_counts.get(dt, 0) for dt in danger_types)
    spec_count_hs = sum(ct_counts.get(st, 0) for st in spec_types)
    if danger_count > spec_count_hs:
        return False

    spec_results = [r for r in high_score if r.get("content_type", "") in spec_types]
    if not spec_results:
        return False

    spec_ratio = len(spec_results) / len(high_score)
    if spec_ratio >= 0.40:
        logger.info("spec_hint activated: spec_ratio=%.2f", spec_ratio)
        return True
    return False


async def _rag_search(symptom: str, vehicle_id: str | None) -> list[dict]:
    """RAG search wrapper for asyncio.gather."""
    try:
        return await vector_store.search(
            query=symptom,
            vehicle_id=vehicle_id,
            n_results=5,
        )
    except Exception as e:
        logger.warning(f"RAG search failed in free_text: {e}")
        return []


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

    # 1. Keyword urgency check (BEFORE parallel execution — no added latency)
    keyword_result = keyword_urgency_check(symptom)
    if keyword_result and keyword_result["level"] == "critical":
        session.urgency_level = "critical"
        session.can_drive = False
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # 2. RAG search
    rag_results = await _rag_search(symptom, session.vehicle_id)

    # 3. Spec path routing
    should_spec, spec_results = _should_route_to_spec_check(rag_results, keyword_result)
    if should_spec:
        session.spec_rag_sources = spec_results
        session.current_step = ChatStep.SPEC_CHECK
        from app.chat_flow.step_spec_check import handle_spec_check
        return await handle_spec_check(session, request)

    # 4. Soft spec hint for DIAGNOSING
    if _should_hint_spec(rag_results, keyword_result):
        session.spec_hint = True

    # 5. Default → DIAGNOSING
    session.current_step = ChatStep.DIAGNOSING
    from app.chat_flow.step_diagnosing import handle_diagnosing
    return await handle_diagnosing(session, request)
