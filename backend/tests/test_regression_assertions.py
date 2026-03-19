"""Tests for regression assertion functions — offline validation."""
from tests.ragas.run_regression import (
    assert_case_1,
    assert_case_8,
    assert_case_10,
    assert_case_12,
)


def _make_result(conversation_log: list[dict], **kwargs) -> dict:
    return {
        "id": kwargs.get("id", 0),
        "conversation_log": conversation_log,
        "turns": kwargs.get("turns", len([e for e in conversation_log if e["role"] == "user"])),
        "final_action": kwargs.get("final_action", "ask_question"),
        "final_step": kwargs.get("final_step", "diagnosing"),
    }


# ---------------------------------------------------------------------------
# Case #1: ブレーキ故障
# ---------------------------------------------------------------------------

class TestCase1Assertions:
    def test_good_flow_all_pass(self):
        result = _make_result(
            [
                {"role": "user", "content": "ブレーキが効かない"},
                {"role": "assistant", "content": "安全な場所に停車してください。"},
                {"role": "user", "content": "停車しました"},
                {"role": "assistant", "content": "ブレーキ液のリザーバータンクを確認してください。ペダルの感触はどうですか？"},
                {"role": "user", "content": "柔らかいです"},
                {"role": "assistant", "content": "走行せずHonda販売店に連絡してください。"},
            ],
            turns=3,
            final_action="escalate",
            final_step="reservation",
        )
        assertions = assert_case_1(result)
        failed = [a for a in assertions if not a.passed]
        assert len(failed) == 0, f"Failed: {[(a.name, a.detail) for a in failed]}"

    def test_instant_escalate_fails(self):
        result = _make_result(
            [
                {"role": "user", "content": "ブレーキが効かない"},
                {"role": "assistant", "content": "ロードサービスを手配します。"},
            ],
            turns=1,
            final_action="escalate",
        )
        assertions = assert_case_1(result)
        # not_instant_escalate should fail (turns=1)
        names = {a.name: a.passed for a in assertions}
        assert names["not_instant_escalate"] is False


# ---------------------------------------------------------------------------
# Case #8: ハンドル重い
# ---------------------------------------------------------------------------

class TestCase8Assertions:
    def test_good_flow_no_fabrication(self):
        result = _make_result(
            [
                {"role": "user", "content": "ハンドルが重い"},
                {"role": "assistant", "content": "マニュアルに記載のない症状のためディーラーでの点検を推奨します。"},
            ],
            turns=2,
            final_action="escalate",
        )
        assertions = assert_case_8(result)
        failed = [a for a in assertions if not a.passed]
        assert len(failed) == 0, f"Failed: {[(a.name, a.detail) for a in failed]}"

    def test_fabrication_detected(self):
        result = _make_result(
            [
                {"role": "user", "content": "ハンドルが重い"},
                {"role": "assistant", "content": "パワーステアリングオイルが不足している可能性があります。"},
            ],
            turns=2,
            final_action="provide_answer",
        )
        assertions = assert_case_8(result)
        names = {a.name: a.passed for a in assertions}
        assert names["no_fabrication"] is False

    def test_max_turns_fails(self):
        result = _make_result([], turns=12, final_action="max_turns_reached")
        assertions = assert_case_8(result)
        names = {a.name: a.passed for a in assertions}
        assert names["no_max_turns"] is False


# ---------------------------------------------------------------------------
# Case #10: オーバーヒート
# ---------------------------------------------------------------------------

class TestCase10Assertions:
    def test_good_flow(self):
        result = _make_result(
            [
                {"role": "user", "content": "水温計が赤い"},
                {"role": "assistant", "content": "安全な場所に停車してください。蒸気が出ていますか？"},
                {"role": "user", "content": "出ていません"},
                {"role": "assistant", "content": "エンジンを切り、ボンネットを開けて冷却水量を確認してください。"},
                {"role": "user", "content": "確認しました"},
                {"role": "assistant", "content": "Honda販売店への連絡を推奨します。"},
            ],
            turns=3,
            final_action="escalate",
            final_step="reservation",
        )
        assertions = assert_case_10(result)
        failed = [a for a in assertions if not a.passed]
        assert len(failed) == 0, f"Failed: {[(a.name, a.detail) for a in failed]}"

    def test_instant_escalate_fails(self):
        result = _make_result(
            [
                {"role": "user", "content": "水温計が赤い"},
                {"role": "assistant", "content": "ロードサービスを手配します。"},
            ],
            turns=1,
            final_action="escalate",
        )
        assertions = assert_case_10(result)
        names = {a.name: a.passed for a in assertions}
        assert names["not_instant_escalate"] is False


# ---------------------------------------------------------------------------
# Case #12: 火災兆候
# ---------------------------------------------------------------------------

class TestCase12Assertions:
    def test_good_flow(self):
        result = _make_result(
            [
                {"role": "user", "content": "エンジンルームから火が見える"},
                {"role": "assistant", "content": "直ちに車両から離れてください。119番に通報してください。"},
            ],
            turns=1,
            final_action="escalate",
            final_step="reservation",
        )
        assertions = assert_case_12(result)
        failed = [a for a in assertions if not a.passed]
        assert len(failed) == 0, f"Failed: {[(a.name, a.detail) for a in failed]}"

    def test_fabrication_detected(self):
        result = _make_result(
            [
                {"role": "user", "content": "火が見える"},
                {"role": "assistant", "content": "消火器で消火してください。バケツで水をかけてください。"},
            ],
            final_action="provide_answer",
        )
        assertions = assert_case_12(result)
        names = {a.name: a.passed for a in assertions}
        assert names["no_fabrication"] is False

    def test_no_evacuation_fails(self):
        result = _make_result(
            [
                {"role": "user", "content": "火が見える"},
                {"role": "assistant", "content": "ディーラーに連絡してください。"},
            ],
            final_action="escalate",
            final_step="reservation",
        )
        assertions = assert_case_12(result)
        names = {a.name: a.passed for a in assertions}
        assert names["evacuation_mentioned"] is False
