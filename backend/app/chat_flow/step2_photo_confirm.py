from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo


async def handle_photo_confirm(session: SessionState, request: ChatRequest) -> ChatResponse:
    if request.action == "confirm" and request.action_value == "yes":
        session.current_step = ChatStep.FREE_TEXT
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.FREE_TEXT.value,
            prompt=PromptInfo(
                type="text",
                message=f"{session.vehicle_make} {session.vehicle_model} ですね。\nどのような症状やお困りごとがありますか？\nできるだけ詳しく教えてください。",
            ),
        )

    if request.action == "confirm" and request.action_value == "no":
        session.vehicle_id = None
        session.vehicle_make = None
        session.vehicle_model = None
        session.vehicle_year = None
        session.vehicle_photo_url = None
        session.current_step = ChatStep.VEHICLE_ID
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.VEHICLE_ID.value,
            prompt=PromptInfo(
                type="vehicle_search",
                message="もう一度お車を検索してください。",
            ),
        )

    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.PHOTO_CONFIRM.value,
        prompt=PromptInfo(
            type="photo_confirm",
            message="お車の確認をお願いします。こちらのお車でお間違いないですか？",
            choices=[
                {"value": "yes", "label": "はい、この車です"},
                {"value": "no", "label": "いいえ、違います"},
            ],
            vehicle_photo_url=session.vehicle_photo_url,
        ),
    )
