import json
import logging
import re

from app.models.session import SessionState, ChatStep
from app.models.chat import ChatRequest, ChatResponse, PromptInfo, RAGSource
from app.llm.registry import provider_registry
from app.llm.prompts import SYSTEM_PROMPT, DIAGNOSTIC_PROMPT, CONVERSATION_SUMMARY_PROMPT
from app.llm.schemas import DIAGNOSTIC_SCHEMA
from app.services.rag_service import rag_service
from app.services.urgency_assessor import keyword_urgency_check
from app.data.diagnostic_config_loader import get_candidate_hints

logger = logging.getLogger(__name__)

# Task 2: 待ちメッセージ検出パターン
_WAITING_PATTERN = re.compile(r"まとめ|整理|お待ち|確認.{0,5}させ|少々", re.UNICODE)

# Tip 1: 候補ラベル補助辞書（YAML から読み込み）
_CANDIDATE_HINTS = get_candidate_hints()


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


# ---------------------------------------------------------------------------
# トピック関連性ガード
# ---------------------------------------------------------------------------
# 症状に含まれない限りブロックすべきトピックとそのキーワード
_GUARDED_TOPICS: dict[str, list[str]] = {
    "音": ["音", "サウンド", "鳴", "キー", "ゴリ", "カタ", "ガタ", "ギー", "異音"],
    "振動": ["振動", "ブルブル", "ガクガク", "揺れ"],
    "臭い": ["臭", "匂", "におい", "スメル"],
    "煙": ["煙", "白煙", "黒煙"],
}


def _is_irrelevant_topic(topic: str, symptom_text: str, conversation_history: list[dict]) -> bool:
    """question_topic がユーザーの症状・会話に無関係かどうか判定する。

    ガードリストにあるトピックについて、症状テキストと会話履歴に
    関連キーワードが一切含まれていない場合に True を返す。
    ガードリストにないトピックは常に False（許可）。
    """
    # 全テキストを結合して検索対象にする
    all_text = symptom_text
    for entry in conversation_history:
        if entry["role"] == "user":
            all_text += " " + entry["content"]

    for guarded_name, keywords in _GUARDED_TOPICS.items():
        # topic がこのガードカテゴリに該当するか
        if any(kw in topic for kw in keywords) or guarded_name in topic:
            # 症状テキスト+会話にキーワードが1つでもあれば関連あり
            if any(kw in all_text for kw in keywords):
                return False  # 関連あり → ブロックしない
            return True  # 関連なし → ブロック
    return False  # ガード対象外 → 許可


# ---------------------------------------------------------------------------
# RAG駆動型ヘルパー関数
# ---------------------------------------------------------------------------

def _build_recent_turns(session: SessionState, n: int = 4) -> str:
    """直近N件のやり取りのみテキスト化する。"""
    history = session.conversation_history
    recent = history[-n:] if len(history) > n else history
    lines = []
    for entry in recent:
        role = "ユーザー" if entry["role"] == "user" else "アシスタント"
        lines.append(f"{role}: {entry['content']}")
    return "\n".join(lines) if lines else "(初回入力)"


def _build_additional_instructions(session: SessionState, user_input: str, candidates_just_triggered: bool) -> str:
    """条件付き指示を一括構築して返す。"""
    parts: list[str] = []

    # 改善C: Spec hint injection
    if session.spec_hint:
        parts.append(
            "\n\n【参考】この症状はマニュアルに仕様として記載されている可能性があります。"
            "マニュアル関連情報を確認し、仕様に該当する場合は action: \"spec_answer\" を優先してください。"
        )

    # Force provide_answer if max turns reached
    if session.diagnostic_turn >= session.max_diagnostic_turns:
        parts.append(
            "\n\n【重要】問診回数の上限に達しました。これまでの情報をもとに action: \"provide_answer\" で回答を提供してください。"
        )

    # 解決策提示トリガー
    if candidates_just_triggered or (session.candidates_shown and session.solutions_tried == 0):
        parts.append(
            "\n\n【重要】これまでの情報から、最も可能性の高い原因を1つ特定し、"
            "ユーザーが自分で試せる具体的な対処手順を action: \"provide_answer\" で提示してください。"
            "手順は番号付きで、素人でもできる内容にしてください。"
        )
    elif session.solutions_tried > 0:
        parts.append(
            f"\n\n【重要】前回提示した解決策ではユーザーの問題が解決しませんでした（{session.solutions_tried}回目）。"
            "次に可能性の高い別の原因と対処法を action: \"provide_answer\" で提示してください。"
            "前回と異なる原因・対処法を提示してください。"
        )

    return "".join(parts)


