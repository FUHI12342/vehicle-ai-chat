from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo
from app.chat_flow.step1_vehicle_id import handle_vehicle_id
from app.chat_flow.step2_photo_confirm import handle_photo_confirm
from app.chat_flow.step3_free_text import handle_free_text
from app.chat_flow.step_diagnosing import handle_diagnosing
from app.chat_flow.step_urgency import handle_urgency_check
from app.chat_flow.step_reservation import (
    handle_reservation,
    handle_booking_info,
    handle_booking_confirm,
)


STEP_HANDLERS = {
    ChatStep.VEHICLE_ID: handle_vehicle_id,
    ChatStep.PHOTO_CONFIRM: handle_photo_confirm,
    ChatStep.FREE_TEXT: handle_free_text,
    ChatStep.DIAGNOSING: handle_diagnosing,
    ChatStep.URGENCY_CHECK: handle_urgency_check,
    ChatStep.RESERVATION: handle_reservation,
    ChatStep.BOOKING_INFO: handle_booking_info,
    ChatStep.BOOKING_CONFIRM: handle_booking_confirm,
}


async def process_step(session: SessionState, request: ChatRequest) -> ChatResponse:
    handler = STEP_HANDLERS.get(session.current_step)
    if not handler:
        return ChatResponse(
            session_id=session.session_id,
            current_step=session.current_step.value,
            prompt=PromptInfo(
                type="text",
                message="セッションが終了しました。新しい問診を開始するには、ページを更新してください。",
            ),
        )
    return await handler(session, request)
