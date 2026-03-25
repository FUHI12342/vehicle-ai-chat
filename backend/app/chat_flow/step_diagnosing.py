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
from app.utils.fabrication_patterns import detect_fabrications

logger = logging.getLogger(__name__)

# Task 2: 待ちメッセージ検出パターン
_WAITING_PATTERN = re.compile(r"まとめ|整理|お待ち|確認.{0,5}させ|少々", re.UNICODE)

# マルチステップダンプ検出パターン（番号付きリストが2行以上）
_MULTI_STEP_PATTERN = re.compile(r"(?:\d+[.、）]\s.*\n){2,}", re.UNICODE)

# Fix 2: 捏造検出は共通ライブラリ (app.utils.fabrication_patterns) に統合済み


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


def _count_procedure_steps(rag_sources: list[RAGSource]) -> int:
    """RAGソースの中から procedure/troubleshooting チャンクの手順数を推定する。

    content_type が 'procedure' または 'troubleshooting' のチャンクに含まれる
    番号付きリスト行をカウントして、対処手順の総数を推定する。
    """
    step_count = 0
    for source in rag_sources:
        if source.content_type in ("procedure", "troubleshooting"):
            # 番号付きリスト or 箇条書きをカウント
            lines = source.content.split("\n")
            for line in lines:
                stripped = line.strip()
                if re.match(r"^\d+[.、）]", stripped) or stripped.startswith("- "):
                    step_count += 1
    return step_count


def _extract_procedure_steps(rag_sources: list[RAGSource]) -> list[str]:
    """RAGソースから番号付き手順行を抽出する。ガイドモードで使用。"""
    steps: list[str] = []
    for source in rag_sources:
        if source.content_type in ("procedure", "troubleshooting"):
            for line in source.content.split("\n"):
                stripped = line.strip()
                if re.match(r"^\d+[.、）]", stripped) or stripped.startswith("- "):
                    # 番号を除去して本文だけ取得
                    text = re.sub(r"^[\d.、）\-\s]+", "", stripped).strip()
                    if text and text not in steps:
                        steps.append(text)
    return steps


def _format_guide_step_message(step_text: str) -> str:
    """RAGの手順テキストを自然な日本語の指示文に整形する。
    OCR由来のテキストは動詞の連用形で途切れることがあるため、
    機械的に「してください」を付加せず文法に応じた整形を行う。
    """
    text = step_text.rstrip("。、,. \t")

    # 既に完全な指示文（〜ください）
    if text.endswith("ください"):
        return f"{text}。完了しましたか？"

    # て/で形 → 「ください」を付加
    if text.endswith("て") or text.endswith("で"):
        return f"{text}ください。完了しましたか？"

    # 連用形「し」: particle+し, カタカナ語+し(セットし等), 漢語+し(確認し等)
    if re.search(r'[\u3092\u306B\u3068\u30A0-\u30FF\u4E00-\u9FFF]し$', text):
        return f"{text}てください。完了しましたか？"

    # その他（辞書形「差し込む」、連用形「巻き」等）→ 引用形式で安全に表示
    return f"次の操作を行ってください：\n「{text}」\n\n完了しましたか？"


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


def _is_repeated_response(message: str, conversation_history: list[dict]) -> bool:
    """直近3件のアシスタント応答と内容が類似しているか判定"""
    recent_assistant = [
        e["content"] for e in conversation_history[-6:]
        if e["role"] == "assistant"
    ][-3:]
    norm_new = _normalize_question(message)
    for prev in recent_assistant:
        norm_prev = _normalize_question(prev)
        if not norm_prev or not norm_new:
            continue
        if norm_new == norm_prev:
            return True
        shorter, longer = sorted([norm_new, norm_prev], key=len)
        if len(shorter) >= 10 and shorter in longer:
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


def _record_diagnostic_path(session: SessionState, user_input: str) -> None:
    """Record the diagnostic decision path (last AI question + user answer).

    When the user's answer indicates a branch decision (e.g. choosing between
    diagnostic conditions), record the branch as well.
    """
    # Find the last assistant message (the question that was asked)
    last_q = ""
    for entry in reversed(session.conversation_history):
        if entry["role"] == "assistant":
            last_q = entry["content"][:80]
            break

    if not last_q:
        return

    entry = {"q": last_q, "a": user_input[:50]}

    # Detect branch decisions from the answer
    answer_lower = user_input.lower()
    if "正常" in answer_lower and ("回る" in answer_lower or "回" in answer_lower):
        entry["branch"] = "スターター正常→始動手順/イモビ/燃料/ヒューズ確認"
    elif "回らない" in answer_lower or "回転しない" in answer_lower:
        entry["branch"] = "スターター不良→室内灯/バッテリー確認"
    elif "暗い" in answer_lower or "点灯しない" in answer_lower:
        entry["branch"] = "室内灯暗い→バッテリー上がり"
    elif "問題ない" in answer_lower or "明るさに問題" in answer_lower:
        entry["branch"] = "室内灯正常→ヒューズ確認"

    session.diagnostic_path.append(entry)
    # Keep only the last 8 entries
    if len(session.diagnostic_path) > 8:
        session.diagnostic_path = session.diagnostic_path[-8:]


