import json
import logging
import re

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo, RAGSource
from app.llm.registry import provider_registry
from app.llm.prompts import SYSTEM_PROMPT, DIAGNOSTIC_PROMPT
from app.llm.schemas import DIAGNOSTIC_SCHEMA
from app.services.rag_service import rag_service
from app.services.urgency_assessor import keyword_urgency_check

logger = logging.getLogger(__name__)


FALLBACK_QUESTIONS = [
    "症状が出るのは走行中ですか？それとも停車しているときですか？",
    "症状が出る頻度はどのくらいですか？（毎回・たまに・一度だけなど）",
    "エンジンをかけたとき、メーターパネルに見慣れない表示は出ていますか？",
    "最近、車の点検や修理をされましたか？",
    "症状が出るとき、何か特別な操作をしていますか？（例：エアコンをつけた、坂道を走ったなど）",
]

# Task 2: 待ちメッセージ検出パターン
_WAITING_PATTERN = re.compile(r"まとめ|整理|お待ち|確認.{0,5}させ|少々", re.UNICODE)

# Tip 1: 候補ラベル補助辞書（LLMが短すぎる単語を返したときに説明付きに変換）
_CANDIDATE_HINTS: dict[str, str] = {
    "ブレーキパッド": "ブレーキパッド摩耗（キーキー/金属音）",
    "ローター": "ブレーキローター（擦れ/振動）",
    "ブレーキローター": "ブレーキローター（擦れ/振動）",
    "タイヤ": "タイヤ異常（パンク/偏摩耗）",
    "バッテリー": "バッテリー劣化（始動不良）",
    "オルタネーター": "オルタネーター（発電機）故障",
    "ベルト": "ベルト類損傷（ギーギー音）",
    "エンジン": "エンジン内部異常（振動/異音）",
    "サスペンション": "サスペンション（ゴトゴト音）",
    "ショック": "ショックアブソーバー劣化",
    "プラグ": "スパークプラグ不良（点火）",
    "燃料": "燃料系統（出力低下）",
    "冷却水": "冷却水不足（過熱）",
    "クーラント": "クーラント漏れ（過熱）",
    "オイル": "エンジンオイル（漏れ/不足）",
    "マフラー": "マフラー異常（排気音変化）",
    "CVT": "CVT（変速機）不具合",
    "AT": "AT（オートマ）不具合",
    "クラッチ": "クラッチ摩耗（滑り）",
    "ハブ": "ハブベアリング（走行異音）",
    "パワステ": "パワーステアリング不具合",
}


def _enrich_candidate_label(label: str) -> str:
    """短すぎる候補ラベルを補助辞書で説明付きに変換する。"""
    s = label.strip()
    # 既に括弧付きか十分な長さなら変換不要
    if "（" in s or "(" in s or len(s) >= 12:
        return s
    for key, hint in _CANDIDATE_HINTS.items():
        if key in s:
            return hint
    return s


# A) ask_question / clarify_term の末尾に必ず追加するデフォルト選択肢
_DEFAULT_TAIL: list[dict] = [
    {"value": "dont_know", "label": "わからない"},
    {"value": "free_input", "label": "✏️ 自由入力"},
]


def _append_default_choices(choices: list[str] | None) -> list[dict]:
    """LLM が返した choices に「わからない」「自由入力」を末尾追加する（重複除外）。"""
    result: list[dict] = []
    if choices:
        result = [{"value": c, "label": _enrich_candidate_label(c)} for c in choices]
    existing_values = {d["value"] for d in result}
    for tail in _DEFAULT_TAIL:
        if tail["value"] not in existing_values:
            result.append(tail)
    return result


def _is_waiting_message(msg: str) -> bool:
    """True if message looks like a 'please wait' transition, not a real question."""
    if "？" in msg or "?" in msg:
        return False
    return bool(_WAITING_PATTERN.search(msg))


