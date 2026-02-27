# 問診処理フロー 詳細設計書

## 概要

ユーザーが症状を入力してから診断完了（または予約）まで、バックエンド内でどのファイル・関数がどの順に呼ばれるかを記述する。

---

## 1. リクエスト受信〜ステートマシン振り分け

```
ブラウザ (POST /api/chat)
  ↓
frontend/src/hooks/useChat.ts: sendMessage() / sendAction()
  ↓ Next.js rewrite (/api/* → localhost:8000)
backend/app/api/chat.py: chat(req: ChatRequest)
  ↓
backend/app/services/chat_service.py: ChatService.process()
  ↓
backend/app/services/session_store.py: SessionStore.get() or .create()
  ↓
backend/app/chat_flow/state_machine.py: process_step(session, request)
  ↓ session.current_step に基づきハンドラーを選択
  STEP_HANDLERS[session.current_step](session, request)
```

### ファイル別の役割

| ファイル | 責務 |
|---------|------|
| `api/chat.py` | FastAPIルーター。ChatRequest受信→ChatResponse返却。エラーハンドリング |
| `services/chat_service.py` | セッション取得/作成 → ステートマシン呼び出し → セッション更新 |
| `services/session_store.py` | インメモリ辞書ストア。TTL付きセッション管理（create/get/update/delete） |
| `chat_flow/state_machine.py` | ChatStep enum → ハンドラー関数のマッピング。`process_step()` でディスパッチ |

---

## 2. ステートマシン全体図

```
VEHICLE_ID → PHOTO_CONFIRM → FREE_TEXT → SPEC_CHECK → DIAGNOSING → URGENCY_CHECK
                                |              ↓           ↓              ↓
                                |          (仕様確認)   (CRITICAL時)   RESERVATION
                                |              ↓           ↓              ↓
                                |          DIAGNOSING   RESERVATION   BOOKING_INFO
                                |                          ↓              ↓
                                +--- (CRITICAL時) --→ RESERVATION   BOOKING_CONFIRM
                                                                         ↓
                                                                        DONE
```

### 各ステップのハンドラーファイル

| ChatStep | ハンドラー | ファイル |
|----------|-----------|---------|
| `vehicle_id` | `handle_vehicle_id` | `step1_vehicle_id.py` |
| `photo_confirm` | `handle_photo_confirm` | `step2_photo_confirm.py` |
| `free_text` | `handle_free_text` | `step3_free_text.py` |
| `spec_check` | `handle_spec_check` | `step_spec_check.py` |
| `diagnosing` | `handle_diagnosing` | `step_diagnosing.py` |
| `urgency_check` | `handle_urgency_check` | `step_urgency.py` |
| `reservation` | `handle_reservation` | `step_reservation.py` |
| `booking_info` | `handle_booking_info` | `step_reservation.py` |
| `booking_confirm` | `handle_booking_confirm` | `step_reservation.py` |

---

## 3. FREE_TEXT ステップ（症状入力の受付）

**ファイル**: `backend/app/chat_flow/step3_free_text.py`
**関数**: `handle_free_text(session, request)`

```
ユーザー入力 (例: 「セレクトレバーが動かない」)
  ↓
1. session.symptom_text に保存
  ↓
2. keyword_urgency_check(symptom) — ルールベース緊急度判定
   ├→ CRITICAL → session.current_step = RESERVATION → handle_reservation() へ
   └→ それ以外 → 続行
  ↓
3. RAG検索 (_rag_search) — ChromaDB からマニュアル検索
  ↓
4. _should_route_to_spec_check() — 仕様確認パスへ分岐するか判定
   ├→ True → session.current_step = SPEC_CHECK → handle_spec_check() へ
   └→ False → 続行
  ↓
5. _should_hint_spec() — 仕様ヒントフラグ設定（soft threshold）
  ↓
6. session.current_step = DIAGNOSING → handle_diagnosing() へ
```

### 仕様確認ルーティング判定 (`_should_route_to_spec_check`)

安全ゲート（いずれか1つで仕様パスをブロック）:
1. キーワード緊急度が critical/high
2. RAG結果に `has_warning=True` あり
3. danger系 content_type が spec系より多い