def _build_additional_instructions(
    session: SessionState,
    user_input: str,
    candidates_just_triggered: bool,
    rag_sources: list[RAGSource] | None = None,
) -> str:
    """条件付き指示を一括構築して返す。"""
    parts: list[str] = []

    # Fix 1: Critical safety pending — 安全手順を先に案内
    if session.critical_safety_pending:
        symptom = (session.symptom_text or "").lower()
        is_fire = any(kw in symptom for kw in ("火", "燃", "煙", "焦げ"))
        if is_fire:
            parts.append(
                "\n\n【緊急・火災】この症状は火災の兆候です。"
                "以下の順序で案内してください:\n"
                "1. 「直ちに車両から離れてください（車外に避難）」と伝える\n"
                "2. 「119番に通報してください」と伝える\n"
                "3. action: \"escalate\" でロードサービス/販売店連絡を案内する\n"
                "消火手順を案内してはいけません。一般知識で手順を補完しないこと。"
            )
        elif not session.can_drive:
            # Phase 2-2: critical + 走行不能でもマニュアル手順があれば全案内
            parts.append(
                "\n\n【緊急・走行不能】この症状はcriticalレベルかつ走行不能と判定されています。"
                "以下の順序で案内してください:\n"
                "1. まず「安全な場所に停車してください」と伝える\n"
                "2. マニュアルに該当する対処手順があれば全ステップを1つずつ案内する\n"
                "3. 全手順完了後、またはマニュアルに手順がない場合は action: \"escalate\" で販売店連絡を案内する\n"
                "一般知識で手順を補完しないこと。マニュアルの記載のみ使用すること。"
            )
        else:
            # Phase 2-2: critical + 走行可能の場合は全手順案内
            parts.append(
                "\n\n【緊急・走行可能】この症状はcriticalレベルですが走行可能と判定されています。"
                "安全確認を行いつつ、マニュアルの対処手順を全ステップ案内してください。\n"
                "全手順完了後に provide_answer で最終結論を案内し、ディーラー点検を推奨してください。\n"
                "一般知識で手順を補完しないこと。マニュアルの記載のみ使用すること。"
            )

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
        guide_turns = session.diagnostic_turn - session.guide_start_turn

        # RAGから手順リストを抽出
        procedure_steps = _extract_procedure_steps(rag_sources or [])
        current_step_idx = guide_turns  # 0-indexed: guide_turn 0 = step 1

        if guide_turns >= 4 and guide_turns >= session.guide_turn_limit - 1:
            parts.append(
                "\n\n【重要】手順案内が完了段階です。\n"
                "provide_answer で「手順は以上です。セレクトレバーは動くようになりましたか？」と案内してください。\n"
                "choices: [\"解決しました\", \"まだ動かない\"] にしてください。\n"
                "手順で問題が解決した場合、ディーラー来店を推奨しないこと。\n"
                "urgency_flag は実際の危険度に基づいて設定すること（手順で解決可能なら low）。"
            )
        elif user_input == "わからない":
            parts.append(
                "\n\n【重要】ユーザーが前のステップについて「わからない」と回答しました。"
                "同じステップをより分かりやすく、具体的な場所や見た目の特徴を含めて再説明してください。"
                "新しいステップに進まないでください。"
            )
        else:
            # 手順リストとステップ番号を明示
            steps_text = ""
            if procedure_steps:
                numbered = [f"  {i+1}. {s}" for i, s in enumerate(procedure_steps)]
                steps_text = "\n".join(numbered)

            step_instruction = ""
            if procedure_steps and current_step_idx < len(procedure_steps):
                target = procedure_steps[current_step_idx]
                step_instruction = (
                    f"\n今回案内すべきステップ: ステップ{current_step_idx + 1}「{target}」\n"
                    f"このステップだけを案内してください。他のステップには触れないこと。"
                )
            elif procedure_steps and current_step_idx >= len(procedure_steps):
                step_instruction = (
                    "\n全ステップの案内が完了しました。"
                    "provide_answer で「手順は以上です。問題は解決しましたか？」と案内してください。"
                    "\nchoices: [\"解決しました\", \"まだ解決しない\"] にしてください。"
                )

            parts.append(
                "\n\n【手順ガイドモード】\n"
                "あなたは今、マニュアルの対処手順を1ステップずつユーザーに案内しています。\n"
                "ルール:\n"
                "- action: \"ask_question\" を使うこと（provide_answer は全ステップ完了まで禁止）\n"
                "- 1回のメッセージで案内するのは1つの物理的アクションだけ\n"
                "- message: 「〜してください。完了しましたか？」の形式\n"
                "- choices: そのアクションの結果（例: [\"できました\", \"うまくいかない\"]）\n"
                "- 要約や概要は不要。具体的な指示だけ伝えること\n"
            )
            if steps_text:
                parts.append(f"\n【マニュアルの手順リスト】\n{steps_text}")
            if step_instruction:
                parts.append(step_instruction)
            if session.identified_issue:
                parts.append(f"\n特定済みの事象: {session.identified_issue[:100]}")

    # 重複防止: 過去の質問をプロンプトに含める
    if session.last_questions:
        recent_qs = session.last_questions[-6:]  # 直近6件
        qs_text = "\n".join(f"- {q}" for q in recent_qs)
        parts.append(
            f"\n\n【既に案内済みの内容（繰り返し禁止）】\n{qs_text}"
        )

    # 診断経路: 確定した分岐情報を注入（LLMが分岐を忘れないように）
    if session.diagnostic_path:
        path_lines = []
        for entry in session.diagnostic_path[-5:]:  # 直近5件
            path_lines.append(f"- Q: {entry.get('q', '')} → A: {entry.get('a', '')}")
            if entry.get("branch"):
                path_lines.append(f"  → 確定分岐: {entry['branch']}")
        parts.append(
            f"\n\n【診断経路（確定済み、変更不可）】\n" + "\n".join(path_lines)
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


def _unwrap_schema_response(result: dict) -> dict:
    """Fix for Claude Haiku returning JSON schema with values instead of flat JSON.

    When the prompt is long, Haiku sometimes outputs:
        {"type": "object", "properties": {"action": "ask_question", "message": "..."}}
    instead of:
        {"action": "ask_question", "message": "..."}
    """
    if "properties" in result and "type" in result and not result.get("message"):
        props = result["properties"]
        # Check if properties contain actual values (strings) rather than schema definitions
        if isinstance(props.get("action"), str) and isinstance(props.get("message"), str):
            logger.warning("Unwrapping schema-like LLM response into flat JSON")
            return props
    return result


async def _llm_call(provider, diagnostic_prompt: str, max_retries: int = 2) -> dict:
    """Call LLM with DIAGNOSTIC_SCHEMA and return parsed JSON.

    Retries once if the LLM returns an empty/incomplete response (common with
    Claude Haiku on Bedrock when the prompt is long).
    Falls back to a simplified prompt if all retries fail.
    """
    for attempt in range(max_retries):
        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": diagnostic_prompt},
                ],
                temperature=0.15,
                response_format={"type": "json_schema", "json_schema": DIAGNOSTIC_SCHEMA},
            )
            raw = response.content
            result = json.loads(raw)
            # Fix: Claude Haiku sometimes returns the schema itself with values
            # embedded under "properties" instead of a flat JSON object
            result = _unwrap_schema_response(result)
            if result.get("message"):
                return result
            logger.warning(
                "LLM returned empty message (attempt %d/%d). Raw: %s",
                attempt + 1, max_retries, raw[:500],
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(
                "LLM returned invalid JSON (attempt %d/%d): %s. Raw: %s",
                attempt + 1, max_retries, e, raw[:200] if 'raw' in dir() else "N/A",
            )

    # All retries failed — try with a shorter prompt (no RAG context)
    logger.warning("All LLM retries returned empty, trying shortened prompt")
    try:
        # Remove the RAG context section to shorten the prompt
        short_prompt = diagnostic_prompt
        rag_marker = "【マニュアル関連情報】"
        next_marker = "【最優先ルール】"
        if rag_marker in short_prompt and next_marker in short_prompt:
            rag_start = short_prompt.index(rag_marker)
            rag_end = short_prompt.index(next_marker)
            short_prompt = (
                short_prompt[:rag_start]
                + "【マニュアル関連情報】\n(情報量が多いため省略。症状に基づいて質問を続けてください)\n\n"
                + short_prompt[rag_end:]
            )
        response = await provider.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": short_prompt},
            ],
            temperature=0.15,
            response_format={"type": "json_schema", "json_schema": DIAGNOSTIC_SCHEMA},
        )
        result = json.loads(response.content)
        result = _unwrap_schema_response(result)
        if result.get("message"):
            logger.info("Shortened prompt succeeded")
            return result
    except Exception as e:
        logger.warning("Shortened prompt also failed: %s", e)

    # Ultimate fallback
    return {
        "action": "ask_question",
        "message": "他に気になる症状や状況があれば教えてください。",
        "choices": None,
        "manual_coverage": "partially_covered",
        "urgency_flag": "none",
    }