def _build_conversation_text(session: SessionState) -> str:
    """Build conversation history as text for the prompt."""
    lines = []
    for entry in session.conversation_history:
        role = "ユーザー" if entry["role"] == "user" else "アシスタント"
        lines.append(f"{role}: {entry['content']}")
    return "\n".join(lines) if lines else "(初回入力)"


def _normalize_question(text: str) -> str:
    """Normalize a question for duplicate comparison."""
    text = re.sub(r"[？?。、！!.,\s　]+", "", text)
    return text.lower()


def _is_duplicate_question(message: str, last_questions: list[str]) -> bool:
    """Check if the LLM question is semantically a duplicate of a recent one."""
    norm_new = _normalize_question(message)
    if not norm_new:
        return False
    for prev in last_questions:
        norm_prev = _normalize_question(prev)
        if not norm_prev:
            continue
        if norm_new == norm_prev:
            return True
        shorter, longer = sorted([norm_new, norm_prev], key=len)
        if len(shorter) >= 4 and shorter in longer:
            return True
    return False


def _pick_fallback_question(session: SessionState) -> str | None:
    """Pick a fallback question that hasn't been asked yet."""
    for q in FALLBACK_QUESTIONS:
        if not _is_duplicate_question(q, session.last_questions):
            return q
    return None


async def _llm_call(provider, diagnostic_prompt: str) -> dict:
    """Call LLM with DIAGNOSTIC_SCHEMA and return parsed JSON."""
    response = await provider.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": diagnostic_prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_schema", "json_schema": DIAGNOSTIC_SCHEMA},
    )
    return json.loads(response.content)


