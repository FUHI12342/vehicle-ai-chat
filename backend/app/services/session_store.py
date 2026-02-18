import time
import uuid

from app.config import settings
from app.models.session import SessionState, ChatStep


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}

    def create(self) -> SessionState:
        session_id = str(uuid.uuid4())
        now = time.time()
        session = SessionState(
            session_id=session_id,
            current_step=ChatStep.VEHICLE_ID,
            created_at=now,
            updated_at=now,
        )
        self._sessions[session_id] = session
        self._cleanup_expired()
        return session

    def get(self, session_id: str) -> SessionState | None:
        session = self._sessions.get(session_id)
        if session and self._is_expired(session):
            del self._sessions[session_id]
            return None
        return session

    def update(self, session: SessionState):
        session.updated_at = time.time()
        self._sessions[session.session_id] = session

    def delete(self, session_id: str):
        self._sessions.pop(session_id, None)

    def _is_expired(self, session: SessionState) -> bool:
        return time.time() - session.updated_at > settings.session_ttl_seconds

    def _cleanup_expired(self):
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.updated_at > settings.session_ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]


session_store = SessionStore()