仕様パス条件（すべて満たす必要あり）:
- score >= 0.50 の結果が存在
- spec系 content_type (procedure/specification/general) が所定数以上
- spec系比率 >= 50%

---

## 4. DIAGNOSING ステップ（問診ループ — 最重要）

**ファイル**: `backend/app/chat_flow/step_diagnosing.py`
**関数**: `handle_diagnosing(session, request)`

### 全体フロー

```
handle_diagnosing(session, request)
  ↓
┌─ A. Rewind処理（request.rewind_to_turn != None の場合）
│   1. state_snapshots から該当ターンのスナップショットを検索
│   2. セッション状態を復元（state_snapshots自体を除く）
│   3. 以降のスナップショットを削除
│   4. rewound_to_turn 付き ChatResponse を返却
│   → return
│
├─ B. resolved処理（request.action == "resolved" の場合）
│   ├→ action_value == "yes" → DONE へ遷移
│   ├→ action_value == "no" → solutions_tried++ → 3回超えたら URGENCY_CHECK、それ以外は再問診
│   └→ action_value == "book" → RESERVATION へ遷移
│   → return
│
├─ C. 空入力チェック → 空なら「症状について教えてください」を返却
│
└─ D. メイン問診フロー（以下詳細）
```

### D. メイン問診フロー詳細

```
1. ユーザー入力保存 + diagnostic_turn++
   session.collected_symptoms.append(user_input)
   session.conversation_history.append({role: "user", content: user_input})
   session.diagnostic_turn += 1
     ↓
2. スナップショット保存（F1: Rewind機能）
   session.state_snapshots.append({turn: N, state: session全体のdump})
   上限: max_diagnostic_turns 件
     ↓
3. キーワード緊急度チェック（高速パス）
   keyword_urgency_check(全症状テキスト)
   ├→ CRITICAL → RESERVATION へ即時遷移
   └→ それ以外 → 続行
     ↓
4. RAG検索
   rag_service.query(symptom, vehicle_id, make, model, year)
   → rag_context (マニュアルテキスト) + rag_sources (参照情報)
     ↓
5. 会話要約（3ターンごと）
   _maybe_summarize(session, provider)
   → session.conversation_summary を更新
     ↓
6. 候補トリガー判定
   confidence >= 0.7 OR turn >= 4 → session.candidates_shown = True
     ↓
7. プロンプト構築
   _build_recent_turns(session)       — 直近4件の会話
   _build_additional_instructions()   — 条件付き追加指示
   DIAGNOSTIC_PROMPT.format(...)      — 全パラメータ埋め込み
     ↓
8. LLM呼び出し
   _llm_call(provider, diagnostic_prompt)
   → JSON (DIAGNOSTIC_SCHEMA に準拠)
     ↓
9. LLM結果パース
   action, message, urgency_flag, choices, can_drive,
   manual_coverage, visit_urgency, confidence_to_answer, etc.
     ↓
10. トピック関連性ガード
    _is_irrelevant_topic(question_topic, symptom_text, history)
    → 無関係なら再LLM呼び出し（topic制限指示付き）
     ↓
11. 待ちメッセージ検出
    _is_waiting_message(message) → 「まとめます」等を検出したら再LLM呼び出し
     ↓
12. manual_coverage 緊急度引き上げ（F3）
    not_covered かつ urgency_flag が none/low → medium に引き上げ
     ↓
13. urgency_flag チェック
    ├→ critical → RESERVATION へ即時遷移
    └→ high → urgency_level, can_drive をセッションに保存
     ↓
14. action に基づく分岐（下記詳細）
```

### action 別の分岐

| action | 処理 | 遷移先 |
|--------|------|--------|
| `escalate` | 緊急エスカレーション | → RESERVATION |
| `spec_answer` | 仕様回答（マニュアル準拠） | → SPEC_CHECK |
| `provide_answer` | 診断回答を提示 | urgency high/critical → RESERVATION、それ以外 → 解決確認（DIAGNOSING内） |
| `clarify_term` | 専門用語の確認 | DIAGNOSING（選択肢付き） |
| `ask_question` | 追加質問 | DIAGNOSING（選択肢付き） |

