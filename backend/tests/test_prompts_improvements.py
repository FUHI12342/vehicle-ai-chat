"""Tests for prompt improvements: not_covered strictness and loop prevention."""
from app.llm.prompts import DIAGNOSTIC_PROMPT


class TestNotCoveredStrictness:
    def test_strict_not_covered_criteria_present(self):
        assert "not_covered の判定は厳格に行うこと" in DIAGNOSTIC_PROMPT

    def test_rag_specific_guidance(self):
        assert "RAGの検索結果に「元の症状」の具体的な診断手順・対処法が含まれていない場合は not_covered" in DIAGNOSTIC_PROMPT

    def test_spec_only_rag_is_not_covered(self):
        assert "RAG結果が一般的な仕様説明のみで、トラブルシューティング手順がない場合も not_covered" in DIAGNOSTIC_PROMPT

    def test_no_general_knowledge_for_not_covered(self):
        assert "not_covered の場合は一般知識で診断手順を作成してはならない" in DIAGNOSTIC_PROMPT

    def test_escalate_instruction_for_not_covered(self):
        assert 'action: "escalate"' in DIAGNOSTIC_PROMPT


class TestLoopPreventionPrompt:
    def test_loop_avoidance_section_present(self):
        assert "ループ回避ルール" in DIAGNOSTIC_PROMPT

    def test_no_repeat_instruction(self):
        assert "直前のアシスタント応答と同じ内容・同じ結論を繰り返さないこと" in DIAGNOSTIC_PROMPT

    def test_different_angle_instruction(self):
        assert "別の角度からの確認に切り替えるか、escalateすること" in DIAGNOSTIC_PROMPT

    def test_dealer_suggestion_on_no_progress(self):
        assert "ディーラーでの点検を提案すること" in DIAGNOSTIC_PROMPT


class TestAdditionalInstructionsPlaceholder:
    def test_additional_instructions_placeholder_exists(self):
        assert "{additional_instructions}" in DIAGNOSTIC_PROMPT
