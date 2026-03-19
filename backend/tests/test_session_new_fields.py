"""Tests for new SessionState fields added for 3-fix improvement."""
from app.models.session import SessionState, ChatStep


class TestCriticalSafetyPendingField:
    def test_default_is_false(self):
        s = SessionState(session_id="t")
        assert s.critical_safety_pending is False

    def test_set_to_true(self):
        s = SessionState(session_id="t")
        updated = s.model_copy(update={"critical_safety_pending": True})
        assert updated.critical_safety_pending is True
        assert s.critical_safety_pending is False  # original unchanged


class TestNotCoveredCountField:
    def test_default_is_zero(self):
        s = SessionState(session_id="t")
        assert s.not_covered_count == 0

    def test_increment(self):
        s = SessionState(session_id="t", not_covered_count=1)
        assert s.not_covered_count == 1


class TestRepeatedResponseCountField:
    def test_default_is_zero(self):
        s = SessionState(session_id="t")
        assert s.repeated_response_count == 0

    def test_increment(self):
        s = SessionState(session_id="t", repeated_response_count=2)
        assert s.repeated_response_count == 2


class TestFieldsSerialization:
    def test_model_dump_includes_new_fields(self):
        s = SessionState(
            session_id="t",
            critical_safety_pending=True,
            not_covered_count=3,
            repeated_response_count=1,
        )
        data = s.model_dump()
        assert data["critical_safety_pending"] is True
        assert data["not_covered_count"] == 3
        assert data["repeated_response_count"] == 1

    def test_model_validate_with_new_fields(self):
        data = {
            "session_id": "t",
            "critical_safety_pending": True,
            "not_covered_count": 2,
            "repeated_response_count": 1,
        }
        s = SessionState.model_validate(data)
        assert s.critical_safety_pending is True
        assert s.not_covered_count == 2
        assert s.repeated_response_count == 1
