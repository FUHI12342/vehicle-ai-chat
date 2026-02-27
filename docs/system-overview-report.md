# 車両トラブル診断AIチャットシステム — システム概要報告書

## 1. システムの目的

車両オーナーが症状を入力すると、AIが一問一答形式で問診を行い、**車両マニュアルの情報**を活用して原因特定・対処手順の提示・緊急度判定・ディーラー予約導線までを一気通貫で提供するWebアプリケーション。

---

## 2. システム構成図の各レイヤーの役割

http://localhost:3000 の「構成図」ボタンから閲覧可能。

### 2-1. Frontend（Next.js 15 / React 19）

**役割**: ユーザーが操作する画面（チャットUI）

ユーザーのブラウザ上で動作する部分。チャット画面、車両検索、選択肢ボタン、予約フォームなど。

| コンポーネント | 役割 |
|--------------|------|
| ChatContainer | チャット画面全体の制御（入力欄、選択肢、予約フォームの出し分け） |
| ChatInput | テキスト入力欄 |
| ChoiceButtons | 選択肢ボタン群の表示（警告灯アイコンカード対応） |
| MessageBubble | 吹き出し1つ分の表示（ユーザー: 青、AI: グレー） |
| MessageList | 吹き出しの一覧表示（スクロール、やり直しボタン、バッジ表示） |
| VehicleSearch | 車両検索・選択UI |
| VehiclePhotoCard | 車両写真の確認表示 |
| ReservationForm | ディーラー予約フォーム |
| UrgencyAlert | 緊急度に応じた警告表示（赤: 運転中止、黄: 本日来場推奨 等） |
| TypingIndicator | AI回答生成中の「...」表示 |

| Hooks | 役割 |
|-------|------|
| useChat | チャットのコアロジック（メッセージ送受信、セッション管理、やり直し機能） |
| useSession | セッションID管理 |

### 2-2. Next.js API Proxy

**役割**: フロントエンドからバックエンドへのリクエスト中継

ブラウザからの `/api/*` リクエストを `http://localhost:8000/api/*`（FastAPI）に転送する。セキュリティ上、バックエンドのURLを直接ブラウザに公開しないための仕組み。

### 2-3. Backend API（FastAPI）

**役割**: ビジネスロジックの入り口（APIエンドポイント）

フロントエンドからのHTTPリクエストを受け取り、適切なサービスに処理を委譲する。

| エンドポイント | 役割 |
|--------------|------|
| POST `/api/chat` | チャットメッセージの送受信（メインのAPI） |
| GET `/api/vehicles/search` | 車両名での検索 |
| GET `/api/health` | サーバーの生存確認 |
| POST `/api/admin/ingest` | PDFマニュアルの取り込み（管理者用） |
| GET `/api/providers` | LLMプロバイダーの一覧・状態確認 |

### 2-4. Services（サービス層）

**役割**: ビジネスロジックの本体

| サービス | 役割 |
|---------|------|
| ChatService | チャット処理の中核。セッション取得→ステートマシン実行→セッション保存 |
| RAGService | マニュアル検索。ChromaDBからユーザーの症状に関連するマニュアル情報を取得 |
| SessionStore | セッション管理。インメモリ辞書に保存（TTL=30分で自動削除） |
| UrgencyAssessor | 緊急度判定。キーワードベース（即時）+ LLMベース（詳細）の二段階 |
| VehicleService | 車両データの検索（vehicles.jsonから） |

### 2-5. Chat Flow State Machine（チャットフロー状態マシン）

**役割**: 問診の進行制御

ユーザーとの対話を「ステップ」という概念で管理する。各ステップには専用のハンドラー関数があり、ユーザーの入力に応じて次のステップに遷移する。

```
vehicle_id → photo_confirm → free_text → spec_check → diagnosing
                                              ↓              ↓
                                          (仕様確認)    urgency_check
                                              ↓              ↓
                                          diagnosing     reservation
                                              ↓              ↓
                                      (CRITICAL時)     booking_info
                                              ↓              ↓
                                          reservation   booking_confirm
                                                             ↓
                                                            done
```

| ステップ | 意味 | 何が起こるか |
|---------|------|------------|
| vehicle_id | 車両選択 | ユーザーが車を検索・選択 |
| photo_confirm | 写真確認 | 「この車で合ってますか？」 |
| free_text | 症状入力 | ユーザーが自由文で症状を入力 |
| spec_check | 仕様確認 | 「それは正常な動作（仕様）かもしれません」と提示 |
| diagnosing | 問診ループ | AIが質問→ユーザー回答→AIが質問…を繰り返し、原因を特定 |
| urgency_check | 緊急度評価 | 問診完了後、LLMで緊急度を最終判定 |
| reservation | 予約導線 | 緊急度に応じてロードサービス/来店予約を提案 |
| booking_info | 予約情報入力 | 名前・電話番号・住所等のフォーム |
| booking_confirm | 予約確認 | 入力内容の確認画面 |
| done | 完了 | 問診終了 |