### provide_answer の分岐

```
provide_answer
  ↓
  manual_coverage 警告追加:
  ├→ not_covered → 「⚠️ ディーラーでの点検を推奨」追記
  └→ partially_covered → 「ℹ️ 一般的な知識に基づく回答」追記
  ↓
  urgency_flag 判定:
  ├→ high/critical:
  │   ├→ can_drive=false → 🚨 自走禁止 + ロードサービス選択肢 → RESERVATION
  │   └→ can_drive=true  → ⚠️ 早急な点検推奨 + 予約選択肢 → RESERVATION
  └→ none/low/medium:
      → 「解決しました / 解決していません / 予約したい」選択肢 → DIAGNOSING内
```

### 選択肢（choices）の処理

**設計方針**: ハードコードされた用語変換辞書は使用しない。LLMが返した選択肢をそのまま表示する。
専門用語の素人向け説明はLLMがプロンプト指示に従って生成する（マニュアル用語 + カッコ書き説明）。

```
LLM が choices: ["選択肢A", "選択肢B", "選択肢C"] を返却
  ↓
_append_default_choices(choices)
  1. LLM選択肢の重複排除（seen セット）
  2. value = label = LLMが返した文字列そのまま（変換なし）
  3. 末尾に「わからない」「✏️ 自由入力」を追加（重複除外）
  ↓
_attach_icons(choices, question_topic)
  1. question_topic に「警告灯」「ランプ」「表示灯」「インジケーター」が含まれるか判定
  2. 含まれる場合、各選択肢のlabelにキーワード（エンジン、ABS等）が含まれれば icon パスを付与
  3. 含まれない場合は何もしない（従来通り）
  ↓
[
  {value: "選択肢A", label: "選択肢A", icon: "/icons/warning-lights/engine.svg"},  // 警告灯質問時のみ
  {value: "選択肢B", label: "選択肢B", icon: "/icons/warning-lights/abs.svg"},
  {value: "選択肢C", label: "選択肢C"},
  {value: "dont_know", label: "わからない"},
  {value: "free_input", label: "✏️ 自由入力"},
]
```

**フロントエンド側**: `ChatContainer.tsx` でも選択肢はLLMの返却値をそのまま使用。
ハードコードされたラベル変換マップ（LABEL_MAP）やヒントマップ（HINT_MAP）は廃止済み。

**選択肢の品質担保**: プロンプト（DIAGNOSTIC_PROMPT）で以下を指示:
- choices は質問の回答として直接適切なもののみ
- 質問と無関係な選択肢は絶対に入れないこと
- 重複禁止
- 専門用語にはカッコ書きで素人向け説明を添える
- マニュアルの用語を使う場合もカッコ書きで説明を添える

---

## 5. SPEC_CHECK ステップ（仕様確認）

**ファイル**: `backend/app/chat_flow/step_spec_check.py`
**関数**: `handle_spec_check(session, request)`

```
Phase 1 (spec_check_shown=False):
  LLMで仕様判定 (SPEC_CLASSIFICATION_SCHEMA)
  ├→ is_spec=true & confidence=high → 仕様説明を表示、ユーザーに確認
  └→ それ以外 → DIAGNOSING へフォールスルー

Phase 2 (spec_check_shown=True):
  ├→ "resolved" → DONE
  └→ "not_resolved" / "already_tried" → DIAGNOSING
```

---

## 6. URGENCY_CHECK ステップ（緊急度評価）

**ファイル**: `backend/app/chat_flow/step_urgency.py`
**関数**: `handle_urgency_check(session, request)`

```
UrgencyAssessor.assess() 呼び出し
  ↓
  1. keyword_urgency_check() — ルールベース（即時）
  2. LLM判定 (URGENCY_SCHEMA) — RAG警告情報付き
  3. 両者を統合（より高い緊急度を採用）
  ↓
  level 判定:
  ├→ high/critical → RESERVATION へ
  └→ low/medium → アドバイス表示 → DONE
```

### UrgencyAssessor 詳細

**ファイル**: `backend/app/services/urgency_assessor.py`