def _validate_manual_coverage(
    llm_claimed: str,
    rag_sources: list[RAGSource],
) -> str:
    """LLMの自己申告coverage値をRAGスコアで外部検証する。

    - RAGソースなし → not_covered（LLMの判断を信頼しない）
    - max_score < 0.55 → not_covered（関連度が低すぎる）
    - max_score < 0.70 → partially_covered（中間的）
    - content_type に troubleshooting/procedure がない → partially_covered 上限
    - それ以外 → LLMの判断を信頼
    """
    if not rag_sources:
        if llm_claimed == "covered":
            logger.info("No RAG sources but LLM claims covered — overriding to not_covered")
            return "not_covered"
        return llm_claimed

    max_score = max(s.score for s in rag_sources)

    # content_type チェック: troubleshooting/procedure がない場合は対処法なし
    content_types = [s.content_type for s in rag_sources if s.content_type]
    has_actionable = (
        not content_types  # content_type 未設定ならこのチェックをスキップ
        or any(ct in ("troubleshooting", "procedure") for ct in content_types)
    )

    if max_score < 0.55 and llm_claimed == "covered":
        logger.info("RAG max_score=%.2f < 0.55 — overriding covered to not_covered", max_score)
        return "not_covered"
    if max_score < 0.70 and llm_claimed == "covered":
        logger.info("RAG max_score=%.2f < 0.70 — overriding covered to partially_covered", max_score)
        return "partially_covered"

    # High score but no actionable content → cap at partially_covered
    if llm_claimed == "covered" and not has_actionable:
        logger.info(
            "No troubleshooting/procedure content_type — overriding covered to partially_covered"
        )
        return "partially_covered"

    # Upgrade: LLM claims not_covered but RAG has high-score actionable content
    # LLMの過小申告を補正（RAGに根拠があるのに見落としている場合）
    if llm_claimed == "not_covered" and max_score >= 0.70 and has_actionable:
        logger.info(
            "RAG has high-score actionable content (max=%.2f) but LLM claims not_covered "
            "— upgrading to partially_covered",
            max_score,
        )
        return "partially_covered"

    # Upgrade: LLM claims partially_covered but RAG has very high-score actionable content
    # Claude Haiku on Bedrock is more conservative than GPT-4o about claiming covered
    if llm_claimed == "partially_covered" and max_score >= 0.80 and has_actionable:
        logger.info(
            "RAG has high-score actionable content (max=%.2f) and LLM claims partially_covered "
            "— upgrading to covered",
            max_score,
        )
        return "covered"

    return llm_claimed


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

    # Handle guide_start from any action type (select_choice or resolved)
    if request.action_value == "guide_start":
        session.guide_phase = "guiding"
        session.guide_start_turn = session.diagnostic_turn
        request.message = f"「{session.identified_issue[:80]}」の解決手順を教えてください"
        request.action = None
        request.action_value = None
        return await handle_diagnosing(session, request)

    # Handle guide completion resolution choices
    if request.action_value == "resolved_yes":
        session.current_step = ChatStep.DONE
        return ChatResponse(
            session_id=session.session_id,
            current_step=ChatStep.DONE.value,
            prompt=PromptInfo(
                type="text",
                message="問題が解決して良かったです！\n他にご質問があれば、新しい問診を開始してください。\n安全運転をお願いいたします。",
            ),
            manual_coverage=session.manual_coverage,
            diagnostic_turn=session.diagnostic_turn,
        )
    if request.action_value in ("resolved_no", "dealer"):
        session.guide_phase = "identifying"
        session.current_step = ChatStep.RESERVATION
        session.urgency_level = session.urgency_level or "low"
        session.can_drive = session.urgency_level != "critical"
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

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
            request.action = None
            request.action_value = None
            return await handle_diagnosing(session, request)
        elif request.action_value == "book":
            # 後方互換: 「点検を予約する」を直接選択
            session.current_step = ChatStep.RESERVATION
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)
        elif request.action_value and request.action_value.startswith("followup_"):
            # 動的選択肢: ユーザーの選択テキストを次の入力として処理
            selected_label = request.message or request.action_value
            # 予約系キーワード検出
            # Fix v2: ガイドモード完了後（guiding）の場合、provide_answer結論として
            # DONEに遷移する（手順案内済みなので reservation ではなく完了扱い）
            _is_dealer_intent = any(kw in selected_label for kw in ["予約", "ディーラー", "持ち込", "ロードサービス"])
            if _is_dealer_intent and session.guide_phase == "guiding":
                # ガイド完了後: urgency_check 経由で適切な reservation 導線へ
                session.current_step = ChatStep.URGENCY_CHECK
                from app.chat_flow.step_urgency import handle_urgency_check
                return await handle_urgency_check(session, request)
            elif _is_dealer_intent:
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
            request.action = None
            request.action_value = None
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
    # 0b. Dealer intent detection: user explicitly wants dealer visit
    # ---------------------------------------------------------------
    _DEALER_INTENT_KW = ("ディーラー", "予約", "持ち込", "ロードサービス", "点検に行")
    if (session.diagnostic_turn >= 3
            and session.guide_phase in ("guiding", "guide_offered")
            and any(kw in user_input for kw in _DEALER_INTENT_KW)):
        logger.info("Dealer intent detected in user message: %s", user_input[:40])
        session.conversation_history.append({"role": "user", "content": user_input})
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # ---------------------------------------------------------------
    # 1. Save user input + diagnostic_turn++
    # ---------------------------------------------------------------
    session.collected_symptoms.append(user_input)
    session.conversation_history.append({"role": "user", "content": user_input})
    session.diagnostic_turn += 1

    # Record diagnostic path: pair last AI question with user's answer
    _record_diagnostic_path(session, user_input)

    # F1: Save snapshot after turn increment
    snapshot = session.model_dump(exclude={"state_snapshots"})
    session.state_snapshots.append({"turn": session.diagnostic_turn, "state": snapshot})
    if len(session.state_snapshots) > session.max_diagnostic_turns:
        session.state_snapshots = session.state_snapshots[-session.max_diagnostic_turns:]

    # 2. Keyword-based urgency check (set flag, don't skip safety steps)
    all_symptoms = " ".join(session.collected_symptoms)
    keyword_result = keyword_urgency_check(all_symptoms)
    if keyword_result and keyword_result["level"] == "critical":
        session.urgency_level = "critical"
        session.can_drive = False
        session.critical_safety_pending = True

    # 2b. Phase 2-2: Critical safety auto-escalate only when can_drive=false
    #     ガイドモード中はマニュアル手順の案内を続行させる
    #     turn 6まで猶予を与えてguide mode進入の時間を確保
    if (session.critical_safety_pending
            and session.diagnostic_turn >= 6
            and not session.can_drive
            and session.guide_phase != "guiding"):
        session.current_step = ChatStep.RESERVATION
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # 3. RAG query: use rewritten_query if available, otherwise all_symptoms
    rag_query = session.rewritten_query if session.rewritten_query else all_symptoms
    rag_context = "関連するマニュアル情報はありません。"
    rag_sources: list[RAGSource] = []
    logger.info(
        "DIAG[%s] turn=%d vehicle=%s rag_query='%s'",
        session.session_id[:8], session.diagnostic_turn,
        session.vehicle_id, rag_query[:80],
    )
    try:
        results = await rag_service.query(
            symptom=rag_query,
            vehicle_id=session.vehicle_id,
            make=session.vehicle_make or "",
            model=session.vehicle_model or "",
            year=session.vehicle_year or 0,
            n_results=10,
        )
        logger.info(
            "DIAG[%s] RAG returned %d sources",
            session.session_id[:8], len(results["sources"]),
        )
        if results["sources"]:
            # 生チャンクを直接プロンプトに注入（LLM要約を経由しない）
            rag_context = "\n\n---\n\n".join(
                f"【{s['section'] or 'マニュアル'}（p.{s['page']}）】スコア:{s['score']:.2f}\n{s['content']}"
                for s in results["sources"]
            )
            rag_sources = [
                RAGSource(
                    content=s["content"],
                    page=s["page"],
                    section=s["section"],
                    score=s["score"],
                    content_type=s.get("content_type", ""),
                )
                for s in results["sources"]
            ]
    except Exception as e:
        logger.warning(f"RAG query failed: {e}")

    # 3b. Phase 2-3: 事前coverage判定 — RAGスコアでnot_coveredを検出し、
    #     LLMへ渡す前にRAGコンテキストを除去して一般知識回答を防ぐ
    pre_coverage = _validate_manual_coverage("covered", rag_sources)
    if pre_coverage == "not_covered":
        logger.info("Pre-LLM coverage check: not_covered — replacing RAG context")
        rag_context = "関連するマニュアル情報はありません。"
        # Pre-LLM bypass: turn >= 3 + not_covered → skip LLM, escalate directly
        # ターン1-2は質問を許可（rewritten_queryでRAG再検索のチャンスを与える）
        if session.diagnostic_turn >= 3:
            logger.info(
                "Pre-LLM not_covered bypass: escalating at turn %d",
                session.diagnostic_turn,
            )
            session.not_covered_count += 1
            session.manual_coverage = "not_covered"
            session.current_step = ChatStep.RESERVATION
            msg = (
                "マニュアルに該当する記載が見つかりませんでした。"
                "Honda販売店またはディーラーでの点検をお勧めします。"
            )
            session.conversation_history.append(
                {"role": "assistant", "content": msg}
            )
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)

    # 3c. partially_covered + no actionable content → turn >= 3 で bypass
    if (pre_coverage == "partially_covered"
            and session.diagnostic_turn >= 3
            and not session.guide_phase == "guiding"):
        # content_type が設定されている場合のみチェック
        content_types = [s.content_type for s in rag_sources if s.content_type]
        has_actionable = (
            not content_types  # content_type未設定ならスキップ
            or any(ct in ("troubleshooting", "procedure") for ct in content_types)
        )
        if not has_actionable:
            logger.info(
                "Pre-LLM partially_covered bypass: no actionable content at turn %d",
                session.diagnostic_turn,
            )
            session.manual_coverage = "not_covered"
            session.current_step = ChatStep.RESERVATION
            msg = (
                "お伺いした症状についてマニュアルに明確な対処方法が見つかりませんでした。"
                "Honda販売店またはディーラーでの点検をお勧めします。"
            )
            session.conversation_history.append(
                {"role": "assistant", "content": msg}
            )
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)

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
    additional_instructions = _build_additional_instructions(session, user_input, candidates_just_triggered, rag_sources)

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
    logger.info(
        "DIAG[%s] LLM action=%s coverage=%s msg='%s' choices=%s",
        session.session_id[:8], action,
        result.get("manual_coverage", "?"), message[:60],
        choices,
    )

    # Fix: Hard enforce provide_answer at max turns
    if session.diagnostic_turn >= session.max_diagnostic_turns and action == "ask_question":
        logger.warning("Max turns reached but LLM returned ask_question, forcing provide_answer")
        action = "provide_answer"

    # Phase 2-1: guide mode dynamic turn limit based on procedure step count
    if (session.guide_phase == "guiding"
            and session.guide_start_turn > 0):
        estimated_steps = _count_procedure_steps(rag_sources)
        guide_turn_limit = max(5, min(estimated_steps + 2, 10))
        session.guide_turn_limit = guide_turn_limit
        guide_turns = session.diagnostic_turn - session.guide_start_turn

        if action == "ask_question" and guide_turns >= guide_turn_limit:
            logger.warning(
                "Guide mode dynamic limit: forcing provide_answer "
                "(guide_turns=%d, limit=%d, estimated_steps=%d)",
                guide_turns, guide_turn_limit, estimated_steps,
            )
            action = "provide_answer"

        # Guard: guiding中のprovide_answerをブロック
        # guide_turn_limit未満では手順が完了していないはずなので、ask_questionに強制
        # ただしユーザーが明確に解決を報告した場合は許可
        # ガイドモード中の「できました」は手順ステップ完了であり問題解決ではない
        _resolution_keywords = ("動きました", "解決し", "直りました", "治りました")
        _user_resolved = any(kw in user_input for kw in _resolution_keywords)
        if (action == "provide_answer"
                and guide_turns < guide_turn_limit
                and not _user_resolved):
            logger.warning(
                "Guide mode guard: LLM returned provide_answer on guide_turn=%d "
                "(limit=%d), forcing ask_question for step-by-step",
                guide_turns, guide_turn_limit,
            )
            action = "ask_question"
            # LLMが要約を返した場合、RAGから該当ステップを抽出してメッセージを書き換え
            procedure_steps = _extract_procedure_steps(rag_sources)
            step_idx = guide_turns  # 0-indexed
            if procedure_steps and step_idx < len(procedure_steps):
                target_step = procedure_steps[step_idx]
                message = _format_guide_step_message(target_step)
                choices = ["できました", "うまくいかない"]
                logger.info(
                    "Guide guard: rewrote message to step %d: %s",
                    step_idx + 1, target_step,
                )
            elif not choices:
                choices = ["確認しました", "わからない"]

    # 8. Save rewritten_query, confidence, and manual_coverage
    session.rewritten_query = result.get("rewritten_query", "")
    session.last_confidence = result.get("confidence_to_answer", 0.0)
    question_topic = result.get("question_topic", "")

    # F3: manual_coverage — RAGスコアベース検証で上書き
    manual_coverage = _validate_manual_coverage(
        llm_claimed=result.get("manual_coverage", "covered"),
        rag_sources=rag_sources,
    )

    # Fix 2: Fabrication detection — immediately escalate when fabrication patterns found
    # ただし manual_coverage が "covered"（RAG検証済み）の場合はスキップ
    # RAGに該当情報があるなら、LLMの言及は捏造ではなくマニュアル準拠
    if manual_coverage == "covered":
        matched = []
    else:
        matched = detect_fabrications(message)
    fabrication_detected = len(matched) > 0
    if fabrication_detected:
        logger.warning(
            "Fabrication detected in LLM response: patterns=%s, message=%s",
            [m.description for m in matched], message[:80],
        )
        manual_coverage = "not_covered"

    if fabrication_detected:
        session.manual_coverage = "not_covered"
        session.current_step = ChatStep.RESERVATION
        msg = "マニュアルに該当する記載が見つかりませんでした。Honda販売店またはディーラーでの点検をお勧めします。"
        session.conversation_history.append({"role": "assistant", "content": msg})
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    session.manual_coverage = manual_coverage

    # Fix 2: not_covered consecutive detection (non-fabrication case)
    if manual_coverage == "not_covered":
        session.not_covered_count += 1
    else:
        session.not_covered_count = 0

    # Fix A: 1回not_covered + 3ターン以上経過でescalate（ターン1-2は質問許可、rewritten_queryの機会を確保）
    if session.not_covered_count >= 1 and session.diagnostic_turn >= 3:
        session.current_step = ChatStep.RESERVATION
        msg = "マニュアルに該当する記載が見つかりませんでした。Honda販売店またはディーラーでの点検をお勧めします。"
        session.conversation_history.append({"role": "assistant", "content": msg})
        from app.chat_flow.step_reservation import handle_reservation
        return await handle_reservation(session, request)

    # Fix A2 (Phase5-3): identifyingフェーズ強制遷移
    # partially_covered は6ターン、not_covered は4ターンで強制終了
    _id_turn_limit = 4 if manual_coverage == "not_covered" else 6
    if (action == "ask_question"
            and session.diagnostic_turn >= _id_turn_limit
            and session.guide_phase == "identifying"
            and not session.critical_safety_pending):
        if manual_coverage in ("not_covered", "partially_covered"):
            # not_covered/partially → escalate
            logger.info(
                "Identifying phase turn limit: forcing escalate "
                "(turn=%d, coverage=%s)", session.diagnostic_turn, manual_coverage
            )
            session.current_step = ChatStep.RESERVATION
            msg = (
                "お伺いした症状についてマニュアルに明確な対処方法が見つかりませんでした。"
                "Honda販売店またはディーラーでの点検をお勧めします。"
            )
            session.conversation_history.append({"role": "assistant", "content": msg})
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)
        else:
            # covered → provide_answerに昇格して手順ガイドへ
            logger.info(
                "Identifying phase turn limit: promoting to provide_answer "
                "(turn=%d, confidence=%.2f)", session.diagnostic_turn, session.last_confidence
            )
            action = "provide_answer"

    # Fix B: COVERED高信頼度ケースの早期結論
    # manual_coverage==covered かつ confidence>=0.9 かつ 3ターン以上 → ask_question を provide_answer に上書き
    # Fix v2: 閾値を厳格化(0.8→0.9, 2→3ターン)して手順ガイドを優先
    #         guiding中はLLMの判断に任せる（手順完了後に自然にprovide_answerになる）
    if (action == "ask_question"
            and manual_coverage == "covered"
            and session.last_confidence >= 0.9
            and session.diagnostic_turn >= 3
            and session.guide_phase != "guiding"):
        logger.info("High-confidence covered case: overriding ask_question → provide_answer")
        action = "provide_answer"

    # Global soft limit: turn 10+でまだask_questionなら結論を強制
    # provide_answerの繰り返しループも検出してescalate
    if (action == "ask_question"
            and session.diagnostic_turn >= 10
            and not session.critical_safety_pending):
        logger.warning(
            "Global turn-10 soft limit: forcing provide_answer (turn=%d, phase=%s)",
            session.diagnostic_turn, session.guide_phase,
        )
        action = "provide_answer"

    # Phase 2 fix: turn 10+でguiding中のprovide_answerは自然完了を許可
    # （以前はescalateに強制変換していたが、手順完了後はprovide_answerが正しい終了方法）

    # F2: visit_urgency
    visit_urgency_llm = result.get("visit_urgency")
    if visit_urgency_llm:
        session.visit_urgency = visit_urgency_llm

    logger.info(
        f"Diagnostic action={action}, urgency={urgency_flag}, "
        f"confidence={session.last_confidence:.2f}, topic={question_topic!r}, reasoning={reasoning}"
    )

    # Fix 3: Loop detection — 同じ応答の繰り返し検出
    if _is_repeated_response(message, session.conversation_history):
        session.repeated_response_count += 1
        if session.repeated_response_count >= 2:
            session.current_step = ChatStep.RESERVATION
            msg = (
                "同じご案内を繰り返してしまい申し訳ございません。"
                "この症状についてはディーラーでの直接点検をお勧めします。"
            )
            session.conversation_history.append({"role": "assistant", "content": msg})
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)
    else:
        session.repeated_response_count = 0

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
    # Fix 1: Block instant escalation when critical_safety_pending is active
    # guiding中はguide_turn_limitまでescalateをブロック
    _in_guide_range = (
        session.guide_phase == "guiding"
        and session.guide_start_turn > 0
        and (session.diagnostic_turn - session.guide_start_turn) < session.guide_turn_limit
    )
    _block_escalate = (
        (session.critical_safety_pending and session.diagnostic_turn < 4)
        or _in_guide_range
        or (manual_coverage == "covered"
            and session.guide_phase == "identifying"
            and session.diagnostic_turn <= 4)
    )
    if urgency_flag in ("high", "critical"):
        session.urgency_level = urgency_flag
        session.can_drive = can_drive_llm if can_drive_llm is not None else (urgency_flag != "critical")
        if urgency_flag == "critical" and not _block_escalate:
            session.current_step = ChatStep.RESERVATION
            session.conversation_history.append({"role": "assistant", "content": message})
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)

    # 11. Dispatch based on action
    if action == "escalate":
        if _block_escalate:
            if (manual_coverage == "covered"
                    and session.guide_phase == "identifying"
                    and session.diagnostic_turn >= 3):
                # Covered case with enough info → promote to provide_answer for guide entry
                action = "provide_answer"
                message = (
                    "お伺いした症状について、マニュアルに関連する手順が見つかりました。"
                    "ステップごとに確認してみましょう。"
                )
                logger.info(
                    "Blocked escalate for covered case → promoting to provide_answer (turn=%d)",
                    session.diagnostic_turn,
                )
            else:
                # Override: deliver safety message as ask_question instead of escalating
                action = "ask_question"
                if "停車" not in message and "安全な場所" not in message:
                    message = "安全な場所に停車してください。\n\n" + message
                if not choices:
                    choices = ["はい、停車しました", "まだ走行中です"]
                logger.info("Blocked instant escalate for critical_safety_pending (turn=%d)", session.diagnostic_turn)
        elif (manual_coverage in ("covered", "partially_covered")
              and session.guide_phase in ("identifying", "guiding")
              and (
                  session.diagnostic_turn <= 3  # Early turns: always block
                  or _in_guide_range  # Guiding phase: block until guide limit
              )):
            # covered/partially_covered + non-critical → escalateを阻止
            # マニュアルに記載があるケースは手順案内を優先する
            action = "ask_question"
            logger.info(
                "Blocked early escalate for covered case: coverage=%s, phase=%s, turn=%d, in_guide=%s",
                manual_coverage, session.guide_phase, session.diagnostic_turn, _in_guide_range,
            )
        else:
            session.urgency_level = urgency_flag if urgency_flag in ("high", "critical") else (session.urgency_level or urgency_flag or "none")
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
        elif manual_coverage == "not_covered":
            # not_covered でガイドモードに入らない → escalate
            logger.info(
                "Blocking guide_offered for not_covered case (turn=%d)",
                session.diagnostic_turn,
            )
            session.manual_coverage = "not_covered"
            session.current_step = ChatStep.RESERVATION
            msg = (
                "マニュアルに該当する記載が見つかりませんでした。"
                "Honda販売店またはディーラーでの点検をお勧めします。"
            )
            session.conversation_history.append(
                {"role": "assistant", "content": msg}
            )
            from app.chat_flow.step_reservation import handle_reservation
            return await handle_reservation(session, request)
        else:
            # ユーザーが解決を報告している場合は guide_offered をスキップ
            _user_says_resolved = any(
                kw in user_input for kw in ("動きました", "解決し", "直りました", "治りました", "入りました")
            )
            if _user_says_resolved:
                logger.info(
                    "User reported resolution during identifying (turn=%d), skipping guide_offered",
                    session.diagnostic_turn,
                )
                session.conversation_history.append({"role": "assistant", "content": message})
                session.current_step = ChatStep.DONE
                return ChatResponse(
                    session_id=session.session_id,
                    current_step=ChatStep.DONE.value,
                    prompt=PromptInfo(
                        type="text",
                        message=message + "\n\n問題が解決したようですね。他にご質問があれば、新しい問診を開始してください。\n安全運転をお願いいたします。",
                    ),
                    rag_sources=rag_sources,
                    manual_coverage=session.manual_coverage,
                    diagnostic_turn=session.diagnostic_turn,
                )
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
            # LLMの回答に自己対処手順への言及があるかチェック
            # （RAGの_extract_procedure_stepsは無関係ソースの手順も拾うため不正確）
            has_procedure = any(
                kw in message
                for kw in ("手順が記載", "手順に従", "手順として", "操作を行", "解除の手順", "解除穴")
            )
            if has_procedure:
                transition_choices = [
                    {"value": "guide_start", "label": "解決手順を教えてください"},
                    {"value": "yes", "label": "解決しました"},
                    {"value": "no", "label": "試してみたが解決しなかった"},
                ]
            else:
                # 対処手順なし → ディーラー案内中心の選択肢
                transition_choices = [
                    {"value": "dealer", "label": "ディーラーに相談したい"},
                    {"value": "yes", "label": "理解しました"},
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
        # Fix 1: Block when critical_safety_pending is active (safety steps first)
        # Fix Phase5-2: ガイド未開始(identifying)なら手順案内を経由させる
        # Fix: 手順ガイド完了後(guiding)はcriticalのみエスカレート。highは推奨テキストに留める
        # Fix v2: guide_offered もガイド開始前なので escalate しない
        _guide_completed = session.guide_phase == "guiding"
        _should_escalate = (
            urgency_flag == "critical"
            or (urgency_flag == "high" and not _guide_completed)
        )
        if (_should_escalate
                and not _block_escalate
                and session.guide_phase not in ("identifying", "guide_offered")):
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

        # ガイド完了 → 解決確認選択肢（固定）
        if session.guide_phase == "guiding":
            resolution_msg = message + "\n\n手順は以上です。問題は解決しましたか？"
            resolution_choices = [
                {"value": "resolved_yes", "label": "解決しました"},
                {"value": "resolved_no", "label": "解決しなかった"},
                {"value": "dealer", "label": "ディーラーに相談したい"},
            ]
            return ChatResponse(
                session_id=session.session_id,
                current_step=ChatStep.DIAGNOSING.value,
                prompt=PromptInfo(
                    type="single_choice",
                    message=resolution_msg,
                    choices=resolution_choices,
                ),
                rag_sources=rag_sources,
                manual_coverage=session.manual_coverage,
                diagnostic_turn=session.diagnostic_turn,
            )

        # fallback → LLM生成の動的選択肢（最終結論）
        llm_choices = result.get("choices")
        if llm_choices:
            dynamic_choices = [{"value": f"followup_{i}", "label": c} for i, c in enumerate(llm_choices)]
            prompt_type = "single_choice"
        else:
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
            diagnostic_turn=session.diagnostic_turn,
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
        diagnostic_turn=session.diagnostic_turn,
    )