### 2-6. LLM Layer（大規模言語モデル層）

**役割**: AIの「頭脳」

OpenAI GPT-4 を使って、ユーザーの症状を理解し、質問を生成し、診断結果を出す。

- **ProviderRegistry**: LLMプロバイダーの管理（切り替え可能）
- **OpenAI GPT-4**: 現在のメインプロバイダー
- **AWS Bedrock / Google Gemini / IBM Watson**: 将来の切り替え先として実装済み

**Structured Outputs**: LLMの回答を自由文ではなく、JSON形式（型定義付き）で返させる仕組み。これにより「action: ask_question」「urgency_flag: high」など、プログラムが確実に解釈できる形でAIの判断を受け取る。

### 2-7. RAG Pipeline（検索拡張生成パイプライン）

**役割**: 車両マニュアルPDFの知識をAIに与える

RAG = Retrieval-Augmented Generation（検索で情報を取得し、それを元にAIが回答を生成する手法）

| コンポーネント | 役割 |
|--------------|------|
| PDFLoader | PDFマニュアルを読み込み、テキストを抽出 |
| AutomotiveChunker | テキストを意味のある単位に分割（セクション、手順、警告 等） |
| Embedder | テキストを数値ベクトル（embedding）に変換。意味的に近い文章を検索可能にする |
| VehicleManualStore | ベクトルデータベース（ChromaDB）。症状に関連するマニュアル情報を高速検索 |

**処理の流れ（マニュアル取り込み時）**:
```
PDF → テキスト抽出 → チャンク分割 → ベクトル変換 → ChromaDBに保存
```

**処理の流れ（問診時）**:
```
ユーザーの症状 → ベクトル変換 → ChromaDBで類似検索 → 関連マニュアル情報を取得 → LLMに渡す
```

### 2-8. Data Layer（データ層）

**役割**: 静的データの保存

| データ | 内容 |
|-------|------|
| vehicles.json | 車両マスタデータ（メーカー、車種、年式、写真URL） |
| PDF マニュアル | 車両オーナーズマニュアルのPDFファイル |
| chroma_data/ | ChromaDBのベクトルデータ（PDFから生成された検索用データ） |

---

## 3. バックエンド主要ファイルの役割一覧

### エントリーポイント

| ファイル | 役割 |
|---------|------|
| `backend/app/main.py` | FastAPIアプリケーションの起動点。CORS設定、ルーター登録、LLMとRAGの初期化 |
| `backend/app/config.py` | 環境変数の読み込み（APIキー、モデル名、TTL等） |

### APIルーター（`backend/app/api/`）

| ファイル | 役割 |
|---------|------|
| `router.py` | 全ルーターを束ねる親ルーター |
| `chat.py` | POST `/api/chat` — チャットメッセージの処理 |
| `vehicles.py` | GET `/api/vehicles/search` — 車両検索 |
| `health.py` | GET `/api/health` — ヘルスチェック |
| `admin.py` | POST `/api/admin/ingest` — PDFマニュアル取り込み |
| `providers.py` | GET `/api/providers` — LLMプロバイダー一覧 |

### チャットフロー（`backend/app/chat_flow/`）

| ファイル | 役割 |
|---------|------|
| `state_machine.py` | ステートマシン本体。`current_step` に基づいてハンドラーを振り分け |
| `step1_vehicle_id.py` | 車両選択ステップ |
| `step2_photo_confirm.py` | 車両写真確認ステップ |
| `step3_free_text.py` | 症状入力ステップ。キーワード緊急度チェック、RAG検索、仕様パス判定を実行 |
| `step_spec_check.py` | 仕様確認ステップ。LLMで「正常動作かどうか」を判定 |
| `step_diagnosing.py` | **問診ループ（最重要ファイル）**。LLMとの対話、選択肢生成、緊急度判定、マニュアルカバレッジ判定、やり直し機能を統合 |
| `step_urgency.py` | 緊急度最終評価。キーワード+LLM二段階で判定 |
| `step_reservation.py` | 予約導線。ロードサービス手配/来店予約/予約確認の3サブステップ |

### LLM（`backend/app/llm/`）

