"""
共通捏造検出パターンライブラリ

マニュアル外の情報を捏造するLLM応答を検出するためのパターン集。
step_diagnosing.py (runtime)、rule_based_checker.py (評価)、
run_regression.py (回帰テスト) の3箇所で共通利用する。

カテゴリ:
- parts: マニュアルに記載のない部品名（パワステ液、スパークプラグ等）
- diagnosis: 根拠なき断定（「原因は〜です」等）
- repair: 具体的修理指示（「交換してください」等）
- danger: 危険行為の案内（消火指示、ジャッキアップ等）
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FabricationPattern:
    """捏造検出パターン定義。"""
    category: str       # "parts" | "diagnosis" | "repair" | "danger"
    pattern: re.Pattern
    description: str


ALL_PATTERNS: list[FabricationPattern] = [
    # --- parts: マニュアルに記載のない部品名 (8) ---
    FabricationPattern(
        category="parts",
        pattern=re.compile(r"(パワーステアリング|パワステ)(オイル|フルード|液)", re.UNICODE),
        description="パワステ液: 2011アコードにEPS警告灯/パワステ液の記載なし",
    ),
    FabricationPattern(
        category="parts",
        pattern=re.compile(r"スパークプラグ", re.UNICODE),
        description="スパークプラグ: オーナーズマニュアルに交換手順の記載なし",
    ),
    FabricationPattern(
        category="parts",
        pattern=re.compile(r"オルタネーター|ダイナモ", re.UNICODE),
        description="オルタネーター: オーナーズマニュアルに記載なし",
    ),
    FabricationPattern(
        category="parts",
        pattern=re.compile(r"タイミング(ベルト|チェーン)", re.UNICODE),
        description="タイミングベルト/チェーン: オーナーズマニュアルに記載なし",
    ),
    FabricationPattern(
        category="parts",
        pattern=re.compile(
            r"(ATF|オートマ(チック)?フルード|トランスミッション(フルード|オイル|液))",
            re.UNICODE,
        ),
        description="ATF: オーナーズマニュアルに交換手順の記載なし",
    ),
    FabricationPattern(
        category="parts",
        pattern=re.compile(r"エアフィルター|エアクリーナー(エレメント)?", re.UNICODE),
        description="エアフィルター: オーナーズマニュアルに交換手順の記載なし",
    ),
    FabricationPattern(
        category="parts",
        pattern=re.compile(r"触媒|キャタライザー|キャタリスト", re.UNICODE),
        description="触媒: オーナーズマニュアルに記載なし",
    ),
    FabricationPattern(
        category="parts",
        pattern=re.compile(r"サーモスタット", re.UNICODE),
        description="サーモスタット: オーナーズマニュアルに記載なし",
    ),
    # --- diagnosis: 根拠なき断定 (3) ---
    FabricationPattern(
        category="diagnosis",
        pattern=re.compile(
            r"(原因は|故障は|問題は).{0,10}(です|でしょう|と思われ|可能性が高い)",
            re.UNICODE,
        ),
        description="原因断定: 「原因は〜です」等の根拠なき断定",
    ),
    FabricationPattern(
        category="diagnosis",
        pattern=re.compile(r"間違いなく.{0,15}(故障|不良|劣化|損傷)", re.UNICODE),
        description="確信的断定: 「間違いなく〜故障」",
    ),
    FabricationPattern(
        category="diagnosis",
        pattern=re.compile(r"修理費.{0,5}(万|円|￥|\d{4,})", re.UNICODE),
        description="修理費見積: 金額の提示",
    ),
    # --- repair: 具体的修理指示 (3) ---
    FabricationPattern(
        category="repair",
        pattern=re.compile(r"交換(してください|が必要|をお勧め)", re.UNICODE),
        description="交換指示: 「交換してください」等",
    ),
    FabricationPattern(
        category="repair",
        pattern=re.compile(r"DIY.{0,5}(修理|交換|作業)", re.UNICODE),
        description="DIY修理指示: DIYでの修理を案内",
    ),
    FabricationPattern(
        category="repair",
        pattern=re.compile(r"(工具|レンチ|スパナ|ドライバー).{0,10}(外し|取り外|緩め)", re.UNICODE),
        description="工具操作指示: 工具での取り外し手順",
    ),
    # --- danger: 危険行為の案内 (4) ---
    FabricationPattern(
        category="danger",
        pattern=re.compile(r"(消火器|消火|バケツ|水をかけ)", re.UNICODE),
        description="消火指示: 消火手順の案内（マニュアルに記載なし）",
    ),
    FabricationPattern(
        category="danger",
        pattern=re.compile(
            r"ジャッキ(アップ|で持ち上げ|を使っ)",
            re.UNICODE,
        ),
        description="ジャッキアップ指示: 車両のジャッキアップ",
    ),
    FabricationPattern(
        category="danger",
        pattern=re.compile(r"ラジエーター(キャップ|の蓋).{0,10}(開け|外し|取り)", re.UNICODE),
        description="ラジエーターキャップ操作: マニュアルで「絶対に外さないで」と警告あり",
    ),
    FabricationPattern(
        category="danger",
        pattern=re.compile(r"走行(中|しながら).{0,15}(テスト|試し|確認し)", re.UNICODE),
        description="走行中テスト: 走行しながらの確認作業",
    ),
]


def detect_fabrications(text: str) -> list[FabricationPattern]:
    """テキスト中の捏造パターンを検出し、マッチしたパターンのリストを返す。"""
    return [p for p in ALL_PATTERNS if p.pattern.search(text)]
