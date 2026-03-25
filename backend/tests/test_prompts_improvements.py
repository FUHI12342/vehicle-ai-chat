"""Tests for prompt improvements: not_covered strictness and loop prevention."""
from app.llm.prompts import DIAGNOSTIC_PROMPT


class TestNotCoveredStrictness:
    def test_not_covered_definition_present(self):
        assert "not_covered: 該当する記載が一切ない" in DIAGNOSTIC_PROMPT

    def test_no_general_knowledge_for_not_covered(self):
        assert "not_covered の場合は一般知識で診断手順を作成してはならない" in DIAGNOSTIC_PROMPT

    def test_escalate_instruction_for_not_covered(self):
        assert 'action: "escalate"' in DIAGNOSTIC_PROMPT

    def test_not_covered_immediate_escalate(self):
        assert "即座に action" in DIAGNOSTIC_PROMPT

    def test_forbidden_examples_present(self):
        assert "禁止例" in DIAGNOSTIC_PROMPT


class TestLoopPreventionPrompt:
    def test_loop_avoidance_section_present(self):
        assert "ループ回避ルール" in DIAGNOSTIC_PROMPT

    def test_no_repeat_instruction(self):
        assert "直前のアシスタント応答と同じ内容・同じ結論を繰り返さないこと" in DIAGNOSTIC_PROMPT

    def test_different_angle_instruction(self):
        assert "別の角度からの確認に切り替えるか、escalateすること" in DIAGNOSTIC_PROMPT


class TestPhaseDesign:
    def test_two_phase_system_described(self):
        assert "2フェーズ制" in DIAGNOSTIC_PROMPT

    def test_phase1_choices_restriction(self):
        assert "choices に対処手順を入れないこと" in DIAGNOSTIC_PROMPT

    def test_phase2_system_controlled(self):
        assert "システムが切り替え時に追加指示で通知" in DIAGNOSTIC_PROMPT

    def test_provide_answer_no_detailed_steps(self):
        assert "provide_answer で手順の詳細" in DIAGNOSTIC_PROMPT


class TestAdditionalInstructionsPlaceholder:
    def test_additional_instructions_placeholder_exists(self):
        assert "{additional_instructions}" in DIAGNOSTIC_PROMPT
