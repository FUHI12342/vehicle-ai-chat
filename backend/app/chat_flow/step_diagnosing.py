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

logger = logging.getLogger(__name__)

# Task 2: 待ちメッセージ検出パターン
_WAITING_PATTERN = re.compile(r"まとめ|整理|お待ち|確認.{0,5}させ|少々", re.UNICODE)

# マルチステップダンプ検出パターン（番号付きリストが2行以上）
_MULTI_STEP_PATTERN = re.compile(r"(?:\d+[.、）]\s.*\n){2,}", re.UNICODE)


# A) ask_question / clarify_term の末尾に必ず追加するデフォルト選択肢
_DEFAULT_TAIL: list[dict] = [
    {"value": "dont_know", "label": "わからない"},
    {"value": "free_input", "label": "✏️ 自由入力"},
]


WARNING_LIGHT_ICONS: dict[str, str] = {
    "エンジン": "/icons/warning-lights/engine.svg",
    "ABS": "/icons/warning-lights/abs.svg",
    "油圧": "/icons/warning-lights/oil.svg",
    "オイル": "/icons/warning-lights/oil.svg",
    "水温": "/icons/warning-lights/coolant.svg",
    "バッテリー": "/icons/warning-lights/battery.svg",
    "充電": "/icons/warning-lights/battery.svg",
    "エアバッグ": "/icons/warning-lights/airbag.svg",
    "ブレーキ": "/icons/warning-lights/brake.svg",
    "パワステ": "/icons/warning-lights/power-steering.svg",
    "タイヤ": "/icons/warning-lights/tpms.svg",
    "空気圧": "/icons/warning-lights/tpms.svg",
    "シートベルト": "/icons/warning-lights/seatbelt.svg",
}

VISUAL_TOPICS = {"警告灯", "ランプ", "表示灯", "インジケーター"}


def _attach_icons(choices: list[dict], question_topic: str | None) -> list[dict]:
    """警告灯系の質問トピックの場合、選択肢にアイコンパスを付与する。"""
    if not question_topic or not any(kw in question_topic for kw in VISUAL_TOPICS):
        return choices
    for choice in choices:
        label = choice.get("label", "")
        for keyword, icon_path in WARNING_LIGHT_ICONS.items():
            if keyword in label:
                choice["icon"] = icon_path
                break
    return choices


_FILTER_KEYWORDS = {"わからない", "わかりません", "不明", "自由入力", "自由回答", "その他"}


def _append_default_choices(choices: list[str] | None) -> list[dict]:
    """LLM が返した choices に「わからない」「自由入力」を末尾追加する（重複除外）。"""
    result: list[dict] = []
    seen: set[str] = set()
    if choices:
        for c in choices:
            # LLMが「わからない」等の汎用選択肢を生成した場合は除外
            if c not in seen and c not in _FILTER_KEYWORDS:
                seen.add(c)
                result.append({"value": c, "label": c})
    for tail in _DEFAULT_TAIL:
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

