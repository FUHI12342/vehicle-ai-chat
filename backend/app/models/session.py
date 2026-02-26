from enum import Enum
from pydantic import BaseModel


class ChatStep(str, Enum):
    VEHICLE_ID = "vehicle_id"
    PHOTO_CONFIRM = "photo_confirm"
    FREE_TEXT = "free_text"
    SPEC_CHECK = "spec_check"
    DIAGNOSING = "diagnosing"
    URGENCY_CHECK = "urgency_check"
    RESERVATION = "reservation"
    BOOKING_INFO = "booking_info"
    BOOKING_CONFIRM = "booking_confirm"
    DONE = "done"


class SessionState(BaseModel):
    session_id: str
    current_step: ChatStep = ChatStep.VEHICLE_ID
    vehicle_id: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_photo_url: str | None = None
    symptom_category: str | None = None
    symptom_text: str | None = None
    follow_up_count: int = 0
    rag_answer: str | None = None
    conversation_history: list[dict] = []
    created_at: float = 0.0
    updated_at: float = 0.0
    diagnostic_turn: int = 0
    max_diagnostic_turns: int = 8
    collected_symptoms: list[str] = []
    urgency_level: str | None = None
    can_drive: bool | None = None
    booking_type: str | None = None
    booking_data: dict = {}
    last_questions: list[str] = []
    candidates_shown: bool = False
    spec_check_shown: bool = False
    spec_rag_sources: list[dict] = []
    spec_hint: bool = False
    conversation_summary: str = ""
    rewritten_query: str = ""
    last_confidence: float = 0.0
    solutions_tried: int = 0
