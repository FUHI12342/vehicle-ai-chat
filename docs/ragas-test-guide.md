# RAGAS テストガイド

車両問診AIの品質評価ガイド。10種のテストケースによるハンドテスト手順と、RAGAS自動評価の実行方法を記載する。

## テストケース一覧

車両: **ホンダ アコード 2011年式** (`vehicle_id: 30TA06210_web`)

| # | カテゴリ | 症状テキスト | 期待urgency | 期待action | 確認ポイント |
|---|---------|-----------|-----------|----------|------------|
| 1 | ブレーキ故障 | ブレーキを踏んでも止まらない感じがする | critical | escalate | 即停車指示 + ロードサービス案内が出るか |
| 2 | エンジン警告灯 | エンジンの警告灯が点灯している | high | ask_question | 警告灯の色・点灯パターンを聞くか |
| 3 | 走行中異音 | 走行中にガタガタと異音がする | medium | ask_question | 速度域・場所の特定質問が出るか |
| 4 | エアコン不調 | エアコンから冷たい風が出ない | low | ask_question | 設定確認 → 冷媒不足の可能性に触れるか |
| 5 | エンジン始動不良 | エンジンがかからない | high | ask_question | バッテリー/セルモーターの確認を促すか |
| 6 | オイル漏れ | 駐車場の地面に油のシミがある | high | ask_question | 漏れ液の色・位置を聞くか |
| 7 | タイヤ空気圧 | タイヤの空気圧警告灯がついた | medium | ask_question | TPMS説明 + 空気圧点検を案内するか |
| 8 | ハンドル重い | ハンドルが急に重くなった | medium | ask_question | パワステ系統（油圧/電動）の確認を促すか |
| 9 | 仕様確認系 | 停車中にエンジンが止まることがある | low | spec_answer | アイドリングストップの仕様説明が出るか |
| 10 | オーバーヒート | 水温計が赤いところまで上がっている | critical | escalate | 即停車指示 + ラジエーターキャップ注意が出るか |

---

## ハンドテスト手順

### 準備

1. バックエンドを起動
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```
2. フロントエンドを起動
   ```bash
   cd frontend
   npm run dev
   ```
3. ブラウザで `http://localhost:3000` を開く

### テスト実行手順（各ケース共通）

1. **新規チャット開始** — チャット画面を開く
2. **車両選択** — `30TA06210` で検索 or 「ホンダ アコード 2011」を選択
3. **写真確認** — 「はい」を選択
4. **症状入力** — 上記テーブルの「症状テキスト」をそのまま入力
5. **結果確認** — 以下をチェック:

| 確認項目 | 確認方法 |
|---------|---------|
| urgency | 画面上部のアラートバナーの色・レベル表示 |
| action | `escalate` → 予約画面に遷移、`ask_question` → 追加質問が表示、`spec_answer` → 仕様説明が表示 |
| manual_coverage | メッセージ下部のバッジ（黄色=not_covered、グレー=partially_covered） |
| 回答内容 | 「確認ポイント」に記載の内容が含まれているか |

### 判定基準

- **PASS**: urgency・actionが期待値と一致し、回答内容が確認ポイントを満たす
- **WARN**: urgency or actionが1段階ずれ（例: high → medium）だが回答内容は適切
- **FAIL**: urgency or actionが大幅にずれている、または安全に関する指示が欠落

---

## RAGAS 自動評価

### セットアップ

```bash
cd backend
pip install ragas datasets
```

`OPENAI_API_KEY` が `.env` に設定されていることを確認（RAGASの内部評価にLLMを使用）。

### RAGAS評価の実行

```bash
cd backend
python -m tests.ragas.run_ragas_eval
```

出力:
- コンソールに全体スコア + テストケース別スコアのテーブル
- `backend/test_results/ragas_eval_YYYYMMDD_HHMMSS.json` に結果JSON

### E2Eチャットテストの実行

バックエンドが起動している状態で:

```bash
cd backend
python -m tests.ragas.run_e2e_chat
```

出力:
- コンソールにurgency/action一致率のテーブル
- `backend/test_results/e2e_chat_YYYYMMDD_HHMMSS.json` に結果JSON

---

## RAGASスコアの読み方

| メトリクス | 説明 | 良好な目安 |
|-----------|------|----------|
| **Faithfulness** | 回答がコンテキスト（検索結果）に忠実か。ハルシネーション検出。 | ≥ 0.8 |
| **Answer Relevancy** | 回答がユーザーの質問に対して関連性があるか。 | ≥ 0.7 |
| **Context Precision** | 検索結果の上位に関連性の高いチャンクが来ているか。 | ≥ 0.6 |
| **Context Recall** | ground_truthの情報が検索結果にどの程度含まれているか。 | ≥ 0.6 |

### スコアが低い場合の改善指針

| 低スコア | 原因の可能性 | 改善アクション |
|---------|------------|--------------|
| Faithfulness < 0.6 | LLMがマニュアル外の情報で回答 | プロンプトの「コンテキストに基づいて回答」指示を強化 |
| Answer Relevancy < 0.5 | 回答が質問と無関係 | プロンプトのフォーカス指示を改善 |
| Context Precision < 0.4 | 検索結果の質が低い | チャンキング戦略の見直し、embedding モデル変更 |
| Context Recall < 0.4 | 必要な情報が検索できていない | チャンクサイズ調整、検索件数(n_results)増加 |

---

## テスト結果の記録

テスト実行ごとに `backend/test_results/` にJSON結果が保存される。時系列で比較することで、RAGパイプラインの改善効果を追跡できる。

```
backend/test_results/
  ragas_eval_20260304_143022.json
  e2e_chat_20260304_143105.json
```
