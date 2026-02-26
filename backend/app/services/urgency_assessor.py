import json
import re

from app.llm.registry import provider_registry
from app.llm.prompts import SYSTEM_PROMPT, URGENCY_ASSESSMENT_PROMPT
from app.llm.schemas import URGENCY_SCHEMA
from app.services.rag_service import rag_service


# --- ルールベース緊急度キーワード辞書 ---
# LLM呼び出し前に即座に判定。LLMエラー時のフォールバックにもなる。

CRITICAL_RULES: list[dict] = [
    {
        "keywords": [re.compile(r"ブレーキ.{0,10}(効かない|効きが悪い|効かなく|止まらない|止まれない|抜け)")],
        "match": "any",
        "reason": "ブレーキの不具合は走行安全に直結します。直ちに運転を中止してください。",
    },
    {
        "keywords": ["ブレーキ", "故障"],
        "match": "all",
        "reason": "ブレーキの故障は非常に危険です。直ちに運転を中止してください。",
    },
    {
        "keywords": [re.compile(r"(煙|白煙|黒煙)")],
        "match": "any",
        "reason": "車両から煙が出ています。火災の危険があるため、直ちに安全な場所に停車してください。",
    },
    {
        "keywords": [re.compile(r"(発火|火|燃え)")],
        "match": "any",
        "reason": "火災の危険があります。直ちに車両から離れ、119番に通報してください。",
    },
    {
        "keywords": [re.compile(r"オイル.{0,5}漏")],
        "match": "any",
        "reason": "オイル漏れはエンジン焼き付きや火災の原因になります。直ちに点検が必要です。",
    },
    {
        "keywords": [re.compile(r"(ステアリング|ハンドル).{0,10}(効かない|動かない|重い|ロック)")],
        "match": "any",
        "reason": "ステアリング系統の異常は走行不能や事故の原因になります。直ちに運転を中止してください。",
    },
    {
        "keywords": [re.compile(r"(冷却水|クーラント).{0,10}(漏|減|なくな)")],
        "match": "any",
        "reason": "冷却水の不足はエンジンオーバーヒートの原因になります。直ちに停車してください。",
    },
    {
        "keywords": [re.compile(r"(オーバーヒート|過熱|水温.{0,5}(高|異常|赤))")],
        "match": "any",
        "reason": "エンジンのオーバーヒートです。直ちに安全な場所に停車し、エンジンを停止してください。",
    },
]

HIGH_RULES: list[dict] = [
    {
        "keywords": [re.compile(r"警告(灯|ランプ|マーク)")],
        "match": "any",
        "reason": "警告灯が点灯しています。早めにディーラーまたは整備工場で点検してください。",
    },
    {
        "keywords": [re.compile(r"(エンジン|チェックエンジン).{0,10}(ランプ|灯|点灯|光)")],
        "match": "any",
        "reason": "エンジン警告灯の点灯は、排気系統やセンサーの異常の可能性があります。",
    },
    {
        "keywords": [re.compile(r"(異音|ガタガタ|キーキー|ゴロゴロ|カタカタ|キュルキュル)")],
        "match": "any",
        "reason": "異音は部品の摩耗や故障のサインです。早めの点検をお勧めします。",
    },
    {
        "keywords": [re.compile(r"(振動|ブルブル|ガクガク)")],
        "match": "any",
        "reason": "走行中の異常な振動は、足回りやエンジンマウントの問題の可能性があります。",
    },
    {
        "keywords": [re.compile(r"(焦げ|臭|匂い|におい).{0,10}(臭|ゴム|オイル|ガソリン)")],
        "match": "any",
        "reason": "異臭は部品の過熱やオイル漏れの可能性があります。早めの点検が必要です。",
    },
    {
        "keywords": [re.compile(r"(タイヤ|パンク).{0,10}(空気|減|漏|ぺちゃんこ)")],
        "match": "any",
        "reason": "タイヤの空気圧異常はバーストの危険があります。速やかに確認してください。",
    },
    {
        "keywords": [re.compile(r"(ABS|エアバッグ|SRS).{0,10}(灯|ランプ|点灯|光)")],
        "match": "any",
        "reason": "安全装置の警告灯です。万一の際に正常動作しない可能性があります。",
    },
]

MEDIUM_RULES: list[dict] = [
    {
        "keywords": [re.compile(r"(燃費|ガソリン).{0,10}(悪|減|食)")],
        "match": "any",
        "reason": "燃費の悪化はエンジンや点火系統の劣化の可能性があります。",
    },
    {
        "keywords": [re.compile(r"(エアコン|冷房|暖房).{0,10}(効かない|弱|出ない)")],
        "match": "any",
        "reason": "エアコンの不具合です。ガス補充やコンプレッサーの点検が必要かもしれません。",
    },
    {
        "keywords": [re.compile(r"(バッテリー|始動).{0,10}(弱|上が|かから)")],
        "match": "any",
        "reason": "バッテリーの劣化やオルタネーターの不具合の可能性があります。",
    },
    {
        "keywords": [re.compile(r"(ワイパー|ウォッシャー).{0,10}(動かない|出ない)")],
        "match": "any",
        "reason": "視界確保に関わる部品の不具合です。雨天時の安全に影響します。",
    },
]


