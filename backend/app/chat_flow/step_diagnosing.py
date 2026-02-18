import json
import logging

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo, RAGSource
from app.llm.registry import provider_registry
from app.llm.prompts import SYSTEM_PROMPT, DIAGNOSTIC_PROMPT
from app.llm.schemas import DIAGNOSTIC_SCHEMA
from app.services.rag_service import rag_service
from app.services.urgency_assessor import keyword_urgency_check

logger = logging.getLogger(__name__)


FALLBACK_QUESTIONS = [
    "症状が出るのは走行中ですか？それとも停車しているときですか？",
    "症状が出る頻度はどのくらいですか？（毎回・たまに・一度だけなど）",
    "エンジンをかけたとき、メーターパネルに見慣れない表示は出ていますか？",
    "最近、車の点検や修理をされましたか？",
    "症状が出るとき、何か特別な操作をしていますか？（例：エアコンをつけた、坂道を走ったなど）",
]


def _build_conversation_text(session: SessionState) -> str:
    """Build conversation history as text for the prompt."""
    lines = []
    for entry in session.conversation_history:
        role = "ユーザー" if entry["role"] == "user" else "アシスタント"
        lines.append(f"{role}: {entry['content']}")
    return "\n".join(lines) if lines else "(初回入力)"


def _normalize_question(text: str) -> str:
    """Normalize a question for duplicate comparison."""
    import re
    text = re.sub(r"[？?。、！!.,\s　]+", "", text)
    return text.lower()


def _is_duplicate_question(message: str, last_questions: list[str]) -> bool:
    """Check if the LLM question is semantically a duplicate of a recent one."""
    norm_new = _normalize_question(message)
    if not norm_new:
        return False
    for prev in last_questions:
        norm_prev = _normalize_question(prev)
        if not norm_prev:
            continue
        # Exact match after normalization
        if norm_new == norm_prev:
            return True
        # Substring containment (catches "いつから症状が..." vs "いつから...")
        shorter, longer = sorted([norm_new, norm_prev], key=len)
        if len(shorter) >= 4 and shorter in longer:
            return True
    return False


def _pick_fallback_question(session: SessionState) -> str | None:
    """Pick a fallback question that hasn't been asked yet.
    Returns None when all fallbacks are exhausted (caller should force provide_answer).
    """
    for q in FALLBACK_QUESTIONS:
        if not _is_duplicate_question(q, session.last_questions):
            return q
    return None