| ファイル | 役割 |
|---------|------|
| `base.py` | LLMプロバイダーの基底クラス（インターフェース定義） |
| `registry.py` | プロバイダーの管理・切り替え |
| `factory.py` | プロバイダーインスタンスの生成 |
| `openai_provider.py` | OpenAI APIとの通信。Structured Outputsの実行 |
| `schemas.py` | LLMに返させるJSONの型定義（DIAGNOSTIC_SCHEMA, URGENCY_SCHEMA, SPEC_CLASSIFICATION_SCHEMA） |
| `prompts.py` | LLMに渡すプロンプト（指示文）のテンプレート |
| `bedrock_provider.py` | AWS Bedrock (Claude) プロバイダー |
| `gemini_provider.py` | Google Gemini プロバイダー |
| `watson_provider.py` | IBM Watson プロバイダー |

### サービス（`backend/app/services/`）

| ファイル | 役割 |
|---------|------|
| `chat_service.py` | チャット処理の中核。セッション管理→ステートマシン実行 |
| `session_store.py` | インメモリセッション管理（TTL付き自動削除） |
| `rag_service.py` | RAG検索の実行。ChromaDB検索→LLMで回答生成 |
| `urgency_assessor.py` | 緊急度判定。キーワードルール（即時）+ LLM（詳細）の二段階 |
| `vehicle_service.py` | 車両データの検索・取得 |

### RAGパイプライン（`backend/app/rag/`）

| ファイル | 役割 |
|---------|------|
| `pdf_loader.py` | PDFからテキスト抽出 |
| `chunker.py` | テキストを意味単位に分割、content_type（手順/仕様/警告等）を自動分類 |
| `embedder.py` | テキストをベクトル（数値配列）に変換 |
| `vector_store.py` | ChromaDBの操作（保存・検索） |

### データモデル（`backend/app/models/`）

| ファイル | 役割 |
|---------|------|
| `session.py` | セッション状態の定義（ChatStep enum + SessionState）。問診中に蓄積される全情報 |
| `chat.py` | API通信の型定義（ChatRequest / ChatResponse / PromptInfo / UrgencyInfo） |

### データ（`backend/app/data/`）

| ファイル | 役割 |
|---------|------|
| `vehicles.json` | 車両マスタデータ |

---

## 4. フロントエンド主要ファイルの役割一覧

| ファイル | 役割 |
|---------|------|
| `frontend/src/app/page.tsx` | トップページ。ヘッダー + チャットコンテナを配置 |
| `frontend/src/hooks/useChat.ts` | チャットの全ロジック（メッセージ送受信、やり直し、ステップ管理） |
| `frontend/src/lib/api.ts` | バックエンドAPI呼び出しの関数群 |
| `frontend/src/lib/types.ts` | TypeScript型定義（ChatRequest, ChatResponse, ChatMessage 等） |
| `frontend/src/i18n/ja.ts` | 日本語ラベル定義 |
| `frontend/src/lib/architecture-diagram.ts` | システム構成図のMermaid定義（自動生成） |
| `frontend/scripts/generate-architecture-diagram.ts` | 構成図の自動生成スクリプト |

---

## 5. step_diagnosing.py の詳細（問診ループの中核）

このファイルは問診の心臓部。1回のユーザー入力に対して以下の処理を行う:

```
ユーザー入力
  ↓
1. やり直し要求チェック（Rewind機能）
2. 解決済み/未解決の選択肢処理
3. ユーザー入力をセッションに保存 + ターン数+1
4. スナップショット保存（やり直し用）
5. キーワード緊急度チェック（ブレーキ故障等 → 即座にレッカー手配へ）
6. マニュアル検索（RAG）
7. 会話要約（3ターンごと）
8. LLMにプロンプトを送信 → Structured Outputsで応答取得
9. トピック関連性チェック（無関係な質問をブロック）
10. 待ちメッセージ検出（「まとめます」等を排除）
11. マニュアルカバレッジ判定（記載外 → 緊急度引き上げ）
12. 緊急度に応じたステップ遷移
13. LLMのaction（ask_question / provide_answer / escalate 等）に基づく応答生成
```

---

## 6. Structured Outputs（構造化出力）の処理フロー詳細

### 6-1. Structured Outputs とは

通常のAI（ChatGPT等）は自由文で回答する。しかし本システムでは、AIの回答を**決まった形式のJSON**で返させている。
これにより、プログラムがAIの判断（「質問する」「回答する」「緊急」等）を確実に解釈でき、画面表示や処理分岐を正確に行える。

### 6-2. 関係するファイルと役割

```
【定義】                      【指示】                      【実行】                      【利用】
schemas.py                →  prompts.py                →  openai_provider.py          →  step_diagnosing.py
「AIにどんな形式で          「AIにどう判断すべきか        「OpenAI APIに送信して        「返ってきたJSONを解釈して
 返してほしいか」の型定義」    を自然言語で指示」            JSONを受け取る」              画面表示や処理分岐に使う」
```

