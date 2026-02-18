from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo
from app.services.vehicle_service import vehicle_service


async def handle_vehicle_id(session: SessionState, request: ChatRequest) -> ChatResponse:
    if request.action == "select_vehicle" and request.action_value:
        vehicle = vehicle_service.get_by_id(request.action_value)
        if vehicle:
            session.vehicle_id = vehicle.id
            session.vehicle_make = vehicle.make
            session.vehicle_model = vehicle.model
            session.vehicle_year = vehicle.year
            session.vehicle_photo_url = vehicle.photo_url
            session.current_step = ChatStep.PHOTO_CONFIRM

            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.PHOTO_CONFIRM.value,
                prompt=PromptInfo(
                    type="photo_confirm",
                    message=f"{vehicle.year}年式 {vehicle.make} {vehicle.model} {vehicle.trim} でお間違いないですか？",
                    choices=[
                        {"value": "yes", "label": "はい、この車です"},
                        {"value": "no", "label": "いいえ、違います"},
                    ],
                    vehicle_photo_url=vehicle.photo_url,
                ),
            )

    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.VEHICLE_ID.value,
        prompt=PromptInfo(
            type="vehicle_search",
            message="こんにちは！車両トラブル診断アシスタントです。\nまず、お車の情報を教えてください。メーカー名や車種名で検索できます。",
        ),
    )
