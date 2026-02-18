from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str | None = None
    action: str | None = None
    action_value: str | None = None


class RAGSource(BaseModel):
    content: str
    page: int = 0
    section: str = ""
    score: float = 0.0


class UrgencyInfo(BaseModel):
    level: str = "low"
    requires_visit: bool = False
    reasons: list[str] = []


class PromptInfo(BaseModel):
    type: str = "text"
    message: str = ""
    choices: list[dict] | None = None
    vehicle_photo_url: str | None = None
    booking_type: str | None = None
    booking_fields: list[dict] | None = None
    booking_summary: dict | None = None


class ChatResponse(BaseModel):
    session_id: str
    current_step: str
    prompt: PromptInfo
    urgency: UrgencyInfo | None = None
    rag_sources: list[RAGSource] = []
