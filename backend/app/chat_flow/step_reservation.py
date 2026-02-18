import json
import logging

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo, UrgencyInfo

logger = logging.getLogger(__name__)

DISPATCH_FIELDS = [
    {"name": "name", "label": "お名前", "type": "text", "required": True},
    {"name": "phone", "label": "電話番号", "type": "tel", "required": True},
    {"name": "address", "label": "現在地の住所", "type": "text", "required": True},
]

VISIT_FIELDS = [
    {"name": "name", "label": "お名前", "type": "text", "required": True},
    {"name": "phone", "label": "電話番号", "type": "tel", "required": True},
    {"name": "preferred_date", "label": "希望日時", "type": "text", "required": True},
]


async def handle_reservation(session: SessionState, request: ChatRequest) -> ChatResponse:
    """RESERVATION step: ask user if they want to book."""
    # Determine booking type based on urgency
    if session.can_drive is False:
        session.booking_type = "dispatch"
    else:
        session.booking_type = "visit"

    # Handle user choice
    if request.action == "reservation_choice":
        action_val = request.action_value or ""
        if action_val == "dispatch":
            session.booking_type = "dispatch"
            session.current_step = ChatStep.BOOKING_INFO
            return await handle_booking_info(session, request)
        elif action_val in ("yes", "visit"):
            session.booking_type = session.booking_type or "visit"
            session.current_step = ChatStep.BOOKING_INFO
            return await handle_booking_info(session, request)
        else:
            # "no" / "skip" / anything else → 予約しない
            session.current_step = ChatStep.DONE
            message = "承知しました。症状が続く場合は、お近くのディーラーまたは整備工場にご相談ください。\n安全運転をお願いいたします。"
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DONE.value,
                prompt=PromptInfo(type="text", message=message),
            )

    # Initial display: show urgency and ask about booking
    urgency_info = UrgencyInfo(
        level=session.urgency_level or "high",
        requires_visit=True,
        reasons=[],
    )

    if session.booking_type == "dispatch":
        message = (
            "⚠️ 緊急度: 緊急\n\n"
            "走行が危険な状態と判断されます。\n"
            "出張整備の手配をおすすめします。\n\n"
            "出張手配の予約を行いますか？"
        )
    else:
        message = (
            "⚠️ 緊急度: 高\n\n"
            "早めにディーラーまたは整備工場での点検をおすすめします。\n\n"
            "来店予約を行いますか？"
        )

    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.RESERVATION.value,
        prompt=PromptInfo(
            type="reservation_choice",
            message=message,
            choices=[
                {"value": "yes", "label": "はい、予約する"},
                {"value": "no", "label": "いいえ、今は予約しない"},
            ],
            booking_type=session.booking_type,
        ),
        urgency=urgency_info,
    )


async def handle_booking_info(session: SessionState, request: ChatRequest) -> ChatResponse:
    """BOOKING_INFO step: collect booking details."""
    # Handle form submission
    if request.action == "submit_booking" and request.action_value:
        try:
            booking_data = json.loads(request.action_value)
            session.booking_data = booking_data
            session.current_step = ChatStep.BOOKING_CONFIRM
            return await handle_booking_confirm(session, request)
        except json.JSONDecodeError:
            logger.warning("Invalid booking data JSON")

    # Show booking form
    if session.booking_type == "dispatch":
        message = "出張手配に必要な情報を入力してください。"
        fields = DISPATCH_FIELDS
    else:
        message = "来店予約に必要な情報を入力してください。"
        fields = VISIT_FIELDS

    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.BOOKING_INFO.value,
        prompt=PromptInfo(
            type="booking_form",
            message=message,
            booking_type=session.booking_type,
            booking_fields=fields,
        ),
    )


async def handle_booking_confirm(session: SessionState, request: ChatRequest) -> ChatResponse:
    """BOOKING_CONFIRM step: confirm and finalize booking."""
    # Handle confirmation
    if request.action == "booking_confirm":
        if request.action_value == "confirm":
            session.current_step = ChatStep.DONE
            if session.booking_type == "dispatch":
                message = (
                    "✅ 出張手配の予約を承りました。\n\n"
                    f"お名前: {session.booking_data.get('name', '')}\n"
                    f"電話番号: {session.booking_data.get('phone', '')}\n"
                    f"住所: {session.booking_data.get('address', '')}\n\n"
                    "担当者から折り返しご連絡いたします。\n"
                    "安全な場所でお待ちください。"
                )
            else:
                message = (
                    "✅ 来店予約を承りました。\n\n"
                    f"お名前: {session.booking_data.get('name', '')}\n"
                    f"電話番号: {session.booking_data.get('phone', '')}\n"
                    f"希望日時: {session.booking_data.get('preferred_date', '')}\n\n"
                    "ご来店をお待ちしております。\n"
                    "安全運転でお越しください。"
                )
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DONE.value,
                prompt=PromptInfo(type="text", message=message),
            )

        if request.action_value == "edit":
            # Go back to booking info
            session.current_step = ChatStep.BOOKING_INFO
            return await handle_booking_info(session, request)

    # Show confirmation screen
    summary = dict(session.booking_data)
    if session.booking_type == "dispatch":
        message = (
            "以下の内容で出張手配を予約します。\n\n"
            f"お名前: {summary.get('name', '')}\n"
            f"電話番号: {summary.get('phone', '')}\n"
            f"住所: {summary.get('address', '')}\n\n"
            "こちらの内容でよろしいですか？"
        )
    else:
        message = (
            "以下の内容で来店予約を行います。\n\n"
            f"お名前: {summary.get('name', '')}\n"
            f"電話番号: {summary.get('phone', '')}\n"
            f"希望日時: {summary.get('preferred_date', '')}\n\n"
            "こちらの内容でよろしいですか？"
        )

    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.BOOKING_CONFIRM.value,
        prompt=PromptInfo(
            type="booking_confirm",
            message=message,
            choices=[
                {"value": "confirm", "label": "予約する"},
                {"value": "edit", "label": "修正する"},
            ],
            booking_type=session.booking_type,
            booking_summary=summary,
        ),
    )