二段階判定:
1. **キーワードベース**: CRITICAL_RULES / HIGH_RULES / MEDIUM_RULES を正規表現でマッチ
2. **LLMベース**: URGENCY_ASSESSMENT_PROMPT + URGENCY_SCHEMA でStructured Output
3. **統合**: キーワードとLLMの結果を比較し、高い方を採用。理由はマージ

| ルールレベル | visit_urgency | can_drive | 例 |
|------------|---------------|-----------|-----|
| CRITICAL | immediate | false | ブレーキ故障、火災、オイル漏れ |
| HIGH | today | true | 警告灯点灯、異音、振動 |
| MEDIUM | this_week | true | 燃費悪化、エアコン不調 |

---

## 7. RESERVATION ステップ（予約導線）

**ファイル**: `backend/app/chat_flow/step_reservation.py`

### 3つのサブステップ

```
RESERVATION: handle_reservation()
  → visit_urgency に基づくメッセージ分岐
  → 予約するか選択
    ├→ dispatch → BOOKING_INFO (出張手配フォーム)
    ├→ visit   → BOOKING_INFO (来店予約フォーム) ※can_drive=true時のみ
    └→ skip    → DONE

BOOKING_INFO: handle_booking_info()
  → フォーム表示（名前/電話/住所 or 希望日時）
  → submit_booking → BOOKING_CONFIRM

BOOKING_CONFIRM: handle_booking_confirm()
  → 確認画面表示
  ├→ confirm → 予約完了メッセージ → DONE
  └→ edit    → BOOKING_INFO に戻る
```

### visit_urgency によるメッセージ分岐

| visit_urgency | メッセージ |
|--------------|-----------|
| — (can_drive=false) | 🚨 今すぐロードサービスまたは来場が必要です |
| immediate | 🚨 今すぐ来場またはロードサービスが必要です |
| today | ⚠️ 本日中の来場をおすすめします |
| this_week | ⚠️ 今週中の来場をおすすめします |

---

## 8. データモデル

### SessionState (`backend/app/models/session.py`)

問診中に蓄積されるセッション状態。インメモリ辞書ストアに保存。

| フィールド | 型 | 用途 |
|-----------|-----|------|
| `session_id` | str | セッション識別子 |
| `current_step` | ChatStep | 現在のステートマシンステップ |
| `vehicle_id/make/model/year` | str/int | 選択された車両情報 |
| `symptom_text` | str | 最初の症状入力 |
| `collected_symptoms` | list[str] | 全ユーザー入力の蓄積 |
| `conversation_history` | list[dict] | {role, content} 形式の全会話履歴 |
| `diagnostic_turn` | int | 問診ターン数（0始まり） |
| `max_diagnostic_turns` | int | 問診ターン上限（デフォルト8） |
| `last_confidence` | float | 直近のLLM confidence_to_answer |
| `candidates_shown` | bool | 候補トリガー済みか |
| `solutions_tried` | int | 解決策試行回数 |
| `conversation_summary` | str | 3ターンごとのLLM要約 |
| `rewritten_query` | str | LLMが改善したRAG検索クエリ |
| `urgency_level` | str | 最終緊急度 |
| `can_drive` | bool | 走行可否 |
| `manual_coverage` | str | マニュアルカバレッジ判定 (covered/partially_covered/not_covered) |
| `visit_urgency` | str | 来場緊急度 (immediate/today/this_week/when_convenient) |
| `state_snapshots` | list[dict] | Rewind用スナップショット |
| `spec_hint` | bool | 仕様ヒントフラグ |
| `spec_check_shown` | bool | 仕様確認表示済みか |
| `booking_type` | str | 予約種別 (dispatch/visit) |
| `booking_data` | dict | 予約フォーム入力データ |

### ChatRequest / ChatResponse (`backend/app/models/chat.py`)

