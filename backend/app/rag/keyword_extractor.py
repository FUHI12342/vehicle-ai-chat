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

# 口語表現・オノマトペ → 診断キーワードのマッピング
# クエリ中にキー文字列が含まれる場合、値リストの用語をキーワードとして追加する
_IMPLICIT_KEYWORDS: dict[str, list[str]] = {
    # オノマトペ → 部品/症状
    "キュルキュル": ["スターター", "ベルト"],
    "ガタガタ": ["振動", "サスペンション"],
    "カタカタ": ["異音"],
    "ゴリゴリ": ["ベアリング", "ブレーキ"],
    "キーキー": ["ブレーキ", "ベルト"],
    "ブーン": ["異音"],
    "ガリガリ": ["ブレーキ", "異音"],
    "キュッ": ["ブレーキ", "ベルト"],
    # 症状の口語表現 → 部品/系統（具体的→汎用の順序で登録、先に一致したものが優先）
    "シミ": ["オイル", "漏れ"],
    "漏れ": ["オイル", "冷却水"],
    "かからない": ["スターター", "バッテリー", "イモビライザー"],
    "かかりにくい": ["スターター", "バッテリー"],
    "かかり": ["スターター", "バッテリー"],
    "効かない": ["ブレーキ", "エアコン"],
    "効きが悪い": ["ブレーキ", "エアコン"],
    "止まらない": ["ブレーキ"],
    "ワイパーが動かない": ["ヒューズ", "ワイパー"],
    "ワイパー動かない": ["ヒューズ", "ワイパー"],
    "動かない": ["バッテリー", "スターター"],
    "燃費": ["燃料"],
    "曇る": ["デフロスター", "エアコン"],
    "曇り": ["デフロスター", "エアコン"],
    "拭き": ["ワイパー"],
    "拭け": ["ワイパー"],
}

# 汎用すぎるキーワード: 100+チャンクにヒットするためノイズ源になる
# 他に具体的なキーワードがある場合は除外する
_GENERIC_KEYWORDS = frozenset({"エンジン"})


def extract_keywords(query: str, max_keywords: int = 5) -> list[str]:
    """クエリから検索用キーワードを抽出する。

    優先順位:
    1. 暗黙キーワードマッピング（オノマトペ・口語表現→診断用語）
    2. ドメインキーワード辞書にマッチする語
    3. カタカナ複合語（2文字以上）
    4. 漢字複合語（2文字以上）

    汎用キーワード（エンジン等）は他に具体的なキーワードがある場合、
    リスト末尾に移動してノイズを抑制する。

    Returns:
        重要度順のキーワードリスト（最大max_keywords個）
    """
    keywords: list[str] = []
    seen: set[str] = set()

    # 0. 暗黙キーワードマッピング（最優先）
    for trigger, implicit_kws in _IMPLICIT_KEYWORDS.items():
        if trigger in query:
            for kw in implicit_kws:
                if kw not in seen:
                    keywords.append(kw)
                    seen.add(kw)

    # 1. ドメインキーワード辞書マッチ
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

    # 4. 汎用キーワード抑制: 他に具体的なキーワードがある場合は末尾に移動
    specific = [kw for kw in keywords if kw not in _GENERIC_KEYWORDS]
    generic = [kw for kw in keywords if kw in _GENERIC_KEYWORDS]
    if specific and generic:
        keywords = specific + generic

    return keywords[:max_keywords]
