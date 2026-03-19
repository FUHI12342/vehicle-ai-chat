"""Tests for rule_based_checker — deterministic conversation checks."""
from tests.ragas.rule_based_checker import (
    CheckSummary,
    check_critical_safety_message,
    check_not_covered_fabrication,
    check_loop_detection,
    check_expected_action,
    check_max_turns_rate,
    check_step_comparison_coverage,
    check_manual_coverage_accuracy,
    check_sparse_retrieval_fabrication,
    run_all_checks,
    CRITICAL_CASE_IDS,
    NOT_COVERED_CASE_IDS,
)


def _make_case(case_id: int, conversation_log: list[dict], **kwargs) -> dict:
    base = {
        "id": case_id,
        "category": "test",
        "symptom": "test",
        "conversation_log": conversation_log,
        "turns": len([e for e in conversation_log if e["role"] == "user"]),
        "final_step": kwargs.get("final_step", "diagnosing"),
        "final_action": kwargs.get("final_action", "ask_question"),
        "urgency_flag": kwargs.get("urgency_flag"),
        "error": None,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Check 1: Critical safety message
# ---------------------------------------------------------------------------

class TestCriticalSafetyMessage:
    def test_critical_case_with_stop_message(self):
        case = _make_case(1, [
            {"role": "user", "content": "ブレーキ効かない"},
            {"role": "assistant", "content": "安全な場所に停車してください。"},
        ])
        summary = CheckSummary()
        check_critical_safety_message(case, summary)
        assert summary.passed == 1
        assert summary.failed == 0

    def test_critical_case_without_stop_message(self):
        case = _make_case(1, [
            {"role": "user", "content": "ブレーキ効かない"},
            {"role": "assistant", "content": "ブレーキの状態を確認します。"},
        ])
        summary = CheckSummary()
        check_critical_safety_message(case, summary)
        assert summary.failed == 1

    def test_non_critical_case_skipped(self):
        case = _make_case(2, [
            {"role": "assistant", "content": "何かメッセージ"},
        ])
        summary = CheckSummary()
        check_critical_safety_message(case, summary)
        assert summary.total_checks == 0


# ---------------------------------------------------------------------------
# Check 2: Not covered fabrication
# ---------------------------------------------------------------------------

class TestNotCoveredFabrication:
    def test_no_fabrication(self):
        # Case 8 is in NOT_COVERED_CASE_IDS
        case = _make_case(8, [
            {"role": "assistant", "content": "マニュアルに記載がないためディーラーでの点検をお勧めします。"},
        ])
        summary = CheckSummary()
        check_not_covered_fabrication(case, summary)
        assert summary.passed == 1

    def test_fabrication_detected(self):
        case = _make_case(8, [
            {"role": "assistant", "content": "パワーステアリングオイルが不足している可能性があります。"},
        ])
        summary = CheckSummary()
        check_not_covered_fabrication(case, summary)
        assert summary.failed == 1

    def test_covered_case_skipped(self):
        # Case 5 (エンジン始動不良) is NOT in NOT_COVERED_CASE_IDS
        case = _make_case(5, [
            {"role": "assistant", "content": "何か適当な内容"},
        ])
        summary = CheckSummary()
        check_not_covered_fabrication(case, summary)
        assert summary.total_checks == 0


# ---------------------------------------------------------------------------
# Check 3: Loop detection
# ---------------------------------------------------------------------------

class TestLoopDetection:
    def test_no_loop(self):
        case = _make_case(2, [
            {"role": "assistant", "content": "質問A"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "質問B"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "質問C"},
        ])
        summary = CheckSummary()
        check_loop_detection(case, summary)
        assert summary.passed == 1

    def test_loop_detected(self):
        case = _make_case(2, [
            {"role": "assistant", "content": "同じ質問です。確認してください。"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "同じ質問です。確認してください。"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "同じ質問です。確認してください。"},
        ])
        summary = CheckSummary()
        check_loop_detection(case, summary)
        assert summary.failed == 1

    def test_short_conversation_skipped(self):
        case = _make_case(2, [
            {"role": "assistant", "content": "質問A"},
            {"role": "user", "content": "はい"},
        ])
        summary = CheckSummary()
        check_loop_detection(case, summary)
        assert summary.total_checks == 0


# ---------------------------------------------------------------------------
# Check 4: Max turns rate
# ---------------------------------------------------------------------------

class TestMaxTurnsRate:
    def test_low_max_turns_rate(self):
        results = [
            _make_case(1, [], final_action="escalate"),
            _make_case(2, [], final_action="provide_answer"),
            _make_case(3, [], final_action="max_turns_reached"),
        ]
        summary = CheckSummary()
        check_max_turns_rate(results, summary)
        # 1/3 = 33% < 40% → pass
        assert summary.passed == 1

    def test_high_max_turns_rate(self):
        results = [
            _make_case(1, [], final_action="max_turns_reached"),
            _make_case(2, [], final_action="max_turns_reached"),
            _make_case(3, [], final_action="max_turns_reached"),
        ]
        summary = CheckSummary()
        check_max_turns_rate(results, summary)
        # 3/3 = 100% > 40% → fail
        assert summary.failed == 1


# ---------------------------------------------------------------------------
# Check 5: Expected action match
# ---------------------------------------------------------------------------

class TestExpectedActionMatch:
    def test_escalate_match(self):
        case = _make_case(1, [], final_action="escalate")
        summary = CheckSummary()
        check_expected_action(case, summary)
        assert summary.passed == 1

    def test_escalate_mismatch(self):
        case = _make_case(1, [], final_action="max_turns_reached")
        summary = CheckSummary()
        check_expected_action(case, summary)
        assert summary.failed == 1

    def test_ask_question_accepts_provide_answer(self):
        # Case 2 expects ask_question, provide_answer is also acceptable
        case = _make_case(2, [], final_action="provide_answer")
        summary = CheckSummary()
        check_expected_action(case, summary)
        assert summary.passed == 1


# ---------------------------------------------------------------------------
# Check 6: Step coverage
# ---------------------------------------------------------------------------

class TestStepCoverage:
    def test_good_coverage(self):
        case = _make_case(1, [], judge={
            "step_comparison": [
                {"manual_step": "A", "ai_step": "A", "match": "exact"},
                {"manual_step": "B", "ai_step": "B", "match": "partial"},
                {"manual_step": "C", "ai_step": "", "match": "missing"},
            ],
        })
        summary = CheckSummary()
        check_step_comparison_coverage(case, summary)
        # 2/3 = 67% >= 30% → pass
        assert summary.passed == 1

    def test_poor_coverage(self):
        case = _make_case(1, [], judge={
            "step_comparison": [
                {"manual_step": "A", "ai_step": "", "match": "missing"},
                {"manual_step": "B", "ai_step": "", "match": "missing"},
                {"manual_step": "C", "ai_step": "", "match": "missing"},
                {"manual_step": "D", "ai_step": "", "match": "missing"},
            ],
        })
        summary = CheckSummary()
        check_step_comparison_coverage(case, summary)
        # 0/4 = 0% < 30% → fail
        assert summary.failed == 1

    def test_no_step_comparison_skipped(self):
        case = _make_case(2, [], judge={"step_comparison": []})
        summary = CheckSummary()
        check_step_comparison_coverage(case, summary)
        assert summary.total_checks == 0


# ---------------------------------------------------------------------------
# Integration: run_all_checks
# ---------------------------------------------------------------------------

class TestRunAllChecks:
    def test_with_error_cases_skipped(self):
        results = [
            {"id": 1, "error": "connection failed"},
            _make_case(2, [
                {"role": "assistant", "content": "質問A"},
                {"role": "user", "content": "はい"},
                {"role": "assistant", "content": "質問B"},
                {"role": "user", "content": "はい"},
                {"role": "assistant", "content": "質問C"},
            ], final_action="provide_answer"),
        ]
        summary = run_all_checks(results)
        assert summary.total_checks > 0

    def test_case_id_sets_are_correct(self):
        # Verify known cases
        assert 1 in CRITICAL_CASE_IDS
        assert 10 in CRITICAL_CASE_IDS
        assert 8 in NOT_COVERED_CASE_IDS
        assert 12 in NOT_COVERED_CASE_IDS


# ---------------------------------------------------------------------------
# Check 7: Manual coverage accuracy
# ---------------------------------------------------------------------------

class TestManualCoverageAccuracy:
    def test_not_covered_ground_truth_actual_not_covered_pass(self):
        """ground_truth='記載なし' + actual='not_covered' → PASS"""
        case = _make_case(8, [], manual_coverage="not_covered")
        summary = CheckSummary()
        check_manual_coverage_accuracy(case, summary)
        assert summary.passed == 1

    def test_not_covered_ground_truth_actual_covered_fail(self):
        """ground_truth='記載なし' + actual='covered' → FAIL"""
        case = _make_case(8, [], manual_coverage="covered")
        summary = CheckSummary()
        check_manual_coverage_accuracy(case, summary)
        assert summary.failed == 1

    def test_covered_ground_truth_actual_covered_pass(self):
        """ground_truth has pages + actual='covered' → PASS"""
        case = _make_case(1, [], manual_coverage="covered")
        summary = CheckSummary()
        check_manual_coverage_accuracy(case, summary)
        assert summary.passed == 1

    def test_covered_ground_truth_actual_not_covered_fail(self):
        """ground_truth has pages + actual='not_covered' → FAIL"""
        case = _make_case(1, [], manual_coverage="not_covered")
        summary = CheckSummary()
        check_manual_coverage_accuracy(case, summary)
        assert summary.failed == 1

    def test_partially_covered_accepted_for_both(self):
        """partially_covered is accepted for both covered and not_covered ground_truth"""
        # not_covered ground_truth
        case8 = _make_case(8, [], manual_coverage="partially_covered")
        s8 = CheckSummary()
        check_manual_coverage_accuracy(case8, s8)
        assert s8.passed == 1

        # covered ground_truth
        case1 = _make_case(1, [], manual_coverage="partially_covered")
        s1 = CheckSummary()
        check_manual_coverage_accuracy(case1, s1)
        assert s1.passed == 1

    def test_no_manual_coverage_skipped(self):
        """Missing manual_coverage field → skip"""
        case = _make_case(1, [])
        summary = CheckSummary()
        check_manual_coverage_accuracy(case, summary)
        assert summary.total_checks == 0


# ---------------------------------------------------------------------------
# Check 8: Sparse retrieval fabrication
# ---------------------------------------------------------------------------

class TestSparseRetrievalFabrication:
    def test_not_covered_no_fabrication_pass(self):
        """not_coveredケースで捏造なし → PASS"""
        case = _make_case(8, [
            {"role": "assistant", "content": "マニュアルに記載がないためディーラーでの点検をお勧めします。"},
        ])
        summary = CheckSummary()
        check_sparse_retrieval_fabrication(case, summary)
        assert summary.passed == 1

    def test_not_covered_with_fabrication_fail(self):
        """not_coveredケースでパワステ液捏造あり → FAIL"""
        case = _make_case(8, [
            {"role": "assistant", "content": "パワステ液が不足しています。補充してください。"},
        ])
        summary = CheckSummary()
        check_sparse_retrieval_fabrication(case, summary)
        assert summary.failed == 1

    def test_covered_case_skipped(self):
        """coveredケースはスキップされる"""
        case = _make_case(1, [
            {"role": "assistant", "content": "パワステ液を確認してください。"},
        ])
        summary = CheckSummary()
        check_sparse_retrieval_fabrication(case, summary)
        assert summary.total_checks == 0

    def test_multiple_messages_checked(self):
        """各assistantメッセージが個別に検査される"""
        case = _make_case(8, [
            {"role": "assistant", "content": "まずは状況を確認します。"},
            {"role": "user", "content": "はい"},
            {"role": "assistant", "content": "原因はオルタネーターの故障です。交換してください。"},
        ])
        summary = CheckSummary()
        check_sparse_retrieval_fabrication(case, summary)
        assert summary.failed == 1
