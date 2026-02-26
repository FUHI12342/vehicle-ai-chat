# ハンドテスト手順書

2026-02-26 追加3機能のテスト手順

## 前提条件

- バックエンド起動済み (`uvicorn app.main:app`)
- フロントエンド起動済み (`npm run dev`)
- LLMプロバイダー設定済み (OpenAI APIキー)
- 車両マニュアルがRAGに登録済み（少なくとも1台分）

---

## テスト1: マニュアルに載っている症状 → `manual_coverage = covered`

### 手順
1. チャットを開始
2. マニュアル登録済みの車両を選択（例: フィット）
3. 症状入力: 「セレクトレバーが動かない」
4. 問診に回答（2〜3ターン）
5. provide_answer が表示されるまで進める

### 期待結果
- [ ] 回答メッセージに「ディーラーでの点検を推奨」の警告が **ない**
- [ ] 黄色バッジ「マニュアル記載外」が **表示されない**
- [ ] マニュアル参照ページが表示される

---

## テスト2: マニュアルに載っていない症状 → `manual_coverage = not_covered`

### 手順
1. チャットを開始
2. 車両を選択
3. 症状入力: 「走行中にハンドルが左に引っ張られる」（マニュアルに通常記載がない症状）
4. 問診に回答
5. provide_answer まで進める

### 期待結果
- [ ] 回答メッセージ末尾に「⚠️ マニュアルに記載のない症状のため、ディーラーでの点検を推奨します」が表示される
- [ ] 黄色バッジ「⚠ マニュアル記載外 — 想定外の不具合の可能性があります」が表示される
- [ ] urgency が none/low だった場合、medium に引き上げられている

---

## テスト3: ブレーキ故障 → `visit_urgency = immediate`, `can_drive = false`

### 手順
1. チャットを開始
2. 車両を選択
3. 症状入力: 「ブレーキが効かない」

### 期待結果
- [ ] キーワード判定で即座に CRITICAL 判定
- [ ] 予約画面（RESERVATION）に遷移
- [ ] UrgencyAlert に赤太字「🚨 運転を中止してください」が表示される
- [ ] UrgencyAlert に「今すぐ来場/ロードサービスが必要です」ラベルが表示される
- [ ] 予約メッセージが「🚨 今すぐロードサービスまたは来場が必要です」

---

## テスト4: 警告灯点灯 → `visit_urgency = today`, `can_drive = true`

### 手順
1. チャットを開始
2. 車両を選択
3. 症状入力: 「エンジン警告灯が点灯している」
4. 問診に回答（必要に応じて）

### 期待結果
- [ ] urgency_level が high
- [ ] UrgencyAlert に「本日中の来場をおすすめします」ラベルが表示される
- [ ] 「🚨 運転を中止してください」は **表示されない**（can_drive = true）
- [ ] 来店予約の選択肢が表示される

---

## テスト5: 問診3ターン後に「やり直す」

### 手順
1. チャットを開始
2. 車両を選択
3. 症状入力: 「エンジンから異音がする」
4. 問診1回目: 適当に回答（例: 「走行中に聞こえる」）
5. 問診2回目: 適当に回答（例: 「カタカタという音」）
6. 問診3回目: 適当に回答（例: 「最近始まった」）
7. **問診1回目のユーザーメッセージ**の下に「やり直す」リンクが表示されていることを確認
8. 「やり直す」をクリック

### 期待結果
- [ ] DIAGNOSING 中のユーザーメッセージ（最新以外）に「やり直す」リンクが表示される
- [ ] 最新のユーザーメッセージには「やり直す」が **表示されない**
- [ ] 「やり直す」クリック後、そのメッセージ以降のやり取りがチャットから削除される
- [ ] バックエンドのセッション状態がそのターンの時点に復元される
- [ ] その後、別の回答を入力して問診を続行できる

---

## テスト6: やり直し後に完了まで進む

### 手順
1. テスト5の状態から続行
2. やり直し後、別の回答を入力
3. provide_answer まで進める
4. 「解決しました」を選択

### 期待結果
- [ ] provide_answer が正常に表示される
- [ ] 「解決しました」選択で DONE ステップに遷移
- [ ] 完了メッセージが表示される

---

## テスト7: 複合確認（not_covered + visit_urgency）

### 手順
1. チャットを開始
2. 車両を選択
3. 症状入力: 「走行中にステアリングが重くなったり軽くなったりする」
4. 問診に回答

### 期待結果
- [ ] manual_coverage が not_covered または partially_covered
- [ ] visit_urgency が設定されている（todayまたはthis_week）
- [ ] 両方の表示が同時に正しく出ている

---

## 確認用チェックリスト（開発者向け）

### バックエンド確認コマンド
```bash
# 全ファイルのコンパイルチェック
python3 -m py_compile backend/app/models/session.py
python3 -m py_compile backend/app/models/chat.py
python3 -m py_compile backend/app/llm/schemas.py
python3 -m py_compile backend/app/llm/prompts.py
python3 -m py_compile backend/app/chat_flow/step_diagnosing.py
python3 -m py_compile backend/app/services/urgency_assessor.py
python3 -m py_compile backend/app/chat_flow/step_urgency.py
python3 -m py_compile backend/app/chat_flow/step_reservation.py
```

### フロントエンド確認コマンド
```bash
cd frontend && npm run build
```

### スキーマ確認
- `DIAGNOSTIC_SCHEMA` に `manual_coverage`, `visit_urgency` が存在すること
- `URGENCY_SCHEMA` に `visit_urgency` が存在すること
- `SessionState` に `state_snapshots`, `visit_urgency`, `manual_coverage` が存在すること
