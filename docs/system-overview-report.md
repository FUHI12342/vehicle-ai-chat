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
| ChoiceButtons | 選択肢ボタン群の表示 |
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

## 6. 主要機能の動作概要

### 6-1. 危険度判定（ブレーキ故障の場合）

「ブレーキが効かない」と入力すると:
1. キーワードルールが即座にCRITICALと判定
2. 問診をスキップし、直接予約画面へ
3. 「運転を中止してください」と表示
4. 「ロードサービスを呼ぶ」ボタンを提示（自走での来店は不可）

### 6-2. マニュアル記載外の不具合検出

マニュアルに載っていない症状の場合:
1. LLMが `manual_coverage = not_covered` と判定
2. 緊急度を1段階引き上げ（安全側に）
3. 回答に「ディーラーでの点検を推奨します」を追記
4. 画面に黄色バッジ「マニュアル記載外」を表示

### 6-3. やり直し機能

問診中に過去の回答をやり直せる:
1. 各ターンでセッション状態のスナップショットを保存
2. 「やり直す」ボタンでそのターンまで巻き戻し
3. 以降のメッセージは画面から削除
4. 別の回答を入力して問診を続行

---

## 7. 技術スタック一覧

| レイヤー | 技術 | バージョン |
|---------|------|-----------|
| フロントエンド | Next.js / React / TypeScript / Tailwind CSS | 15 / 19 |
| バックエンド | FastAPI / Python / Pydantic | 3.12 |
| AI | OpenAI API (Structured Outputs) | GPT-4o |
| マニュアル検索 | ChromaDB + OpenAI Embeddings | — |
| PDF処理 | pdfplumber | — |
| セッション管理 | インメモリ辞書（TTL 30分） | — |
| 構成図 | Mermaid.js（自動生成） | 11.x |
