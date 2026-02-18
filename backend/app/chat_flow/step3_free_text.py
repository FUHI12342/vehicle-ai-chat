from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo


async def handle_free_text(session: SessionState, request: ChatRequest) -> ChatResponse:
    if request.message and request.message.strip():
        session.symptom_text = request.message.strip()
        session.current_step = ChatStep.DIAGNOSING
        # Transition to diagnosing loop
        from app.chat_flow.step_diagnosing import handle_diagnosing
        return await handle_diagnosing(session, request)

    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.FREE_TEXT.value,
        prompt=PromptInfo(
            type="text",
            message="症状やお困りごとを入力してください。",
        ),
    )
