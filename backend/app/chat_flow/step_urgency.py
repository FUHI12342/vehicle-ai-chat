from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo, UrgencyInfo
from app.services.urgency_assessor import urgency_assessor


async def handle_urgency_check(session: SessionState, request: ChatRequest) -> ChatResponse:
    symptom = session.symptom_text or " ".join(session.collected_symptoms)
    assessment = await urgency_assessor.assess(
        symptom=symptom,
        vehicle_id=session.vehicle_id,
        make=session.vehicle_make or "",
        model=session.vehicle_model or "",
        year=session.vehicle_year or 0,
    )

    level = assessment["level"]
    can_drive = assessment.get("can_drive", level != "critical")
    reasons = assessment["reasons"]
    recommendation = assessment.get("recommendation", "")

    session.urgency_level = level
    session.can_drive = can_drive

    urgency_info = UrgencyInfo(
        level=level,
        requires_visit=level in ("high", "critical"),
        reasons=reasons,
    )

    if level in ("high", "critical"):
        # Go to reservation flow
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # low/medium → additional advice and done
    message = f"緊急度: {'中' if level == 'medium' else '低'}\n\n"
    message += "\n".join(f"・{r}" for r in reasons)
    if recommendation:
        message += f"\n\n📋 {recommendation}"

    session.current_step = ChatStep.DONE

    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.DONE.value,
        prompt=PromptInfo(
            type="text",
            message=message,
        ),
        urgency=urgency_info,
    )
