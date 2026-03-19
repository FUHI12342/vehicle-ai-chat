"""Tests for shared fabrication pattern library."""
import pytest

from app.utils.fabrication_patterns import (
    ALL_PATTERNS,
    FabricationPattern,
    detect_fabrications,
)


# ---------------------------------------------------------------------------
# Category: parts — マニュアルに記載のない部品名
# ---------------------------------------------------------------------------

class TestPartsPatterns:
    """部品名パターンの正例・負例テスト。"""

    def test_power_steering_fluid_positive(self):
        assert any(
            p.pattern.search("パワーステアリングオイルが不足しています")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_power_steering_fluid_shorthand(self):
        assert any(
            p.pattern.search("パワステ液を補充してください")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_power_steering_negative(self):
        """パワステ単体（液/オイルなし）はマッチしない"""
        parts = [p for p in ALL_PATTERNS if "パワステ" in p.description]
        assert all(not p.pattern.search("パワステの警告灯が点灯") for p in parts)

    def test_spark_plug_positive(self):
        assert any(
            p.pattern.search("スパークプラグの交換時期です")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_spark_plug_negative(self):
        assert not any(
            p.pattern.search("エンジンプラグを確認")
            for p in ALL_PATTERNS if "スパークプラグ" in p.description
        )

    def test_alternator_positive(self):
        assert any(
            p.pattern.search("オルタネーターが故障")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_alternator_dynamo(self):
        assert any(
            p.pattern.search("ダイナモの不具合")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_timing_belt_positive(self):
        assert any(
            p.pattern.search("タイミングベルトの交換")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_timing_chain_positive(self):
        assert any(
            p.pattern.search("タイミングチェーンの伸び")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_atf_positive(self):
        assert any(
            p.pattern.search("ATFを交換してください")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_transmission_fluid_positive(self):
        assert any(
            p.pattern.search("トランスミッションフルードが劣化")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_air_filter_positive(self):
        assert any(
            p.pattern.search("エアフィルターを確認")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_air_cleaner_positive(self):
        assert any(
            p.pattern.search("エアクリーナーエレメントを交換")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_catalytic_converter_positive(self):
        assert any(
            p.pattern.search("触媒の劣化が原因")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_thermostat_positive(self):
        assert any(
            p.pattern.search("サーモスタットの故障")
            for p in ALL_PATTERNS if p.category == "parts"
        )

    def test_parts_negative_brake_fluid(self):
        """ブレーキ液はマニュアル記載ありなので parts でマッチしない"""
        parts = [p for p in ALL_PATTERNS if p.category == "parts"]
        assert all(not p.pattern.search("ブレーキ液を確認してください") for p in parts)

    def test_parts_negative_coolant(self):
        """冷却水はマニュアル記載ありなので parts でマッチしない"""
        parts = [p for p in ALL_PATTERNS if p.category == "parts"]
        assert all(not p.pattern.search("冷却水を補充してください") for p in parts)


# ---------------------------------------------------------------------------
# Category: diagnosis — 根拠なき断定
# ---------------------------------------------------------------------------

class TestDiagnosisPatterns:
    def test_cause_assertion_positive(self):
        assert any(
            p.pattern.search("原因はバッテリーの劣化です")
            for p in ALL_PATTERNS if p.category == "diagnosis"
        )

    def test_cause_assertion_probable(self):
        assert any(
            p.pattern.search("問題はセンサーの故障と思われます")
            for p in ALL_PATTERNS if p.category == "diagnosis"
        )

    def test_definite_failure(self):
        assert any(
            p.pattern.search("間違いなくモーターの故障です")
            for p in ALL_PATTERNS if p.category == "diagnosis"
        )

    def test_repair_cost_positive(self):
        assert any(
            p.pattern.search("修理費は約3万円になります")
            for p in ALL_PATTERNS if p.category == "diagnosis"
        )

    def test_repair_cost_yen(self):
        assert any(
            p.pattern.search("修理費は30000円程度です")
            for p in ALL_PATTERNS if p.category == "diagnosis"
        )

    def test_diagnosis_negative_possibility(self):
        """「可能性があります」は断定ではないのでdiagnosisでマッチしない"""
        diag = [p for p in ALL_PATTERNS if "原因断定" in p.description]
        assert all(not p.pattern.search("バッテリーの可能性があります") for p in diag)

    def test_diagnosis_negative_question(self):
        """質問形式はマッチしない"""
        diag = [p for p in ALL_PATTERNS if "確信的断定" in p.description]
        assert all(not p.pattern.search("故障でしょうか？") for p in diag)


# ---------------------------------------------------------------------------
# Category: repair — 具体的修理指示
# ---------------------------------------------------------------------------

class TestRepairPatterns:
    def test_replace_instruction(self):
        assert any(
            p.pattern.search("バッテリーを交換してください")
            for p in ALL_PATTERNS if p.category == "repair"
        )

    def test_replace_needed(self):
        assert any(
            p.pattern.search("部品の交換が必要です")
            for p in ALL_PATTERNS if p.category == "repair"
        )

    def test_diy_repair(self):
        assert any(
            p.pattern.search("DIYで修理できます")
            for p in ALL_PATTERNS if p.category == "repair"
        )

    def test_tool_removal(self):
        assert any(
            p.pattern.search("レンチで取り外してください")
            for p in ALL_PATTERNS if p.category == "repair"
        )

    def test_repair_negative_dealer(self):
        """ディーラー推奨は repair にマッチしない"""
        repair = [p for p in ALL_PATTERNS if p.category == "repair"]
        assert all(not p.pattern.search("Honda販売店で交換を依頼してください") for p in repair)


# ---------------------------------------------------------------------------
# Category: danger — 危険行為の案内
# ---------------------------------------------------------------------------

class TestDangerPatterns:
    def test_fire_extinguisher(self):
        assert any(
            p.pattern.search("消火器を使用してください")
            for p in ALL_PATTERNS if p.category == "danger"
        )

    def test_water_on_fire(self):
        assert any(
            p.pattern.search("水をかけて消火してください")
            for p in ALL_PATTERNS if p.category == "danger"
        )

    def test_jack_up(self):
        assert any(
            p.pattern.search("ジャッキアップして確認してください")
            for p in ALL_PATTERNS if p.category == "danger"
        )

    def test_radiator_cap_open(self):
        assert any(
            p.pattern.search("ラジエーターキャップを開けてください")
            for p in ALL_PATTERNS if p.category == "danger"
        )

    def test_driving_test(self):
        assert any(
            p.pattern.search("走行中にブレーキをテストしてみてください")
            for p in ALL_PATTERNS if p.category == "danger"
        )

    def test_danger_negative_evacuation(self):
        """避難指示は danger にマッチしない"""
        danger = [p for p in ALL_PATTERNS if p.category == "danger"]
        assert all(not p.pattern.search("車外に避難してください") for p in danger)


# ---------------------------------------------------------------------------
# detect_fabrications() integration tests
# ---------------------------------------------------------------------------

class TestDetectFabrications:
    def test_clean_text_returns_empty(self):
        text = "マニュアルに記載がないためHonda販売店での点検をお勧めします。"
        assert detect_fabrications(text) == []

    def test_single_match(self):
        text = "パワステ液を確認してください。"
        results = detect_fabrications(text)
        assert len(results) == 1
        assert results[0].category == "parts"

    def test_multiple_matches(self):
        text = "原因はオルタネーターの故障です。交換してください。"
        results = detect_fabrications(text)
        categories = {r.category for r in results}
        assert "parts" in categories
        assert "diagnosis" in categories
        assert "repair" in categories

    def test_danger_match(self):
        text = "消火器を用意してエンジンルームの火を消してください。"
        results = detect_fabrications(text)
        assert any(r.category == "danger" for r in results)

    def test_pattern_count(self):
        """ALL_PATTERNS should have exactly 18 patterns."""
        assert len(ALL_PATTERNS) == 18

    def test_category_counts(self):
        """Category distribution: 8 parts, 3 diagnosis, 3 repair, 4 danger."""
        by_cat = {}
        for p in ALL_PATTERNS:
            by_cat[p.category] = by_cat.get(p.category, 0) + 1
        assert by_cat == {"parts": 8, "diagnosis": 3, "repair": 3, "danger": 4}

    def test_immutability(self):
        """FabricationPattern is frozen dataclass."""
        p = ALL_PATTERNS[0]
        with pytest.raises(AttributeError):
            p.category = "modified"
