from app.models.chat import ChatRequest, ChatResponse, PromptInfo
from app.services.session_store import session_store
from app.chat_flow.state_machine import process_step


class ChatService:
    async def process(self, request: ChatRequest) -> ChatResponse:
        if request.session_id:
            session = session_store.get(request.session_id)
            if not session:
                return ChatResponse(
                    session_id=request.session_id,
                    current_step="expired",
                    prompt=PromptInfo(
                        type="text",
                        message="セッションの有効期限が切れました。新しい問診を開始します。",
                    ),
                )
        else:
            session = session_store.create()

        response = await process_step(session, request)
        session_store.update(session)
        return response


chat_service = ChatService()