def _build_recent_turns(session: SessionState, n: int = 6) -> str:
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
            "\n\n【重要】問診回数の上限に達しました。これまでの情報をもとに "
            "action: \"provide_answer\" で最終結論を提供してください。"
        )
    # Soft nudge at turn 10+
    elif session.diagnostic_turn >= 10 and session.last_confidence >= 0.8:
        parts.append(
            "\n\n【参考】多くの手順を案内済みです。残りの手順がなければ "
            "provide_answer で最終結論を案内してください。"
        )

    # Retry with different approach
    if session.solutions_tried > 0:
        parts.append(
            f"\n\n【重要】前回の結論ではユーザーの問題が解決しませんでした（{session.solutions_tried}回目）。"
            "次に可能性の高い別の該当事象を探し、手順ガイドモードで案内してください。"
        )

    # ガイドモード指示
    if session.guide_phase == "guiding":
        if user_input == "わからない":
            parts.append(
                "\n\n【重要】ユーザーが前のステップについて「わからない」と回答しました。"
                "同じステップをより分かりやすく、具体的な場所や見た目の特徴を含めて再説明してください。"
                "新しいステップに進まないでください。"
            )
        else:
            parts.append(
                "\n\n【手順ガイドモード有効】マニュアルの対処手順を1ステップずつ "
                "ask_question で案内してください。"
            )
            if session.identified_issue:
                parts.append(f"特定済みの事象: {session.identified_issue[:100]}")

    # 重複防止: 過去の質問をプロンプトに含める
    if session.last_questions:
        recent_qs = session.last_questions[-6:]  # 直近6件
        qs_text = "\n".join(f"- {q}" for q in recent_qs)
        parts.append(
            f"\n\n【既に案内済みの内容（繰り返し禁止）】\n{qs_text}"
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

    # F1: Rewind handler
    if request.rewind_to_turn is not None:
        target_turn = request.rewind_to_turn
        snapshot_entry = None
        snapshot_idx = -1
        for idx, snap in enumerate(session.state_snapshots):
            if snap["turn"] == target_turn:
                snapshot_entry = snap
                snapshot_idx = idx
                break
        if snapshot_entry is not None:
            # Restore state (excluding state_snapshots itself)
            saved = snapshot_entry["state"]
            for key, value in saved.items():
                if key != "state_snapshots":
                    setattr(session, key, value)
            # Remove this and all later snapshots
            session.state_snapshots = session.state_snapshots[:snapshot_idx]
            # Return last assistant message from conversation_history
            last_msg = ""
            for entry in reversed(session.conversation_history):
                if entry["role"] == "assistant":
                    last_msg = entry["content"]
                    break
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DIAGNOSING.value,
                prompt=PromptInfo(type="text", message=last_msg or "やり直しました。症状について教えてください。"),
                manual_coverage=session.manual_coverage,
                diagnostic_turn=session.diagnostic_turn,
                rewound_to_turn=target_turn,
            )
        else:
            logger.warning(f"Rewind target turn {target_turn} not found in snapshots")

    # Handle "resolved" action from provide_answer step
    if request.action == "resolved":
        if request.action_value == "yes":
            # 後方互換（既存セッション用）
            session.current_step = ChatStep.DONE
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DONE.value,
                prompt=PromptInfo(
                    type="text",
                    message="お役に立てて良かったです！他にご質問があれば、新しい問診を開始してください。\n安全運転をお願いいたします。",
                ),
                manual_coverage=session.manual_coverage,
                diagnostic_turn=session.diagnostic_turn,
            )
        elif request.action_value == "no":
            # 後方互換
            session.solutions_tried += 1
            session.guide_phase = "identifying"
            # 3回解決策を試しても解決しない場合 → 専門家へ
            if session.solutions_tried >= 3:
                session.current_step = ChatStep.URGENCY_CHECK
                from app.chat_flow.step_urgency import handle_urgency_check
                return await handle_urgency_check(session, request)
            # まだ別の解決策を試す → DIAGNOSING に留まり次の策を提示
            request.message = "解決しませんでした。他の原因を教えてください。"
            return await handle_diagnosing(session, request)
        elif request.action_value == "book":
            # 後方互換: 「点検を予約する」を直接選択
            session.current_step = ChatStep.RESERVATION
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)
        elif request.action_value == "guide_start":
            session.guide_phase = "guiding"
            request.message = f"「{session.identified_issue[:80]}」の解決手順を教えてください"
            return await handle_diagnosing(session, request)
        elif request.action_value and request.action_value.startswith("followup_"):
            # 動的選択肢: ユーザーの選択テキストを次の入力として処理
            selected_label = request.message or request.action_value
            # 予約系キーワード検出
            if any(kw in selected_label for kw in ["予約", "ディーラー", "持ち込", "ロードサービス"]):
                session.current_step = ChatStep.RESERVATION
                from app.chat_flow.step_reservation import handle_reservation
                return await handle_reservation(session, request)
            # 解決系キーワード検出
            if any(kw in selected_label for kw in ["理解しました", "解決", "試してみ"]):
                session.current_step = ChatStep.DONE
                return ChatResponse(
                    session_id=session.session_id,
                    current_step=ChatStep.DONE.value,
                    prompt=PromptInfo(
                        type="text",
                        message="お役に立てて良かったです！安全運転をお願いいたします。",
                    ),
                    manual_coverage=session.manual_coverage,
                    diagnostic_turn=session.diagnostic_turn,
                )
            # その他 → 追加質問として DIAGNOSING 続行
            request.message = selected_label
            return await handle_diagnosing(session, request)
        else:
            # null choices で provide_answer → 自動的に DONE
            session.current_step = ChatStep.DONE
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DONE.value,
                prompt=PromptInfo(type="text", message="ご利用ありがとうございました。安全運転をお願いいたします。"),
                manual_coverage=session.manual_coverage,
                diagnostic_turn=session.diagnostic_turn,
            )

    if not user_input:
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DIAGNOSING.value,
            prompt=PromptInfo(
                type="text",
                message="症状について教えてください。",
            ),
            manual_coverage=session.manual_coverage,
            diagnostic_turn=session.diagnostic_turn,
        )

    # ---------------------------------------------------------------
    # 1. Save user input + diagnostic_turn++
    # ---------------------------------------------------------------
    session.collected_symptoms.append(user_input)
    session.conversation_history.append({"role": "user", "content": user_input})
    session.diagnostic_turn += 1

    # F1: Save snapshot after turn increment
    snapshot = session.model_dump(exclude={"state_snapshots"})
    session.state_snapshots.append({"turn": session.diagnostic_turn, "state": snapshot})
    if len(session.state_snapshots) > session.max_diagnostic_turns:
        session.state_snapshots = session.state_snapshots[-session.max_diagnostic_turns:]

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
            diagnostic_turn=session.diagnostic_turn,
        )

    await _maybe_summarize(session, provider)

    # 5. ステップバイステップ案内のため候補トリガーは不要
    # provide_answer は LLM の confidence 判断 + max_turns 制限で制御
    candidates_just_triggered = False

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
            manual_coverage=session.manual_coverage,
            diagnostic_turn=session.diagnostic_turn,
        )

    action = result.get("action", "ask_question")
    message = result.get("message", "")
    urgency_flag = result.get("urgency_flag", "none")
    reasoning = result.get("reasoning", "")
    choices = result.get("choices")
    can_drive_llm: bool | None = result.get("can_drive")

    # 8. Save rewritten_query, confidence, and manual_coverage
    session.rewritten_query = result.get("rewritten_query", "")
    session.last_confidence = result.get("confidence_to_answer", 0.0)
    question_topic = result.get("question_topic", "")

    # F3: manual_coverage
    manual_coverage = result.get("manual_coverage", "covered")
    session.manual_coverage = manual_coverage

    # F2: visit_urgency
    visit_urgency_llm = result.get("visit_urgency")
    if visit_urgency_llm:
        session.visit_urgency = visit_urgency_llm

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
    # 8c. マルチステップダンプガード: ask_question に番号付きリストが含まれていたらリトライ
    # ---------------------------------------------------------------
    if action == "ask_question" and _MULTI_STEP_PATTERN.search(message):
        logger.warning(f"Multi-step dump in ask_question, retrying: {message[:80]!r}")
        retry_prompt = (
            diagnostic_prompt
            + "\n\n【重要】ask_question には1つの物理的アクションのみ記載してください。"
            "複数の手順を番号付きで列挙しないでください。"
            "最初に行うべき1ステップだけを案内してください。"
        )
        try:
            result = await _llm_call(provider, retry_prompt)
            action = result.get("action", "ask_question")
            message = result.get("message", message)
            urgency_flag = result.get("urgency_flag", urgency_flag)
            choices = result.get("choices")
            can_drive_llm = result.get("can_drive", can_drive_llm)
            session.rewritten_query = result.get("rewritten_query", session.rewritten_query)
            session.last_confidence = result.get("confidence_to_answer", session.last_confidence)
            question_topic = result.get("question_topic", "")
        except Exception as e:
            logger.warning(f"Multi-step guard re-call failed: {e}")
            lines = [l for l in message.split("\n") if l.strip()]
            if lines:
                message = lines[0]

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

    # 9b. F3: not_covered urgency bump
    if manual_coverage == "not_covered" and urgency_flag in ("none", "low"):
        urgency_flag = "medium"

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
            manual_coverage=session.manual_coverage,
        )

    # ---------------------------------------------------------------
    # 10b. provide_answer フェーズ遷移ロジック
    # ---------------------------------------------------------------
    if action == "provide_answer" and session.guide_phase == "identifying":
        if session.diagnostic_turn <= 1 and session.last_confidence < 0.5:
            # Turn 1で情報不足 → ask_question にリトライ
            logger.warning(
                f"Early provide_answer blocked (confidence={session.last_confidence:.2f}, "
                f"turn={session.diagnostic_turn})"
            )
            retry_prompt = (
                diagnostic_prompt
                + "\n\n【重要】まだ情報が不足しています。"
                "マニュアルの該当事象を絞り込むための確認を ask_question で行ってください。"
            )
            try:
                result = await _llm_call(provider, retry_prompt)
                action = result.get("action", "ask_question")
                message = result.get("message", message)
                urgency_flag = result.get("urgency_flag", urgency_flag)
                choices = result.get("choices")
                can_drive_llm = result.get("can_drive", can_drive_llm)
                session.rewritten_query = result.get("rewritten_query", session.rewritten_query)
                session.last_confidence = result.get("confidence_to_answer", session.last_confidence)
                question_topic = result.get("question_topic", "")
            except Exception as e:
                logger.warning(f"Early provide_answer guard re-call failed: {e}")
        else:
            # 事象特定 → 遷移選択肢へ
            session.identified_issue = message
            session.guide_phase = "guide_offered"

    if action == "provide_answer":
        # F3: manual_coverage warnings
        if manual_coverage == "not_covered":
            message += "\n\n⚠️ マニュアルに記載のない症状のため、ディーラーでの点検を推奨します。"
        elif manual_coverage == "partially_covered":
            message += "\n\nℹ️ マニュアルに完全一致する情報はありません。上記は一般的な知識に基づく回答です。"

        # guide_offered → ハードコード遷移選択肢（high/criticalより先に判定）
        if session.guide_phase == "guide_offered":
            session.rag_answer = message
            session.conversation_history.append({"role": "assistant", "content": message})
            transition_choices = [
                {"value": "guide_start", "label": "解決手順を教えてください"},
                {"value": "yes", "label": "解決しました"},
                {"value": "no", "label": "試してみたが解決しなかった"},
            ]
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DIAGNOSING.value,
                prompt=PromptInfo(
                    type="single_choice",
                    message=message,
                    choices=transition_choices,
                ),
                rag_sources=rag_sources,
                manual_coverage=session.manual_coverage,
                diagnostic_turn=session.diagnostic_turn,
            )

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
                manual_coverage=session.manual_coverage,
                diagnostic_turn=session.diagnostic_turn,
            )

        # guiding or fallback → LLM生成の動的選択肢（最終結論）
        llm_choices = result.get("choices")
        if llm_choices:
            # LLMが生成した選択肢を使用
            dynamic_choices = [{"value": f"followup_{i}", "label": c} for i, c in enumerate(llm_choices)]
            prompt_type = "single_choice"
        else:
            # choicesがnull → 最終回答、会話終了
            dynamic_choices = None
            prompt_type = "text"
            session.current_step = ChatStep.DONE

        return ChatResponse(
            session_id=session.session_id,
            current_step=session.current_step.value if hasattr(session.current_step, 'value') else session.current_step,
            prompt=PromptInfo(
                type=prompt_type,
                message=message,
                choices=dynamic_choices,
            ),
            rag_sources=rag_sources,
            manual_coverage=session.manual_coverage,
            diagnostic_turn=session.diagnostic_turn,
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
            manual_coverage=session.manual_coverage,
        )

    # ---------------------------------------------------------------
    # 12. ask_question — duplicate guard (lightweight)
    # ---------------------------------------------------------------
    if _is_duplicate_question(message, session.last_questions):
        logger.warning(f"Duplicate question detected, replacing: {message!r}")
        message = "他に気になる症状や状況があれば教えてください。"

    # A) 「わからない」「自由入力」を末尾に必ず追加
    choices_for_prompt = _append_default_choices(choices)
    choices_for_prompt = _attach_icons(choices_for_prompt, question_topic)

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
        manual_coverage=session.manual_coverage,
    )