### 6-3. ステップ1: 型定義（schemas.py）

**ファイル**: `backend/app/llm/schemas.py`

AIに「こういう形のJSONで返してね」と伝えるための設計図。Python辞書として定義する。

**DIAGNOSTIC_SCHEMA**（問診用）— AIが毎回返す12フィールド:

| フィールド | 型 | 意味（初心者向け） |
|-----------|-----|-------------------|
| `action` | 5択から1つ | AIの次のアクション。「質問する(ask_question)」「回答する(provide_answer)」「緊急(escalate)」等 |
| `message` | 文字列 | ユーザーに表示するメッセージ本文 |
| `urgency_flag` | 5段階 | 緊急度。none（問題なし）→ low → medium → high → critical（即危険） |
| `choices` | 文字列の配列 or null | ユーザーに見せる選択肢（例: ["かかっている", "かかっていない", "たまに"]） |
| `can_drive` | true/false/null | 車を運転して大丈夫か。null=まだ判断できない |
| `confidence_to_answer` | 0.0〜1.0 | AIが「もう回答できる」と思っている度合い。0.7以上で回答を促す |
| `manual_coverage` | 3択 | マニュアルに症状の記載があるか。covered / partially_covered / not_covered |
| `visit_urgency` | 4段階 or null | ディーラー来場の緊急度。immediate / today / this_week / when_convenient |
| `rewritten_query` | 文字列 | 次にマニュアル検索するときの改善されたキーワード |
| `question_topic` | 文字列 | この質問が扱うトピック（内部ログ用） |
| `reasoning` | 文字列 | AIの判断理由（内部ログ用、ユーザーには見せない） |
| `term_to_clarify` | 文字列 or null | 専門用語確認時の対象用語 |

**URGENCY_SCHEMA**（緊急度評価用）— 5フィールド:

| フィールド | 型 | 意味 |
|-----------|-----|------|
| `level` | 4段階 | low / medium / high / critical |
| `can_drive` | true/false | 運転可否 |
| `visit_urgency` | 4段階 | 来場緊急度 |
| `reasons` | 文字列の配列 | 判定理由のリスト |
| `recommendation` | 文字列 | 推奨アクション |

**SPEC_CLASSIFICATION_SCHEMA**（仕様確認用）— 5フィールド:

| フィールド | 型 | 意味 |
|-----------|-----|------|
| `is_spec_behavior` | true/false | 正常な動作（仕様）かどうか |
| `confidence` | 3段階 | 判定の確信度（high/medium/low） |
| `explanation` | 文字列 | ユーザー向け説明 |
| `manual_reference` | 文字列 | マニュアルの参照箇所 |
| `reasoning` | 文字列 | 内部ログ用の判断理由 |

### 6-4. ステップ2: プロンプト（prompts.py）

**ファイル**: `backend/app/llm/prompts.py`

AIへの指示文。「車両情報」「症状」「マニュアル情報」「会話履歴」を埋め込み、各フィールドの判定基準を自然言語で指示する。

例（DIAGNOSTIC_PROMPT の一部）:
```
【confidence_to_answer の判定基準】
- 0.0〜0.3: まだ症状の概要しか分からない段階
- 0.7〜0.8: 原因がほぼ特定でき、回答の準備ができている
- 0.9〜1.0: 確実に回答できる

【choices のルール】
- choices は質問の回答として直接適切なもののみ
- 質問と無関係な選択肢は絶対に入れないこと
- 専門用語にはカッコ書きで素人向け説明を添える
```

**重要な設計**: スキーマは「型」（文字列か数値か等）を制約し、プロンプトは「意味」（どの値を選ぶべきか）を制約する。この二層で品質を担保している。

### 6-5. ステップ3: API呼び出し（openai_provider.py）

**ファイル**: `backend/app/llm/openai_provider.py`

OpenAI APIに以下を送信:
- messages: システムプロンプト + ユーザープロンプト（車両情報、症状、マニュアル情報等を埋め込み済み）
- response_format: スキーマ定義（DIAGNOSTIC_SCHEMA等）
- temperature: 0.3（低め = 安定した回答を重視）

OpenAI API側で `strict: true` が設定されているため、AIの回答がスキーマに100%準拠することが保証される。型の不一致やフィールドの欠落はAPI側で自動的に拒否される。

### 6-6. ステップ4: 結果の利用（step_diagnosing.py等）

AIから返ってきたJSONを `json.loads()` でPython辞書に変換し、各フィールドを取り出してロジックに使う。