async def handle_diagnosing(session: SessionState, request: ChatRequest) -> ChatResponse:
    user_input = (request.message or "").strip()

    # Handle "resolved" action from provide_answer step
    if request.action == "resolved":
        if request.action_value == "yes":
            session.current_step = ChatStep.DONE
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DONE.value,
                prompt=PromptInfo(
                    type="text",
                    message="お役に立てて良かったです！他にご質問があれば、新しい問診を開始してください。\n安全運転をお願いいたします。",
                ),
            )
        else:
            session.current_step = ChatStep.URGENCY_CHECK
            from app.chat_flow.step_urgency import handle_urgency_check
            return await handle_urgency_check(session, request)

    if not user_input:
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="text",
                message="症状について教えてください。",
            ),
        )

    # ---------------------------------------------------------------
    # 1. Save user input FIRST so conversation_history is complete
    #    before building the LLM prompt.
    # ---------------------------------------------------------------
    session.collected_symptoms.append(user_input)
    session.conversation_history.append({"role": "user", "content": user_input})
    session.diagnostic_turn += 1

    # 2. Keyword-based urgency check (fast path for critical)
    all_symptoms = " ".join(session.collected_symptoms)
    keyword_result = keyword_urgency_check(all_symptoms)
    if keyword_result and keyword_result["level"] == "critical":
        session.urgency_level = "critical"
        session.can_drive = False
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # 3. RAG search
    rag_context = "関連するマニュアル情報はありません。"
    rag_sources: list[RAGSource] = []
    try:
        results = await rag_service.query(
            symptom=all_symptoms,
            vehicle_id=session.vehicle_id,
            make=session.vehicle_make or "",
            model=session.vehicle_model or "",
            year=session.vehicle_year or 0,
        )
        if results["sources"]:
            rag_context = results["answer"]
            rag_sources = [
                RAGSource(
                    content=s["content"],
                    page=s["page"],
                    section=s["section"],
                    score=s["score"],
                )
                for s in results["sources"]
            ]
    except Exception as e:
        logger.warning(f"RAG query failed: {e}")

    # ---------------------------------------------------------------
    # 4. Build prompt — conversation_history already includes the
    #    latest user message (step 1), so LLM sees the full Q/A.
    # ---------------------------------------------------------------
    conversation_text = _build_conversation_text(session)
    diagnostic_prompt = DIAGNOSTIC_PROMPT.format(
        make=session.vehicle_make or "不明",
        model=session.vehicle_model or "不明",
        year=session.vehicle_year or "不明",
        conversation_history=conversation_text,
        rag_context=rag_context,
    )

    # 5. Force provide_answer if max turns reached
    if session.diagnostic_turn >= session.max_diagnostic_turns:
        diagnostic_prompt += "\n\n【重要】問診回数の上限に達しました。これまでの情報をもとに action: \"provide_answer\" で回答を提供してください。"

    # 6. Call LLM with Structured Outputs
    provider = provider_registry.get_active()
    if not provider or not provider.is_configured():
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="text",
                message="LLMプロバイダーが設定されていません。設定を確認してください。",
            ),
        )

    try:
        response = await provider.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": diagnostic_prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_schema", "json_schema": DIAGNOSTIC_SCHEMA},
        )
        result = json.loads(response.content)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"LLM diagnostic call failed: {e}")
        fallback_msg = _pick_fallback_question(session)
        session.last_questions.append(fallback_msg)
        session.conversation_history.append({"role": "assistant", "content": fallback_msg})
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(type="text", message=fallback_msg),
        )

    action = result.get("action", "ask_question")
    message = result.get("message", "")
    urgency_flag = result.get("urgency_flag", "none")
    reasoning = result.get("reasoning", "")

    logger.info(f"Diagnostic action={action}, urgency={urgency_flag}, reasoning={reasoning}")

    # 7. Check urgency_flag from LLM
    if urgency_flag in ("high", "critical"):
        session.urgency_level = urgency_flag
        session.can_drive = urgency_flag != "critical"
        if urgency_flag == "critical":
            session.current_step = ChatStep.RESERVATION
            session.conversation_history.append({"role": "assistant", "content": message})
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)

    # 8. Dispatch based on action
    if action == "escalate":
        session.urgency_level = urgency_flag if urgency_flag in ("high", "critical") else "high"
        session.can_drive = session.urgency_level != "critical"
        session.conversation_history.append({"role": "assistant", "content": message})
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    if action == "provide_answer":
        session.rag_answer = message
        session.conversation_history.append({"role": "assistant", "content": message})
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="single_choice",
                message=message,
                choices=[
                    {"value": "yes", "label": "はい、解決しました"},
                    {"value": "no", "label": "いいえ、解決していません"},
                ],
            ),
            rag_sources=rag_sources,
        )

    if action == "clarify_term":
        choices = result.get("choices")
        session.conversation_history.append({"role": "assistant", "content": message})
        session.last_questions.append(message)
        prompt_choices = None
        if choices:
            prompt_choices = [{"value": c, "label": c} for c in choices]
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="single_choice" if prompt_choices else "text",
                message=message,
                choices=prompt_choices,
            ),
        )

    # ---------------------------------------------------------------
    # 9. ask_question — duplicate guard
    # ---------------------------------------------------------------
    if _is_duplicate_question(message, session.last_questions):
        logger.warning(f"Duplicate question detected, replacing: {message!r}")
        message = _pick_fallback_question(session)

    session.last_questions.append(message)
    session.conversation_history.append({"role": "assistant", "content": message})
    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.DIAGNOSING.value,
        prompt=PromptInfo(type="text", message=message),
    )