def _match_rule(rule: dict, text: str) -> bool:
    """ルール内のキーワード/正規表現をテキストにマッチさせる"""
    match_type = rule.get("match", "all")
    results = []
    for kw in rule["keywords"]:
        if isinstance(kw, re.Pattern):
            results.append(bool(kw.search(text)))
        else:
            results.append(kw in text)

    if match_type == "any":
        return any(results)
    return all(results)


def keyword_urgency_check(symptom: str) -> dict | None:
    """
    キーワードベースで緊急度を即座に判定する。
    マッチしたルールすべての理由を集約して返す。
    マッチなしの場合は None を返し、LLM判定にフォールスルーする。
    """
    text = symptom.lower() if symptom else ""
    original = symptom or ""

    critical_reasons = []
    for rule in CRITICAL_RULES:
        if _match_rule(rule, original) or _match_rule(rule, text):
            critical_reasons.append(rule["reason"])

    if critical_reasons:
        return {
            "level": "critical",
            "requires_visit": True,
            "can_drive": False,
            "visit_urgency": "immediate",
            "reasons": critical_reasons,
            "recommendation": "直ちに運転を中止し、安全な場所に停車してください。ロードサービスまたはディーラーに連絡してください。",
            "keyword_matched": True,
        }

    high_reasons = []
    for rule in HIGH_RULES:
        if _match_rule(rule, original) or _match_rule(rule, text):
            high_reasons.append(rule["reason"])

    if high_reasons:
        return {
            "level": "high",
            "requires_visit": True,
            "can_drive": True,
            "visit_urgency": "today",
            "reasons": high_reasons,
            "recommendation": "できるだけ早くディーラーまたは整備工場で点検を受けてください。",
            "keyword_matched": True,
        }

    medium_reasons = []
    for rule in MEDIUM_RULES:
        if _match_rule(rule, original) or _match_rule(rule, text):
            medium_reasons.append(rule["reason"])

    if medium_reasons:
        return {
            "level": "medium",
            "requires_visit": False,
            "can_drive": True,
            "visit_urgency": "this_week",
            "reasons": medium_reasons,
            "recommendation": "お時間のあるときにディーラーまたは整備工場で点検を受けることをお勧めします。",
            "keyword_matched": True,
        }

    return None


class UrgencyAssessor:
    async def assess(
        self,
        symptom: str,
        vehicle_id: str | None = None,
        make: str = "",
        model: str = "",
        year: int = 0,
    ) -> dict:
        # 1. まずキーワードベースで即座に判定
        keyword_result = keyword_urgency_check(symptom)
        if keyword_result and keyword_result["level"] in ("critical", "high"):
            # critical/high はキーワードだけで確定（速度とフォールバック重視）
            return keyword_result

        # 2. LLMによる詳細判定
        warnings = await rag_service.get_warnings(vehicle_id, symptom)
        warnings_text = "\n".join([w["content"][:300] for w in warnings]) if warnings else "関連する警告情報はありません"

        prompt = URGENCY_ASSESSMENT_PROMPT.format(
            make=make or "不明",
            model=model or "不明",
            year=year or "不明",
            symptom=symptom,
            warnings=warnings_text,
        )

        provider = provider_registry.get_active()
        if not provider or not provider.is_configured():
            # LLM使えない場合、キーワード結果があればそれを返す
            return keyword_result or self._default_assessment()

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_schema", "json_schema": URGENCY_SCHEMA},
            )
            result = json.loads(response.content)
            level = result.get("level", "medium")
            can_drive = result.get("can_drive", level != "critical")
            llm_result = {
                "level": level,
                "requires_visit": level in ("high", "critical"),
                "can_drive": can_drive,
                "visit_urgency": result.get("visit_urgency", "this_week"),
                "reasons": result.get("reasons", []),
                "recommendation": result.get("recommendation", ""),
                "keyword_matched": False,
            }

            # キーワード結果とLLM結果を統合：より高い緊急度を採用
            if keyword_result:
                level_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
                kw_level = level_order.get(keyword_result["level"], 0)
                llm_level = level_order.get(llm_result["level"], 0)
                if kw_level >= llm_level:
                    # キーワードの理由もマージ
                    merged_reasons = list(dict.fromkeys(keyword_result["reasons"] + llm_result["reasons"]))
                    keyword_result["reasons"] = merged_reasons
                    return keyword_result
                else:
                    merged_reasons = list(dict.fromkeys(llm_result["reasons"] + keyword_result["reasons"]))
                    llm_result["reasons"] = merged_reasons
                    return llm_result

            return llm_result

        except (json.JSONDecodeError, Exception):
            # LLMエラー時はキーワード結果をフォールバック
            return keyword_result or self._default_assessment()

    def _default_assessment(self) -> dict:
        return {
            "level": "medium",
            "requires_visit": False,
            "can_drive": True,
            "visit_urgency": "this_week",
            "reasons": ["自動判定ができませんでした。症状が続く場合はディーラーにご相談ください。"],
            "recommendation": "症状が続く場合は、お近くのディーラーにご相談ください。",
            "keyword_matched": False,
        }


urgency_assessor = UrgencyAssessor()