```
ChatRequest:
  session_id       — セッションID（初回はnull）
  message          — ユーザーのテキスト入力
  action           — ボタン押下時のアクション名
  action_value     — ボタンの値
  rewind_to_turn   — やり直し先のターン番号

ChatResponse:
  session_id       — セッションID
  current_step     — 現在のステップ名
  prompt           — PromptInfo（表示内容）
  urgency          — UrgencyInfo（緊急度情報、任意）
  rag_sources      — RAG参照元リスト
  manual_coverage  — マニュアルカバレッジ
  diagnostic_turn  — 現在の問診ターン
  rewound_to_turn  — やり直し先ターン（rewind時のみ）

PromptInfo:
  type             — text / single_choice / reservation_choice / booking_form / booking_confirm
  message          — 表示メッセージ
  choices          — 選択肢リスト [{value, label, icon?}]
  booking_type     — 予約種別
  booking_fields   — フォームフィールド定義
  booking_summary  — 予約確認用サマリー
```

---

## 9. LLMスキーマ

### DIAGNOSTIC_SCHEMA (`backend/app/llm/schemas.py`)

問診ループのLLM呼び出しで使用。Structured Outputs (JSON Schema) で型安全なレスポンスを強制。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `action` | enum | ask_question / clarify_term / provide_answer / escalate / spec_answer |
| `message` | string | ユーザー向けメッセージ |
| `urgency_flag` | enum | none / low / medium / high / critical |
| `reasoning` | string | 内部ログ用の判断理由 |
| `choices` | array/null | 選択肢文字列の配列（uniqueItems制約あり） |
| `can_drive` | bool/null | 走行可否（判断不能時はnull） |
| `confidence_to_answer` | number | 回答確信度 0.0〜1.0 |
| `rewritten_query` | string | 次回RAG検索用クエリ |
| `question_topic` | string | 質問トピック |
| `manual_coverage` | enum | covered / partially_covered / not_covered |
| `visit_urgency` | enum/null | immediate / today / this_week / when_convenient |
| `term_to_clarify` | string/null | clarify_term時の対象用語 |

### URGENCY_SCHEMA

緊急度評価のLLM呼び出しで使用。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `level` | enum | low / medium / high / critical |
| `can_drive` | bool | 走行可否 |
| `visit_urgency` | enum | immediate / today / this_week / when_convenient |
| `reasons` | array[string] | 判定理由リスト |
| `recommendation` | string | 推奨アクション |

---

## 10. RAGサービス

**ファイル**: `backend/app/services/rag_service.py`
**クラス**: `RAGService`

```
query(symptom, vehicle_id, make, model, year)
  ↓
  vector_store.search(query, vehicle_id, n_results=5)  — ChromaDB検索
  ↓
  score > 0.3 のみフィルタ
  ↓
  RAG_ANSWER_PROMPT or NO_RAG_ANSWER_PROMPT でLLM呼び出し
  ↓
  {answer: string, sources: [{content, page, section, score}]}
```

`step_diagnosing.py` では `rag_service.query()` の結果を `rag_context` として DIAGNOSTIC_PROMPT に埋め込む。

---

## 11. ガード機構まとめ

| ガード | 場所 | 目的 |
|--------|------|------|
| キーワード緊急度 | `step3_free_text.py`, `step_diagnosing.py` | CRITICAL症状を即座にRESERVATIONへ |
| トピック関連性 | `step_diagnosing.py: _is_irrelevant_topic` | 症状と無関係な質問をブロック |
| 重複質問検出 | `step_diagnosing.py: _is_duplicate_question` | 同じ質問の繰り返しを防止 |
| 待ちメッセージ検出 | `step_diagnosing.py: _is_waiting_message` | 「まとめます」等の非実質メッセージを排除 |
| 選択肢重複排除 | `step_diagnosing.py: _append_default_choices` | LLM返却選択肢の重複除去 |
| 警告灯アイコン付与 | `step_diagnosing.py: _attach_icons` | 警告灯系質問トピック時に選択肢にアイコンパスを付与 |
| 仕様ルーティング安全ゲート | `step3_free_text.py: _should_route_to_spec_check` | 危険症状を仕様パスに流さない |
| 自走来店拒否 | `step_reservation.py` | can_drive=false時にvisitを拒否 |
| manual_coverage urgency引き上げ | `step_diagnosing.py` | not_covered時にurgencyをmediumに引き上げ |

---

## 12. Structured Outputs（構造化出力）の処理フロー

### 概要