```python
result = json.loads(response.content)   # AI回答をJSON→辞書に変換

action = result.get("action")           # → "ask_question" or "provide_answer" 等
message = result.get("message")         # → ユーザーに表示するメッセージ
urgency_flag = result.get("urgency_flag")  # → "none" or "high" 等
choices = result.get("choices")         # → ["選択肢A", "選択肢B"] or None
manual_coverage = result.get("manual_coverage")  # → "covered" or "not_covered"
```

### 6-7. ステップ5: 後処理（ガード機構）

AIの回答は型は保証されるが、意味的な妥当性はプロンプト依存なので、以下の後処理で検証・補正する:

| 後処理 | 場所 | 内容 |
|--------|------|------|
| 選択肢重複排除 | `_append_default_choices()` | 同じ選択肢が2つ出ないようにする |
| 警告灯アイコン付与 | `_attach_icons()` | 警告灯系の質問トピックの場合、選択肢にアイコンパスを付与 |
| トピック関連性チェック | `_is_irrelevant_topic()` | 症状と無関係な質問をブロック→再LLM呼び出し |
| 待ちメッセージ排除 | `_is_waiting_message()` | 「まとめます」等の無意味な回答を排除→再LLM呼び出し |
| 重複質問排除 | `_is_duplicate_question()` | 同じ質問の繰り返しを防止 |
| urgency引き上げ | manual_coverage判定 | not_covered時にurgencyをmediumに引き上げ |

### 6-8. Structured Outputs の制約と対策

OpenAIのstrict modeでは、JSON Schemaの一部キーワードが使えない:

| 使えないキーワード | 本来の用途 | 代替策 |
|------------------|-----------|--------|
| `uniqueItems` | 配列の重複禁止 | バックエンドの `_append_default_choices()` で重複排除 |
| `minItems`/`maxItems` | 配列の要素数制限 | プロンプトで「3〜4個入れてください」と指示 |
| `pattern` | 文字列の正規表現制約 | プロンプトで「50文字以内」等を指示 |

**設計方針**: 型制約はスキーマ、意味・数量制約はプロンプト、重複排除はアプリコードの**三層**で品質を担保する。

---

## 7. 危険度判定フロー詳細

### 7-1. 二段階判定の仕組み

危険度判定は**キーワードベース（即時）**と**LLMベース（詳細）**の二段階で行う。

```
ユーザーの症状入力
  ↓
【第1段階: キーワード判定】(urgency_assessor.py)
  ↓ 正規表現で即座にマッチ（LLM呼び出し不要、0.01秒以下）
  ├→ CRITICAL マッチ → 即座に「運転中止 + ロードサービス」→ 予約画面へ（問診スキップ）
  ├→ HIGH マッチ → 問診は続行するが、urgency_level="high" をセッションに記録
  ├→ MEDIUM マッチ → 問診は続行、urgency_level="medium" を記録
  └→ マッチなし → 第2段階へ
  ↓
【第2段階: LLM判定】(問診中 or urgency_check ステップ)
  ↓ URGENCY_SCHEMA でAIに緊急度を評価させる
  → キーワード結果とLLM結果を比較し、高い方を採用
```

### 7-2. キーワード判定ルール（urgency_assessor.py）

**CRITICALルール**（即座に運転中止）:

| パターン | 例 | 理由 |
|---------|-----|------|
| ブレーキ + 効かない/止まらない | 「ブレーキが効かない」 | 走行安全に直結 |
| 煙/白煙/黒煙 | 「ボンネットから煙が出る」 | 火災の危険 |
| 発火/火/燃え | 「エンジンルームから火が見える」 | 即座に退避 |
| オイル + 漏 | 「オイルが漏れている」 | エンジン焼き付き・火災 |
| ステアリング/ハンドル + 効かない/動かない | 「ハンドルが動かない」 | 走行不能・事故 |
| 冷却水/クーラント + 漏/減/なくな | 「冷却水がなくなった」 | オーバーヒート |
| オーバーヒート/水温異常 | 「水温計が赤い」 | エンジン損傷 |

**HIGHルール**（早急に点検）:

| パターン | 例 |
|---------|-----|
| 警告灯/ランプ点灯 | 「エンジン警告灯が点いた」 |
| 異音（ガタガタ、キーキー等） | 「走行中にキーキー音がする」 |
| 異常な振動 | 「走行中にガクガクする」 |
| 異臭（焦げ/ゴム/ガソリン） | 「焦げ臭い」 |
| タイヤ/パンク + 空気異常 | 「タイヤがぺちゃんこ」 |
| ABS/エアバッグ警告灯 | 「ABSランプが点灯」 |

