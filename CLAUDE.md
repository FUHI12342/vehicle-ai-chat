# Vehicle AI Chat — 開発ドキュメント

## プロジェクト概要

車両トラブル診断AIチャットシステム。ユーザーが車両を選択し、症状を入力すると、RAG（車両マニュアル検索）+ LLMによる一問一答形式の問診を経て、原因特定・対処手順の提示・緊急度判定・予約導線までを一気通貫で行う。

## 技術スタック

- **Frontend**: Next.js 15 / React 19 / TypeScript / Tailwind CSS
- **Backend**: FastAPI / Python 3.12 / Pydantic
- **LLM**: OpenAI API (Structured Outputs)
- **RAG**: ChromaDB + OpenAI Embeddings + PyPDF2
- **セッション管理**: インメモリ辞書ストア (TTL付き)

## ディレクトリ構成

```
backend/
  app/
    api/           # FastAPI ルーター
    chat_flow/     # ステートマシン (各ステップのハンドラー)
    llm/           # LLMプロバイダー, スキーマ, プロンプト
    models/        # Pydantic モデル (session, chat)
    services/      # ビジネスロジック (RAG, urgency, session_store)
    rag/           # RAGパイプライン (PDF→chunk→embed→ChromaDB)
    data/          # 静的データ (vehicles.json, diagnostic_config.yaml)
frontend/
  src/
    components/chat/  # チャットUI コンポーネント群
    hooks/            # useChat (チャットロジック)
    lib/              # API, 型定義, 定数
    i18n/             # 日本語ラベル
```

## Chat Flow ステートマシン

```
vehicle_id → photo_confirm → free_text → spec_check → diagnosing
                                              ↓              ↓
                                          (仕様確認)    urgency_check
                                              ↓              ↓
                                           diagnosing    reservation → booking_info → booking_confirm → done
                                              ↓
                                      (CRITICAL時) → reservation
                                              ↓
                                           done
```

## LLM スキーマ

- **DIAGNOSTIC_SCHEMA**: 問診ループ用。action / message / urgency_flag / can_drive / manual_coverage / visit_urgency 等
- **URGENCY_SCHEMA**: 緊急度評価用。level / can_drive / visit_urgency / reasons / recommendation
- **SPEC_CLASSIFICATION_SCHEMA**: 仕様確認用。is_spec_behavior / confidence / explanation

---

## 改修ログ

### 2026-02-26: 3機能追加 (commit 93a6f82)

**前提**: RAG駆動型診断 + 解決策ステップバイステップ方式への移行が完了済み。

#### Feature 3: マニュアル記載外の不具合検出 (`manual_coverage`)

**目的**: LLMがRAG検索結果と症状を照合し、マニュアルでカバーされているかを毎ターン判定する。

**仕組み**:
- LLMが `manual_coverage` を毎回返却: `covered` / `partially_covered` / `not_covered`
- `not_covered` の場合:
  - urgency_flag を1段階引き上げ (none/low → medium)
  - provide_answer メッセージに「ディーラーでの点検を推奨」の警告追加
  - フロントエンドに黄色バッジ表示
- `partially_covered` の場合:
  - provide_answer メッセージに補足追加
  - フロントエンドにグレーバッジ表示

**変更ファイル**:
| ファイル | 変更内容 |
|---------|---------|
| `backend/app/llm/schemas.py` | DIAGNOSTIC_SCHEMA に manual_coverage 追加 |
| `backend/app/models/session.py` | SessionState に manual_coverage フィールド追加 |
| `backend/app/models/chat.py` | ChatResponse に manual_coverage フィールド追加 |
| `backend/app/llm/prompts.py` | DIAGNOSTIC_PROMPT に判定基準追加 |
| `backend/app/chat_flow/step_diagnosing.py` | LLM結果からキャプチャ、urgency引き上げ、警告メッセージ追加、全レスポンスに付与 |
| `frontend/src/lib/types.ts` | ChatResponse, ChatMessage に manualCoverage 追加 |
| `frontend/src/hooks/useChat.ts` | addAssistantMessage で manualCoverage キャプチャ |
| `frontend/src/components/chat/MessageList.tsx` | not_covered/partially_covered バッジ表示 |

#### Feature 2: クリティカル判定の改善 (`visit_urgency`)

**目的**: `can_drive`（運転可否）と `visit_urgency`（販売店来場の緊急度）を独立した軸として分離する。

