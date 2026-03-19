"""日本語キーワード抽出モジュール

車両診断クエリから重要なキーワードを抽出する。
ハイブリッド検索でのキーワードマッチングに使用。
"""

import re

# 車両診断に頻出する名詞パターン（カタカナ語、漢字複合語）
_KATAKANA_PATTERN = re.compile(r"[ァ-ヴー]{2,}")
_KANJI_COMPOUND_PATTERN = re.compile(r"[一-龥]{2,}")

# ストップワード: 検索に使っても意味がない一般語
_STOPWORDS = frozenset({
    "する", "ある", "いる", "なる", "できる", "思う", "感じ",
    "ください", "ほしい", "みたい", "よう", "ない", "くる",
    "ところ", "こと", "もの", "とき", "場合", "状態", "感じ",
    "最近", "急に", "少し", "かなり", "とても",
    "車両", "自動車",
})

# 車両診断ドメインの重要キーワード辞書
_DOMAIN_KEYWORDS = frozenset({
    "ブレーキ", "エンジン", "オイル", "バッテリー", "タイヤ",
    "ハンドル", "ワイパー", "エアコン", "ヒューズ", "ラジエーター",
    "クーラント", "冷却水", "警告灯", "ランプ", "メーター",
    "ABS", "TPMS", "VSA", "PGM-FI",
    "振動", "異音", "異臭", "煙", "白煙", "黒煙",
    "オーバーヒート", "水温", "油圧", "燃料", "ガソリン",
    "パワステ", "パワーステアリング", "セレクトレバー",
    "スターター", "イモビライザー", "アイドリング",
    "点灯", "点滅", "液面", "液量", "不足",
    "空気圧", "パンク", "ペダル",
})


def extract_keywords(query: str, max_keywords: int = 5) -> list[str]:
    """クエリから検索用キーワードを抽出する。

    優先順位:
    1. ドメインキーワード辞書にマッチする語
    2. カタカナ複合語（2文字以上）
    3. 漢字複合語（2文字以上）

    Returns:
        重要度順のキーワードリスト（最大max_keywords個）
    """
    keywords: list[str] = []
    seen: set[str] = set()

    # 1. ドメインキーワード辞書マッチ（最優先）
    for kw in _DOMAIN_KEYWORDS:
        if kw in query and kw not in seen:
            keywords.append(kw)
            seen.add(kw)

    # 2. カタカナ複合語
    for match in _KATAKANA_PATTERN.finditer(query):
        word = match.group()
        if word not in seen and word not in _STOPWORDS and len(word) >= 3:
            keywords.append(word)
            seen.add(word)

    # 3. 漢字複合語
    for match in _KANJI_COMPOUND_PATTERN.finditer(query):
        word = match.group()
        if word not in seen and word not in _STOPWORDS and len(word) >= 2:
            keywords.append(word)
            seen.add(word)

    return keywords[:max_keywords]