### 7-3. visit_urgency と can_drive の対応表

| 状況 | urgency | visit_urgency | can_drive | ユーザーへの指示 |
|------|---------|--------------|-----------|----------------|
| ブレーキ故障 | critical | immediate | false | 「運転を中止してください」→ ロードサービス手配 |
| エンジンから煙 | critical | immediate | false | 「車から離れてください」→ ロードサービス手配 |
| 警告灯点灯 | high | today | true | 「本日中にディーラーへ」→ 来店予約 |
| 異音/振動 | high | today | true | 「早めにディーラーへ」→ 来店予約 |
| エアコン不調 | medium | this_week | true | 「今週中にディーラーへ」→ 来店予約 |
| 軽微な消耗品 | low | when_convenient | true | 「都合の良い時に」→ アドバイスのみ |

### 7-4. 予約画面での分岐（step_reservation.py）

```
can_drive = false の場合:
  → booking_type = "dispatch"（出張手配/ロードサービス）
  → メッセージ: 「🚨 今すぐロードサービスまたは来場が必要です」
  → 選択肢: 「ロードサービスを呼ぶ」「今は予約しない」
  → ※「ディーラーに持ち込む」は表示しない（自走不可のため）
  → 万が一 visit を選んでも → 「🚫 自走での来店は危険です」と拒否

can_drive = true の場合:
  visit_urgency に応じたメッセージ:
  ├→ immediate: 「🚨 今すぐ来場が必要です」
  ├→ today:     「⚠️ 本日中の来場をおすすめします」
  └→ this_week: 「⚠️ 今週中の来場をおすすめします」
  → 選択肢: 「はい、予約する」「いいえ、今は予約しない」
```

### 7-5. フロントエンドでの表示（UrgencyAlert.tsx）

| 条件 | 表示 |
|------|------|
| can_drive === false | 赤太字「🚨 運転を中止してください」 |
| visit_urgency === "immediate" | 「今すぐ来場/ロードサービスが必要です」 |
| visit_urgency === "today" | 「本日中の来場をおすすめします」 |
| visit_urgency === "this_week" | 「今週中の来場をおすすめします」 |
| visit_urgency === "when_convenient" | 「ご都合の良い時に」 |

---

## 8. マニュアル記載外の不具合検出フロー詳細

### 8-1. 目的

ユーザーの症状がオーナーズマニュアルに記載されている（=既知の問題）か、記載されていない（=予期せぬ不具合の可能性）かをAIが毎ターン判定する。
マニュアルに載っていない症状は「想定外の不具合」の可能性が高いため、安全側に倒してディーラー来場を推奨する。

### 8-2. 判定フロー

```
ユーザーが症状を入力
  ↓
RAG検索: ChromaDBからマニュアルの関連情報を取得
  ↓
LLMに送信:
  - ユーザーの症状
  - マニュアルの関連情報（RAG結果）
  - 「manual_coverageを判定してください」という指示（プロンプト内）
  ↓
LLMが毎ターン判定:
  ├→ "covered":           マニュアルに明確に記載あり
  ├→ "partially_covered": 関連情報はあるが完全一致ではない
  └→ "not_covered":       マニュアルに該当なし（RAG結果が空の場合も含む）
  ↓
バックエンド後処理 (step_diagnosing.py):
  1. session.manual_coverage に保存
  2. not_covered かつ urgency_flag が none/low → medium に引き上げ
  3. provide_answer 時にメッセージ追記
  ↓
フロントエンド表示 (MessageList.tsx):
  ├→ covered:           バッジなし（通常表示）
  ├→ partially_covered: グレーバッジ「マニュアルに完全一致する情報はありません」
  └→ not_covered:       黄色バッジ「⚠ マニュアル記載外 — 想定外の不具合の可能性があります」
```

### 8-3. 判定基準（プロンプトでAIに指示）

| 判定値 | 基準 | 具体例 |
|--------|------|--------|
| covered | マニュアルに症状の原因/対処法が明確に記載 | 「セレクトレバーが動かない」→ マニュアルにシフトロック解除手順あり |
| partially_covered | 関連情報はあるが症状そのものの記載はない | 「エンジンから異音」→ マニュアルにエンジン項目はあるが異音の記載なし |
| not_covered | 該当記載が一切ない | 「ハンドルが左に引っ張られる」→ マニュアルに該当なし |

### 8-4. not_covered 時の安全措置

1. **urgency引き上げ**: none/low → medium に自動昇格（安全側に倒す）
2. **警告メッセージ追記**: provide_answer の末尾に「⚠️ マニュアルに記載のない症状のため、ディーラーでの点検を推奨します」
3. **画面バッジ**: 黄色の目立つバッジで「マニュアル記載外」を明示