async def _maybe_summarize(session: SessionState, provider) -> None:
    """diagnostic_turn が3の倍数かつ >= 3 のとき、会話を要約して conversation_summary を更新。"""
    if session.diagnostic_turn < 3 or session.diagnostic_turn % 3 != 0:
        return

    # 要約対象: conversation_history 全体
    lines = []
    for entry in session.conversation_history:
        role = "ユーザー" if entry["role"] == "user" else "アシスタント"
        lines.append(f"{role}: {entry['content']}")
    conversation_text = "\n".join(lines)

    summary_prompt = CONVERSATION_SUMMARY_PROMPT.format(conversation_text=conversation_text)

    try:
        response = await provider.chat(
            messages=[
                {"role": "user", "content": summary_prompt},
            ],
            temperature=0.1,
        )
        session.conversation_summary = response.content.strip()
        logger.info(f"Conversation summary updated (turn {session.diagnostic_turn})")
    except Exception as e:
        logger.warning(f"Conversation summary failed: {e}")


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
            session.solutions_tried += 1
            # 3回解決策を試しても解決しない場合 → 専門家へ
            if session.solutions_tried >= 3:
                session.current_step = ChatStep.URGENCY_CHECK
                from app.chat_flow.step_urgency import handle_urgency_check
                return await handle_urgency_check(session, request)
            # まだ別の解決策を試す → DIAGNOSING に留まり次の策を提示
            request.message = "解決しませんでした。他の原因を教えてください。"
            return await handle_diagnosing(session, request)
        elif request.action_value == "book":
            # 「点検を予約する」を直接選択
            session.current_step = ChatStep.RESERVATION
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)
        else:
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
    # 1. Save user input + diagnostic_turn++
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

    # 3. RAG query: use rewritten_query if available, otherwise all_symptoms
    rag_query = session.rewritten_query if session.rewritten_query else all_symptoms
    rag_context = "関連するマニュアル情報はありません。"
    rag_sources: list[RAGSource] = []
    try:
        results = await rag_service.query(
            symptom=rag_query,
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

    # 4. Maybe summarize conversation (every 3 turns)
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

    await _maybe_summarize(session, provider)

    # 5. Candidate trigger: confidence >= 0.7 OR turn >= 4 (fallback)
    candidates_just_triggered = False
    if not session.candidates_shown:
        if session.last_confidence >= 0.7 or session.diagnostic_turn >= 4:
            session.candidates_shown = True
            candidates_just_triggered = True

    # 6. Build prompt
    recent_turns = _build_recent_turns(session)
    additional_instructions = _build_additional_instructions(session, user_input, candidates_just_triggered)

    diagnostic_prompt = DIAGNOSTIC_PROMPT.format(
        make=session.vehicle_make or "不明",
        model=session.vehicle_model or "不明",
        year=session.vehicle_year or "不明",
        original_symptom=session.symptom_text or all_symptoms,
        conversation_summary=session.conversation_summary or "(なし)",
        recent_turns=recent_turns,
        rag_context=rag_context,
        additional_instructions=additional_instructions,
    )

    # 7. Call LLM
    try:
        result = await _llm_call(provider, diagnostic_prompt)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"LLM diagnostic call failed: {e}")
        fallback_msg = "他に気になる症状や状況があれば教えてください。"
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
    can_drive_llm: bool | None = result.get("can_drive")

    # 8. Save rewritten_query and confidence
    session.rewritten_query = result.get("rewritten_query", "")
    session.last_confidence = result.get("confidence_to_answer", 0.0)
    question_topic = result.get("question_topic", "")

    logger.info(
        f"Diagnostic action={action}, urgency={urgency_flag}, "
        f"confidence={session.last_confidence:.2f}, topic={question_topic!r}, reasoning={reasoning}"
    )

    # 8b. Topic relevance guard: reject questions on topics absent from symptom text
    if action == "ask_question" and question_topic:
        symptom_text = (session.symptom_text or "") + " " + " ".join(session.collected_symptoms)
        if _is_irrelevant_topic(question_topic, symptom_text, session.conversation_history):
            logger.warning(
                f"Irrelevant topic blocked: topic={question_topic!r}, symptom={session.symptom_text!r}"
            )
            # Force a re-call with explicit instruction
            regen_prompt = (
                diagnostic_prompt
                + f"\n\n【重要】「{question_topic}」はユーザーの症状と無関係です。"
                "ユーザーが報告した症状の文面に含まれるトピックだけに基づいて質問してください。"
                "症状の原因を絞り込むために、操作の状況・条件・再現性など、症状に直結する質問をしてください。"
            )
            try:
                result = await _llm_call(provider, regen_prompt)
                action = result.get("action", "ask_question")
                message = result.get("message", message)
                urgency_flag = result.get("urgency_flag", urgency_flag)
                choices = result.get("choices")
                can_drive_llm = result.get("can_drive", can_drive_llm)
                session.rewritten_query = result.get("rewritten_query", session.rewritten_query)
                session.last_confidence = result.get("confidence_to_answer", session.last_confidence)
                question_topic = result.get("question_topic", "")
            except Exception as e:
                logger.warning(f"Topic guard re-call failed: {e}")

    # ---------------------------------------------------------------
    # 9. 待ちメッセージ検出 → リトライして provide_answer を取得
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
            session.rewritten_query = result.get("rewritten_query", session.rewritten_query)
            session.last_confidence = result.get("confidence_to_answer", session.last_confidence)
        except Exception as e:
            logger.warning(f"Retry LLM call failed: {e}")
            action = "provide_answer"

    # 10. Check urgency_flag from LLM
    if urgency_flag in ("high", "critical"):
        session.urgency_level = urgency_flag
        session.can_drive = can_drive_llm if can_drive_llm is not None else (urgency_flag != "critical")
        if urgency_flag == "critical":
            session.current_step = ChatStep.RESERVATION
            session.conversation_history.append({"role": "assistant", "content": message})
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)

    # 11. Dispatch based on action
    if action == "escalate":
        session.urgency_level = urgency_flag if urgency_flag in ("high", "critical") else "high"
        session.can_drive = session.urgency_level != "critical"
        session.conversation_history.append({"role": "assistant", "content": message})
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # 改善C: spec_answer — redirect to SPEC_CHECK flow
    if action == "spec_answer":
        session.spec_check_shown = True
        session.current_step = ChatStep.SPEC_CHECK
        session.conversation_history.append({"role": "assistant", "content": message})

        spec_message = f"マニュアルを確認したところ、これは仕様（正常な動作）の可能性があります。\n\n{message}"
        spec_message += "\n\nこの説明で疑問は解決しましたか？"

        spec_choices = [
            {"value": "resolved", "label": "解決しました"},
            {"value": "not_resolved", "label": "解決していません"},
            {"value": "already_tried", "label": "それは試しました / 知っています"},
        ]
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.SPEC_CHECK.value,
            prompt=PromptInfo(
                type="single_choice",
                message=spec_message,
                choices=spec_choices,
            ),
            rag_sources=rag_sources,
        )

    if action == "provide_answer":
        session.rag_answer = message
        session.conversation_history.append({"role": "assistant", "content": message})

        # C) high/critical → 強い警告 + 予約導線（reservation_choice）
        if urgency_flag in ("high", "critical"):
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
    # 12. ask_question — duplicate guard (lightweight)
    # ---------------------------------------------------------------
    if _is_duplicate_question(message, session.last_questions):
        logger.warning(f"Duplicate question detected, replacing: {message!r}")
        message = "他に気になる症状や状況があれば教えてください。"

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