**visit_urgency の4段階**:
| 値 | 意味 | 対応アクション |
|----|------|--------------|
| `immediate` | 今すぐ来場/ロードサービス | dispatch手配 |
| `today` | 本日中に来場推奨 | 来店予約 |
| `this_week` | 今週中に来場推奨 | 来店予約 |
| `when_convenient` | ご都合の良い時に | アドバイスのみ |

**仕組み**:
- LLM (DIAGNOSTIC_SCHEMA / URGENCY_SCHEMA) が visit_urgency を返却
- キーワード判定: CRITICAL→immediate, HIGH→today, MEDIUM→this_week
- can_drive=true でも visit_urgency="today" はありうる（例: 警告灯点灯）
- フロントエンドの UrgencyAlert で visit_urgency ラベル + can_drive===false 時の赤太字警告
- step_reservation でメッセージ分岐

**変更ファイル**:
| ファイル | 変更内容 |
|---------|---------|
| `backend/app/llm/schemas.py` | DIAGNOSTIC_SCHEMA, URGENCY_SCHEMA に visit_urgency 追加 |
| `backend/app/models/session.py` | SessionState に visit_urgency 追加 |
| `backend/app/models/chat.py` | UrgencyInfo に can_drive, visit_urgency 追加 |
| `backend/app/llm/prompts.py` | 両プロンプトに visit_urgency 判定基準追加 |
| `backend/app/services/urgency_assessor.py` | 全キーワード結果・LLM結果・デフォルトに visit_urgency 追加 |
| `backend/app/chat_flow/step_diagnosing.py` | visit_urgency キャプチャ→セッション保存 |
| `backend/app/chat_flow/step_urgency.py` | UrgencyInfo に can_drive, visit_urgency 含めて返却 |
| `backend/app/chat_flow/step_reservation.py` | visit_urgency に基づくメッセージ分岐 |
| `frontend/src/lib/types.ts` | UrgencyInfo に can_drive, visit_urgency 追加 |
| `frontend/src/components/chat/UrgencyAlert.tsx` | visit_urgency ラベル, can_drive 警告表示 |
| `frontend/src/i18n/ja.ts` | visitUrgency ラベル追加 |

#### Feature 1: 回答やり直し — Rewind (`state_snapshots`)

**目的**: DIAGNOSING中の各ターンでSessionStateのスナップショットを保存し、ユーザーが過去の回答に遡って別の回答を試せるようにする。

**仕組み**:
- 各ターン開始時に `state_snapshots` リストに `{turn: N, state: SessionState全体}` を保存
- 上限: `max_diagnostic_turns` 件（最大8件、約40KB）
- ユーザーが「やり直す」ボタン押下 → `rewind_to_turn` パラメータでAPI送信
- バックエンド: 該当ターンのスナップショットから状態復元、以降のスナップショット削除
- フロントエンド: 該当ターン以降のメッセージを配列から削除
- スコープ: DIAGNOSING ステップのみ

**変更ファイル**:
| ファイル | 変更内容 |
|---------|---------|
| `backend/app/models/session.py` | state_snapshots フィールド追加 |
| `backend/app/models/chat.py` | ChatRequest に rewind_to_turn、ChatResponse に diagnostic_turn / rewound_to_turn 追加 |
| `backend/app/chat_flow/step_diagnosing.py` | Rewindハンドラ、スナップショット保存、diagnostic_turn 全レスポンス付与 |
| `frontend/src/lib/types.ts` | ChatRequest / ChatResponse / ChatMessage に rewind 関連フィールド追加 |
| `frontend/src/hooks/useChat.ts` | rewindToTurn(), diagnosticTurn タグ付け |
| `frontend/src/components/chat/MessageBubble.tsx` | onRewind / showRewind Props、「やり直す」ボタン |
| `frontend/src/components/chat/MessageList.tsx` | currentStep / onRewind Props、条件付きボタン表示 |
| `frontend/src/components/chat/ChatContainer.tsx` | rewindToTurn / currentStep を MessageList に渡す |

---

## システム構成図

`npm run build` 時に自動生成される (`frontend/scripts/generate-architecture-diagram.ts`)。
コンポーネント / サービス / ステートマシン / LLMプロバイダー / RAGパイプライン を自動スキャンして Mermaid 図を出力。
