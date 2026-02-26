"""Structured Outputs JSON Schema definitions for OpenAI response_format."""

# 仕様確認用スキーマ
SPEC_CLASSIFICATION_SCHEMA = {
    "name": "spec_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "required": [
            "is_spec_behavior",
            "confidence",
            "explanation",
            "manual_reference",
            "reasoning",
        ],
        "additionalProperties": False,
        "properties": {
            "is_spec_behavior": {
                "type": "boolean",
                "description": "仕様通りの正常動作かどうか",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "判定の確信度",
            },
            "explanation": {
                "type": "string",
                "description": "ユーザー向け解説（素人向け・200文字以内）",
            },
            "manual_reference": {
                "type": "string",
                "description": "マニュアル参照（例: p.142 アイドリングストップ）",
            },
            "reasoning": {
                "type": "string",
                "description": "内部ログ用の判断理由",
            },
        },
    },
}

# 問診ループ用スキーマ
DIAGNOSTIC_SCHEMA = {
    "name": "diagnostic_response",
    "strict": True,
    "schema": {
        "type": "object",
        "required": ["action", "message", "urgency_flag", "reasoning", "term_to_clarify", "choices", "can_drive", "confidence_to_answer", "rewritten_query", "question_topic"],
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["ask_question", "clarify_term", "provide_answer", "escalate", "spec_answer"],
            },
            "message": {
                "type": "string",
                "description": "ユーザーに表示するメッセージ（質問/回答/確認）",
            },
            "urgency_flag": {
                "type": "string",
                "enum": ["none", "low", "medium", "high", "critical"],
            },
            "reasoning": {
                "type": "string",
                "description": "判断理由（内部ログ用）",
            },
            "term_to_clarify": {
                "type": ["string", "null"],
                "description": "clarify_term時の対象用語",
            },
            "choices": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "ユーザーに提示する選択肢（任意）",
            },
            "can_drive": {
                "type": ["boolean", "null"],
                "description": "走行可能か。判定できない段階は null。迷ったら必ず false（安全側）",
            },
            "confidence_to_answer": {
                "type": "number",
                "description": "回答できる確信度 0.0〜1.0",
            },
            "rewritten_query": {
                "type": "string",
                "description": "次のRAG検索用に改善したクエリ（50文字以内）",
            },
            "question_topic": {
                "type": "string",
                "description": "この質問が扱うトピック（例: 操作感、発生時期、色、温度など）。質問しない場合は空文字",
            },
        },
    },
}

# 緊急度評価用スキーマ
URGENCY_SCHEMA = {
    "name": "urgency_assessment",
    "strict": True,
    "schema": {
        "type": "object",
        "required": ["level", "can_drive", "reasons", "recommendation"],
        "additionalProperties": False,
        "properties": {
            "level": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
            },
            "can_drive": {
                "type": "boolean",
                "description": "走行可能か",
            },
            "reasons": {
                "type": "array",
                "items": {"type": "string"},
            },
            "recommendation": {
                "type": "string",
            },
        },
    },
}