本システムでは OpenAI の **Structured Outputs** 機能を使用して、LLMの応答を JSON Schema に厳密に準拠させている。
これにより、LLMの自由文応答ではなく、型安全なフィールド群（action, urgency_flag, choices 等）を確実に取得できる。

### アーキテクチャ

```
スキーマ定義                  プロンプト構築              LLM呼び出し               結果パース
backend/app/llm/schemas.py → backend/app/llm/prompts.py → backend/app/llm/openai_provider.py → 各stepハンドラー
 (DIAGNOSTIC_SCHEMA等)        (DIAGNOSTIC_PROMPT等)        (response_format パラメータ)         (json.loads → dict)
```

### ステップ1: スキーマ定義

**ファイル**: `backend/app/llm/schemas.py`

Python辞書として JSON Schema を定義。OpenAI の `response_format` パラメータにそのまま渡せる形式。

```python
DIAGNOSTIC_SCHEMA = {
    "name": "diagnostic_response",      # スキーマ名（OpenAI API用識別子）
    "strict": True,                      # 厳密モード: スキーマ違反時にエラー
    "schema": {
        "type": "object",
        "required": [...],               # 全フィールドが必須
        "additionalProperties": False,   # 未定義フィールド禁止
        "properties": {
            "action": {"type": "string", "enum": [...]},
            "message": {"type": "string"},
            "choices": {"type": ["array", "null"], "items": {"type": "string"}},
            ...
        }
    }
}
```

本システムで使用している3つのスキーマ:

| スキーマ | 用途 | 使用箇所 |
|---------|------|---------|
| `DIAGNOSTIC_SCHEMA` | 問診ループ（質問/回答/エスカレーション判定） | `step_diagnosing.py` |
| `URGENCY_SCHEMA` | 緊急度評価（level/can_drive/visit_urgency判定） | `urgency_assessor.py` |
| `SPEC_CLASSIFICATION_SCHEMA` | 仕様確認（正常動作かどうかの判定） | `step_spec_check.py` |

### ステップ2: プロンプト構築

**ファイル**: `backend/app/llm/prompts.py`

各スキーマに対応するプロンプトテンプレートを定義。`{placeholder}` 形式で実行時にパラメータを埋め込む。

```
DIAGNOSTIC_PROMPT → DIAGNOSTIC_SCHEMA と対
  - 車両情報、症状、RAGコンテキスト、会話履歴、追加指示を埋め込み
  - スキーマの各フィールドの判定基準をプロンプト内に明示記載
    例: 「confidence_to_answer の判定基準: 0.0〜0.3 = まだ概要のみ...」
    例: 「manual_coverage: covered/partially_covered/not_covered の判定基準...」

URGENCY_ASSESSMENT_PROMPT → URGENCY_SCHEMA と対
SPEC_CLASSIFICATION_PROMPT → SPEC_CLASSIFICATION_SCHEMA と対
```

**重要**: プロンプト内にスキーマフィールドの判定基準を自然言語で記述し、LLMがスキーマのどの値を選ぶべきかを指示する。スキーマは型制約、プロンプトは意味制約を担当。

### ステップ3: LLMプロバイダーでの処理

**ファイル**: `backend/app/llm/openai_provider.py`
**クラス**: `OpenAIProvider`
**メソッド**: `chat(messages, temperature, response_format)`

```python
async def chat(self, messages, temperature, response_format=None, ...):
    kwargs = {
        "model": settings.openai_model,   # 例: "gpt-4o"
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        # ★ Structured Outputs: スキーマ辞書をそのまま渡す
        kwargs["response_format"] = response_format

    response = await client.chat.completions.create(**kwargs)
    return LLMResponse(content=choice.message.content)
```

OpenAI API に渡される `response_format` の実際の値:
```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "diagnostic_response",
    "strict": true,
    "schema": { ... }
  }
}
```

`strict: true` により、OpenAI API側でレスポンスがスキーマに100%準拠することが保証される。
型の不一致やrequiredフィールドの欠落はAPI側でリジェクトされる。

### ステップ4: 呼び出し元での利用

各stepハンドラーで以下のパターンで利用:

