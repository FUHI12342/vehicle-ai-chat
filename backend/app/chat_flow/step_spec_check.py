import json
import logging

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo, RAGSource
from app.llm.registry import provider_registry
from app.llm.prompts import SYSTEM_PROMPT, SPEC_CLASSIFICATION_PROMPT
from app.llm.schemas import SPEC_CLASSIFICATION_SCHEMA

logger = logging.getLogger(__name__)

_SPEC_CHECK_CHOICES = [
    {"value": "resolved", "label": "解決しました"},
    {"value": "not_resolved", "label": "解決していません"},
    {"value": "already_tried", "label": "それは試しました / 知っています"},
]


async def handle_spec_check(session: SessionState, request: ChatRequest) -> ChatResponse:
    """SPEC_CHECK step handler.

    Phase 1 (spec_check_shown=False): LLM classification + show explanation.
    Phase 2 (spec_check_shown=True): Handle user's choice.
    """

    # ── Phase 2: ユーザー選択後 ──
    if session.spec_check_shown:
        return await _handle_user_choice(session, request)

    # ── Phase 1: LLM分類 ──
    return await _classify_and_respond(session, request)


async def _handle_user_choice(session: SessionState, request: ChatRequest) -> ChatResponse:
    """Phase 2: Process user's response to spec explanation."""
    action_value = request.action_value or ""

    if action_value == "resolved":
        session.current_step = ChatStep.DONE
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DONE.value,
            prompt=PromptInfo(
                type="text",
                message="お役に立てて良かったです！他にご質問があれば、新しい問診を開始してください。\n安全運転をお願いいたします。",
            ),
        )

    # not_resolved / already_tried / free text → DIAGNOSING
    if request.message and request.message.strip() and action_value not in ("not_resolved", "already_tried"):
        session.collected_symptoms.append(request.message.strip())

    session.current_step = ChatStep.DIAGNOSING
    from app.chat_flow.step_diagnosing import handle_diagnosing
    return await handle_diagnosing(session, request)


async def _classify_and_respond(session: SessionState, request: ChatRequest) -> ChatResponse:
    """Phase 1: Use LLM to classify whether symptom is spec behavior."""
    provider = provider_registry.get_active()
    if not provider or not provider.is_configured():
        return await _fallthrough_to_diagnosing(session, request)

    # Build RAG context from spec_rag_sources
    rag_context = _build_rag_context(session.spec_rag_sources)

    prompt_text = SPEC_CLASSIFICATION_PROMPT.format(
        make=session.vehicle_make or "不明",
        model=session.vehicle_model or "不明",
        year=session.vehicle_year or "不明",
        symptom=session.symptom_text or "",
        rag_context=rag_context,
    )

    try:
        response = await provider.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_text},
            ],
            temperature=0.1,
            response_format={"type": "json_schema", "json_schema": SPEC_CLASSIFICATION_SCHEMA},
        )
        result = json.loads(response.content)
    except Exception as e:
        logger.error(f"Spec classification LLM call failed: {e}")
        return await _fallthrough_to_diagnosing(session, request)

    is_spec = result.get("is_spec_behavior", False)
    confidence = result.get("confidence", "low")
    explanation = result.get("explanation", "")
    manual_ref = result.get("manual_reference", "")
    reasoning = result.get("reasoning", "")

    logger.info(f"Spec classification: is_spec={is_spec}, confidence={confidence}, reasoning={reasoning}")

    # Only show spec explanation when high confidence AND is_spec_behavior
    if is_spec and confidence == "high":
        session.spec_check_shown = True

        message = f"マニュアルを確認したところ、これは仕様（正常な動作）の可能性があります。\n\n{explanation}"
        if manual_ref:
            message += f"\n\n📖 参考: {manual_ref}"
        message += "\n\nこの説明で疑問は解決しましたか？"

        rag_sources = [
            RAGSource(
                content=s.get("content", ""),
                page=s.get("page", 0),
                section=s.get("section", ""),
                score=s.get("score", 0.0),
            )
            for s in session.spec_rag_sources
        ]

        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.SPEC_CHECK.value,
            prompt=PromptInfo(
                type="single_choice",
                message=message,
                choices=_SPEC_CHECK_CHOICES,
            ),
            rag_sources=rag_sources,
        )

    # Low/medium confidence or not spec → fall through
    return await _fallthrough_to_diagnosing(session, request)


def _build_rag_context(sources: list[dict]) -> str:
    """Build RAG context string from spec_rag_sources."""
    if not sources:
        return "関連するマニュアル情報はありません。"

    parts = []
    for i, s in enumerate(sources, 1):
        content = s.get("content", "")
        section = s.get("section", "")
        page = s.get("page", 0)
        content_type = s.get("content_type", "")
        header = f"[{i}] {section} (p.{page}, {content_type})" if section else f"[{i}] p.{page} ({content_type})"
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts)


async def _fallthrough_to_diagnosing(session: SessionState, request: ChatRequest) -> ChatResponse:
    """Fall through to DIAGNOSING step — actually call handle_diagnosing."""
    session.current_step = ChatStep.DIAGNOSING
    from app.chat_flow.step_diagnosing import handle_diagnosing
    return await handle_diagnosing(session, request)
