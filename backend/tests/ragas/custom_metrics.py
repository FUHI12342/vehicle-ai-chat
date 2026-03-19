"""カスタム評価メトリクス

RAGAS標準メトリクスを補完するドメイン固有の品質指標。

- procedure_adherence: マニュアル手順の遵守率
- conversation_efficiency: 会話ターン数の効率性
"""

import re

from app.rag.keyword_extractor import extract_keywords


def procedure_adherence(
    conversation_log: list[str],
    manual_steps: list[str],
) -> float:
    """会話ログに含まれるマニュアル手順のカバー率を計算する。

    Args:
        conversation_log: アシスタントの発言リスト
        manual_steps: マニュアルに記載された手順リスト

    Returns:
        0.0〜1.0のカバー率
    """
    if not manual_steps:
        return 1.0

    all_text = " ".join(conversation_log).lower()
    # 正規化: 句読点・空白を除去
    all_text_normalized = re.sub(r"[。、！？!?.,\s　]+", "", all_text)

    covered = 0
    for step in manual_steps:
        step_keywords = extract_keywords(step, max_keywords=3)
        # キーワードの半分以上がマッチすればカバー済みとみなす
        if not step_keywords:
            covered += 1
            continue
        matched = sum(1 for kw in step_keywords if kw.lower() in all_text_normalized)
        if matched >= max(1, len(step_keywords) // 2):
            covered += 1

    return covered / len(manual_steps)


def conversation_efficiency(
    actual_turns: int,
    max_expected_turns: int,
) -> float:
    """会話ターン数の効率性スコアを計算する。

    Args:
        actual_turns: 実際のターン数
        max_expected_turns: 期待される最大ターン数

    Returns:
        0.0〜1.0のスコア（期待値以内なら1.0、超過分だけ減点）
    """
    if max_expected_turns <= 0:
        return 1.0
    if actual_turns <= max_expected_turns:
        return 1.0
    # 超過分を減点: 2倍で0.0
    overshoot = (actual_turns - max_expected_turns) / max_expected_turns
    return max(0.0, 1.0 - overshoot)


def not_covered_quality(
    response: str,
    forbidden_terms: list[str] | None = None,
    expected_final_action: str | None = None,
    actual_final_action: str | None = None,
) -> dict:
    """not_coveredケースの品質を複合評価する。

    Returns:
        {
            "score": 0.0〜1.0,
            "has_dealer_referral": bool,
            "has_forbidden_terms": bool,
            "action_correct": bool,
        }
    """
    dealer_keywords = ["ディーラー", "販売店", "点検", "ロードサービス", "Honda"]
    has_dealer = any(kw in response for kw in dealer_keywords)

    has_forbidden = False
    if forbidden_terms:
        has_forbidden = any(term in response for term in forbidden_terms)

    action_correct = True
    if expected_final_action and actual_final_action:
        action_correct = actual_final_action == expected_final_action

    # スコア計算
    score = 0.0
    if has_dealer:
        score += 0.5
    if not has_forbidden:
        score += 0.3
    if action_correct:
        score += 0.2

    return {
        "score": score,
        "has_dealer_referral": has_dealer,
        "has_forbidden_terms": has_forbidden,
        "action_correct": action_correct,
    }