async def handle_diagnosing(session: SessionState, request: ChatRequest) -> ChatResponse:
    user_input = (request.message or "").strip()

    # Handle "resolved" action from provide_answer step
    if request.action == "resolved":
        if request.action_value == "yes":
            session.current_step = ChatStep.DONE
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DONE.value,
                prompt=PromptInfo(
                    type="text",
                    message="お役に立てて良かったです！他にご質問があれば、新しい問診を開始してください。\n安全運転をお願いいたします。",
                ),
            )
        elif request.action_value == "no":
            session.current_step = ChatStep.URGENCY_CHECK
            from app.chat_flow.step_urgency import handle_urgency_check
            return await handle_urgency_check(session, request)
        elif request.action_value == "book":
            # 「点検を予約する」を直接選択
            session.current_step = ChatStep.RESERVATION
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)
        else:
            # 想定外の値はログだけ残して無視（diagnosis_candidates は sendMessage 経由なので通常ここに来ない）
            logger.warning(f"Unexpected resolved value: {request.action_value!r}")
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DIAGNOSING.value,
                prompt=PromptInfo(type="text", message="症状について教えてください。"),
            )

    if not user_input:
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="text",
                message="症状について教えてください。",
            ),
        )

    # ---------------------------------------------------------------
    # 1. Save user input FIRST
    # ---------------------------------------------------------------
    session.collected_symptoms.append(user_input)
    session.conversation_history.append({"role": "user", "content": user_input})
    session.diagnostic_turn += 1

    # 2. Keyword-based urgency check (fast path for critical)
    all_symptoms = " ".join(session.collected_symptoms)
    keyword_result = keyword_urgency_check(all_symptoms)
    if keyword_result and keyword_result["level"] == "critical":
        session.urgency_level = "critical"
        session.can_drive = False
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # 3. RAG search
    rag_context = "関連するマニュアル情報はありません。"
    rag_sources: list[RAGSource] = []
    try:
        results = await rag_service.query(
            symptom=all_symptoms,
            vehicle_id=session.vehicle_id,
            make=session.vehicle_make or "",
            model=session.vehicle_model or "",
            year=session.vehicle_year or 0,
        )
        if results["sources"]:
            rag_context = results["answer"]
            rag_sources = [
                RAGSource(
                    content=s["content"],
                    page=s["page"],
                    section=s["section"],
                    score=s["score"],
                )
                for s in results["sources"]
            ]
    except Exception as e:
        logger.warning(f"RAG query failed: {e}")

    # 4. Build prompt
    conversation_text = _build_conversation_text(session)
    diagnostic_prompt = DIAGNOSTIC_PROMPT.format(
        make=session.vehicle_make or "不明",
        model=session.vehicle_model or "不明",
        year=session.vehicle_year or "不明",
        conversation_history=conversation_text,
        rag_context=rag_context,
    )

    # 5. Force provide_answer if max turns reached
    if session.diagnostic_turn >= session.max_diagnostic_turns:
        diagnostic_prompt += "\n\n【重要】問診回数の上限に達しました。これまでの情報をもとに action: \"provide_answer\" で回答を提供してください。"

    # ---------------------------------------------------------------
    # Task 3: turn>=4 で一回だけ候補提示 / 候補選択後は provide_answer へ
    # ---------------------------------------------------------------
    candidates_just_triggered = False
    if session.diagnostic_turn >= 4 and not session.candidates_shown:
        session.candidates_shown = True
        candidates_just_triggered = True
        diagnostic_prompt += (
            "\n\n【重要】これまでの問診から考えられる原因を4つに絞り込んでください。"
            "action: \"ask_question\", "
            "message は「原因として最も近いものはどれですか？」（30文字以内・1文）, "
            "choices に考えられる原因を4個（各10文字以内）＋「その他」の計5個を必ず設定してください。"
        )
    elif session.candidates_shown and not candidates_just_triggered:
        # 候補選択後 → すぐに回答を出す
        diagnostic_prompt += (
            f"\n\n【重要】ユーザーが原因候補「{user_input}」を選択しました。"
            "この候補に基づいてすぐに action: \"provide_answer\" で具体的な回答を提供してください。"
        )

    # 6. Call LLM
    provider = provider_registry.get_active()
    if not provider or not provider.is_configured():
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="text",
                message="LLMプロバイダーが設定されていません。設定を確認してください。",
            ),
        )

    try:
        result = await _llm_call(provider, diagnostic_prompt)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"LLM diagnostic call failed: {e}")
        fallback_msg = _pick_fallback_question(session)
        session.last_questions.append(fallback_msg)
        session.conversation_history.append({"role": "assistant", "content": fallback_msg})
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(type="text", message=fallback_msg),
        )

    action = result.get("action", "ask_question")
    message = result.get("message", "")
    urgency_flag = result.get("urgency_flag", "none")
    reasoning = result.get("reasoning", "")
    choices = result.get("choices")
    can_drive_llm: bool | None = result.get("can_drive")  # True / False / None

    logger.info(f"Diagnostic action={action}, urgency={urgency_flag}, reasoning={reasoning}")

    # ---------------------------------------------------------------
    # Task 2: 待ちメッセージ検出 → リトライして provide_answer を取得
    # ---------------------------------------------------------------
    if action == "ask_question" and _is_waiting_message(message):
        logger.warning(f"Waiting message detected, retrying: {message!r}")
        retry_prompt = (
            diagnostic_prompt
            + "\n\n【重要】「まとめます」「整理します」などの待機メッセージは出さないでください。"
            "今すぐ action: \"provide_answer\" で診断結果を提供してください。"
        )
        try:
            result = await _llm_call(provider, retry_prompt)
            action = result.get("action", "provide_answer")
            message = result.get("message", message)
            urgency_flag = result.get("urgency_flag", urgency_flag)
            choices = result.get("choices")
            can_drive_llm = result.get("can_drive", can_drive_llm)
        except Exception as e:
            logger.warning(f"Retry LLM call failed: {e}")
            action = "provide_answer"

    # 7. Check urgency_flag from LLM
    if urgency_flag in ("high", "critical"):
        session.urgency_level = urgency_flag
        # LLM の can_drive 優先。None なら urgency_flag で推定（critical → False）
        session.can_drive = can_drive_llm if can_drive_llm is not None else (urgency_flag != "critical")
        if urgency_flag == "critical":
            session.current_step = ChatStep.RESERVATION
            session.conversation_history.append({"role": "assistant", "content": message})
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)

    # 8. Dispatch based on action
    if action == "escalate":
        session.urgency_level = urgency_flag if urgency_flag in ("high", "critical") else "high"
        session.can_drive = session.urgency_level != "critical"
        session.conversation_history.append({"role": "assistant", "content": message})
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    if action == "provide_answer":
        session.rag_answer = message
        session.conversation_history.append({"role": "assistant", "content": message})

        # C) high/critical → 強い警告 + 予約導線（reservation_choice）
        if urgency_flag in ("high", "critical"):
            # True のときだけ自走可。False も None（不明）も → 自走禁止扱い
            effective_can_drive = can_drive_llm if can_drive_llm is True else False
            session.urgency_level = urgency_flag
            session.can_drive = effective_can_drive
            session.current_step = ChatStep.RESERVATION

            if not effective_can_drive:
                warning = (
                    "🚨【自走禁止】すぐに運転を中止し、安全な場所に停車してください。\n\n"
                    f"{message}\n\n"
                    "ロードサービスへの連絡を強くお勧めします。"
                )
                reservation_choices = [
                    {"value": "dispatch", "label": "ロードサービスを呼ぶ"},
                    {"value": "skip", "label": "今は予約しない"},
                ]
            else:
                warning = (
                    "⚠️【早急な点検推奨】無理な運転は避けてください。\n\n"
                    f"{message}\n\n"
                    "早急にディーラーまたは整備工場での点検をお勧めします。"
                )
                reservation_choices = [
                    {"value": "dispatch", "label": "ロードサービスを呼ぶ"},
                    {"value": "visit", "label": "ディーラーに持ち込む"},
                    {"value": "skip", "label": "今は予約しない"},
                ]

            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.RESERVATION.value,
                prompt=PromptInfo(
                    type="reservation_choice",
                    message=warning,
                    choices=reservation_choices,
                    booking_type=session.booking_type,
                ),
                rag_sources=rag_sources,
            )

        # low/medium/none → 解決確認 + 予約へのショートカット
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="single_choice",
                message=message,
                choices=[
                    {"value": "yes", "label": "解決しました"},
                    {"value": "no", "label": "解決していません"},
                    {"value": "book", "label": "予約したい"},
                ],
            ),
            rag_sources=rag_sources,
        )

    if action == "clarify_term":
        session.conversation_history.append({"role": "assistant", "content": message})
        session.last_questions.append(message)
        # A) 「わからない」「自由入力」を末尾に必ず追加
        prompt_choices = _append_default_choices(choices)
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="single_choice",
                message=message,
                choices=prompt_choices,
            ),
        )

    # ---------------------------------------------------------------
    # Task 3: 候補提示 — candidates_just_triggered かつ choices が揃っていれば
    #          diagnosis_candidates として返す（Tip 1: ラベル補強）
    # ---------------------------------------------------------------
    if candidates_just_triggered and choices and len(choices) >= 4:
        prompt_choices = [{"value": c, "label": _enrich_candidate_label(c)} for c in choices]
        session.conversation_history.append({"role": "assistant", "content": message})
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="diagnosis_candidates",
                message=message,
                choices=prompt_choices,
            ),
        )

    # ---------------------------------------------------------------
    # 9. ask_question — duplicate guard
    # ---------------------------------------------------------------
    if _is_duplicate_question(message, session.last_questions):
        logger.warning(f"Duplicate question detected, replacing: {message!r}")
        message = _pick_fallback_question(session)

    # A) 「わからない」「自由入力」を末尾に必ず追加
    choices_for_prompt = _append_default_choices(choices)

    session.last_questions.append(message)
    session.conversation_history.append({"role": "assistant", "content": message})
    return ChatResponse(
        session_id=session.session_id,
        current_step=ChatStep.DIAGNOSING.value,
        prompt=PromptInfo(
            type="single_choice",
            message=message,
            choices=choices_for_prompt,
        ),
    )