---

## 9. やり直し（Rewind）機能フロー詳細

### 9-1. 目的

問診中にユーザーが「さっきの回答を変えたい」と思った時、過去のターンまで巻き戻して別の回答を試せるようにする。
例: 「走行中に聞こえる」と答えたが、よく考えたら「停車中にも聞こえる」だった → やり直し

### 9-2. スナップショットの仕組み

**スナップショットとは**: ある時点のセッション状態（全フィールド）の複製。ゲームの「セーブデータ」のようなもの。

```
問診ターン1: ユーザー入力 → [スナップショット1を保存] → AI質問
問診ターン2: ユーザー入力 → [スナップショット2を保存] → AI質問
問診ターン3: ユーザー入力 → [スナップショット3を保存] → AI回答
          ↑
    ここで「やり直す」を押すと…
    → スナップショット1の状態に巻き戻し
    → ターン1以降のスナップショットを削除
    → 画面からターン1以降のメッセージを削除
    → 別の回答を入力して問診を再開
```

### 9-3. バックエンド処理（step_diagnosing.py）

**スナップショット保存**（各ターン開始時）:
```python
# 1. セッション状態の全フィールドをコピー（スナップショット自体は除く）
snapshot = session.model_dump(exclude={"state_snapshots"})
# 2. ターン番号と一緒に保存
session.state_snapshots.append({"turn": session.diagnostic_turn, "state": snapshot})
# 3. 上限チェック（最大8件、古いものから削除）
if len(session.state_snapshots) > session.max_diagnostic_turns:
    session.state_snapshots = session.state_snapshots[-session.max_diagnostic_turns:]
```

**やり直し処理**（rewind_to_turn が指定された時）:
```python
# 1. 指定ターンのスナップショットを検索
for idx, snap in enumerate(session.state_snapshots):
    if snap["turn"] == target_turn:
        snapshot_entry = snap
        break

# 2. スナップショットからセッション状態を復元
for key, value in saved.items():
    if key != "state_snapshots":        # スナップショット自体は復元しない
        setattr(session, key, value)    # セッションの各フィールドを上書き

# 3. このターン以降のスナップショットを削除
session.state_snapshots = session.state_snapshots[:snapshot_idx]

# 4. 復元されたセッションの最後のAIメッセージを返却
```

### 9-4. フロントエンド処理

**useChat.ts**:
```
rewindToTurn(turn) が呼ばれると:
  1. APIに rewind_to_turn=N を送信
  2. レスポンスの rewound_to_turn を確認
  3. 該当ターン以降のメッセージを配列から削除（画面から消える）
```

**MessageList.tsx / MessageBubble.tsx**:
```
条件: currentStep === "diagnosing" かつ ユーザーのメッセージ かつ 最新メッセージでない
  → 「やり直す」リンクを表示

最新のユーザーメッセージには「やり直す」は表示しない
（最新の回答を変えたいなら普通に入力し直せばよいため）
```

### 9-5. やり直しの制約

| 項目 | 値 | 理由 |
|------|-----|------|
| スナップショット上限 | 8件 | メモリ節約（1件≒5KB、8件≒40KB） |
| 対象ステップ | diagnosing のみ | 車両選択や予約画面でのやり直しは不要 |
| やり直し後 | 該当ターン以降の全データが消える | 分岐した時間軸を混在させない設計 |

### 9-6. やり直しの具体的シナリオ

```
ターン1: AI「エンジンはかかっていますか？」
         ユーザー「かかっていない」← ここに「やり直す」リンクが出る
ターン2: AI「バッテリーは新しいですか？」
         ユーザー「わからない」     ← ここにも「やり直す」リンクが出る
ターン3: AI「回答: バッテリー交換をお試しください」
         ユーザー（ここが最新なので「やり直す」は出ない）

→ ユーザーがターン1の「やり直す」をクリック
→ ターン1以降が全て消える
→ AI「エンジンはかかっていますか？」が再表示される
→ ユーザー「たまにかかる」← 別の回答を入力
→ 新しいターン2以降がスタート
```

---

## 10. 画像選択カード（警告灯アイコン）フロー詳細

### 10-1. 目的

問診で「ダッシュボードの警告灯は何が点灯していますか？」のような質問が出た際、テキストボタンだけでは警告灯の種類を識別しにくい。警告灯アイコンを画像カード形式で提示し、ユーザーが視覚的に直感的に選択できるようにする。

### 10-2. 処理フロー