```python
# step_diagnosing.py の例
response = await provider.chat(
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": diagnostic_prompt},      # ステップ2で構築
    ],
    temperature=0.3,
    response_format={"type": "json_schema", "json_schema": DIAGNOSTIC_SCHEMA},  # ステップ1
)
result = json.loads(response.content)  # str → dict

# 型安全にフィールドアクセス
action = result.get("action", "ask_question")
message = result.get("message", "")
urgency_flag = result.get("urgency_flag", "none")
choices = result.get("choices")   # list[str] | None
can_drive = result.get("can_drive")  # bool | None
manual_coverage = result.get("manual_coverage", "covered")
visit_urgency = result.get("visit_urgency")  # str | None
```

### ステップ5: 後処理（バリデーション・ガード）

Structured Outputs で型は保証されるが、**意味的な妥当性**はプロンプト依存。
そのため、以下の後処理でLLM出力を検証・補正する:

```
json.loads(response.content)
  ↓
1. action/urgency_flag/manual_coverage → セッション状態に保存
  ↓
2. choices → _append_default_choices() で重複排除 + デフォルト追加
  ↓
2b. choices → _attach_icons() で警告灯アイコン付与（question_topicが警告灯系の場合）
  ↓
3. question_topic → _is_irrelevant_topic() で関連性チェック
   NG → プロンプト修正して再LLM呼び出し
  ↓
4. message → _is_waiting_message() で待ちメッセージ検出
   NG → 強制 provide_answer 指示で再LLM呼び出し
  ↓
5. message → _is_duplicate_question() で重複質問検出
   NG → 汎用メッセージに差し替え
  ↓
6. manual_coverage == "not_covered" → urgency_flag 引き上げ
  ↓
7. urgency_flag → high/critical 判定 → ステップ遷移
```

### プロバイダー抽象化

**ファイル**: `backend/app/llm/base.py`

```python
class LLMProvider(ABC):
    async def chat(self, messages, temperature, max_tokens, json_mode, response_format) -> LLMResponse: ...
    async def embed(self, texts) -> EmbeddingResponse: ...
```

`response_format` パラメータは全プロバイダー共通のインターフェース。
現在の実装: OpenAI (`openai_provider.py`), Bedrock (`bedrock_provider.py`), Gemini (`gemini_provider.py`), Watson (`watson_provider.py`)

**ファイル**: `backend/app/llm/registry.py`

```python
class ProviderRegistry:
    def get_active(self) -> LLMProvider | None   # 現在のアクティブプロバイダー
    def set_active(self, name: str)              # プロバイダー切り替え
```

デフォルトは `openai`。プロバイダーを切り替えても、Structured Outputs の仕組みは同一。

### エラーハンドリング

```
LLM呼び出し
  ├→ 正常: json.loads() → result dict
  ├→ JSONDecodeError: フォールバックメッセージを返却
  ├→ ネットワークエラー: フォールバックメッセージを返却
  └→ Structured Outputs スキーマ違反: OpenAI API が 400 エラー → Exception → フォールバック
```

`step_diagnosing.py` のフォールバック:
```python
except (json.JSONDecodeError, Exception) as e:
    logger.error(f"LLM diagnostic call failed: {e}")
    fallback_msg = "他に気になる症状や状況があれば教えてください。"
    return ChatResponse(prompt=PromptInfo(type="text", message=fallback_msg))
```

### Structured Outputs の利点（本システムにおいて）

1. **型安全**: action が必ず enum 値、urgency_flag が必ず5段階のいずれか → if分岐が安全
2. **フィールド保証**: choices, can_drive, manual_coverage 等が必ず存在 → `result.get()` で KeyError なし
3. **パース不要**: 自由文からの正規表現パースが不要 → コード簡潔化・バグ低減
4. **strict モード**: スキーマ違反がAPI側で検出 → アプリ側での型チェック不要

### Structured Outputs の制約（注意点）

OpenAI の strict モードでは、JSON Schema の一部キーワードが使用不可:
- `uniqueItems` — 使用不可（配列の重複排除はアプリ側で実装）
- `pattern` — 使用不可
- `minItems` / `maxItems` — 使用不可（プロンプトで「3〜4個」と指示）

そのため、**型制約はスキーマ、意味制約・数量制約はプロンプト、重複排除はアプリコード**の三層で担保する設計。