```
LLMが ask_question で質問を生成
  ↓
question_topic に「警告灯」「ランプ」「表示灯」「インジケーター」が含まれるか？
  ├→ 含まれない → 従来通りテキストボタン表示
  └→ 含まれる → _attach_icons() で選択肢にアイコンパス付与
       ↓
     各選択肢のlabelにキーワード（エンジン、ABS、バッテリー等）が含まれるか？
       ├→ 含まれる → choice["icon"] = "/icons/warning-lights/engine.svg" 等
       └→ 含まれない → icon なし（テキストボタンとして末尾配置）
       ↓
     フロントエンドで icon 付き選択肢を検出
       → 3列グリッドのアイコンカード表示に切替
       → 「わからない」「自由入力」はテキストボタンとして下部に配置
```

### 10-3. バックエンド処理（step_diagnosing.py）

**アイコンマッピング辞書**（`WARNING_LIGHT_ICONS`）:

| キーワード | アイコンパス | 対象の警告灯 |
|-----------|------------|------------|
| エンジン | `/icons/warning-lights/engine.svg` | エンジン/チェックエンジン |
| ABS | `/icons/warning-lights/abs.svg` | ABS |
| 油圧 / オイル | `/icons/warning-lights/oil.svg` | 油圧/オイル |
| 水温 | `/icons/warning-lights/coolant.svg` | 水温 |
| バッテリー / 充電 | `/icons/warning-lights/battery.svg` | バッテリー/充電 |
| エアバッグ | `/icons/warning-lights/airbag.svg` | エアバッグ/SRS |
| ブレーキ | `/icons/warning-lights/brake.svg` | ブレーキ |
| パワステ | `/icons/warning-lights/power-steering.svg` | パワーステアリング |
| タイヤ / 空気圧 | `/icons/warning-lights/tpms.svg` | タイヤ空気圧 |
| シートベルト | `/icons/warning-lights/seatbelt.svg` | シートベルト |

**トピック判定キーワード**（`VISUAL_TOPICS`）: `{"警告灯", "ランプ", "表示灯", "インジケーター"}`

**呼び出し箇所**: `_append_default_choices()` の直後に `_attach_icons()` を呼び出し:
```python
choices_for_prompt = _append_default_choices(choices)
choices_for_prompt = _attach_icons(choices_for_prompt, question_topic)
```

### 10-4. フロントエンド表示（ChoiceButtons.tsx）

アイコン付き選択肢が1つでもある場合、コンポーネントは2つのセクションに分かれる:

1. **アイコンカードグリッド**（3列）:
   - 各カードにSVGアイコン（40x40px）+ ラベル
   - ホバー時にアンバー色のハイライト
   - タップで通常の選択と同じ動作

2. **テキストボタン**（グリッドの下）:
   - `icon` を持たない選択肢（「わからない」「✏️ 自由入力」等）
   - 従来通りのButton表示

アイコン付き選択肢がない場合は、従来通りのテキストボタン/グリッド表示にフォールバックする。

### 10-5. SVGアイコンセット

`frontend/public/icons/warning-lights/` に10個のSVGアイコンを配置:

| ファイル | 表す警告灯 | 配色 |
|---------|----------|------|
| `engine.svg` | エンジン/チェックエンジン | アンバー |
| `abs.svg` | ABS | アンバー |
| `oil.svg` | 油圧/オイル | アンバー/赤 |
| `coolant.svg` | 水温 | 赤 |
| `battery.svg` | バッテリー/充電 | 赤 |
| `airbag.svg` | エアバッグ/SRS | 赤 |
| `brake.svg` | ブレーキ | 赤 |
| `power-steering.svg` | パワーステアリング | アンバー |
| `tpms.svg` | タイヤ空気圧 | アンバー |
| `seatbelt.svg` | シートベルト | 赤 |

### 10-6. 型定義の変更

`frontend/src/lib/types.ts` の `PromptInfo.choices` に `icon` フィールドを追加:
```typescript
choices?: { value: string; label: string; icon?: string }[];
```

LLMスキーマ（`schemas.py`）の変更は不要。バックエンドの後処理でアイコンパスを付与するため、LLMはアイコンの存在を意識しない。

---

## 11. 技術スタック一覧

| レイヤー | 技術 | バージョン |
|---------|------|-----------|
| フロントエンド | Next.js / React / TypeScript / Tailwind CSS | 15 / 19 |
| バックエンド | FastAPI / Python / Pydantic | 3.12 |
| AI | OpenAI API (Structured Outputs) | GPT-4o |
| マニュアル検索 | ChromaDB + OpenAI Embeddings | — |
| PDF処理 | pdfplumber | — |
| セッション管理 | インメモリ辞書（TTL 30分） | — |
| 構成図 | Mermaid.js（自動生成） | 11.x |
