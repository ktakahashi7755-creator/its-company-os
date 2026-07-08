# フォーム営業 半自動化キット

戦略の正本：`docs/sales-automation-strategy.md`

## 毎日の回し方（約30分）

1. **リスト補充**（週1回）：Claude Codeに「◯◯市の工務店を20件、prospects.csvに追加して」と指示
2. **診断＋文面生成**（自動・数分）：
   ```
   node automation/form-sales/check_prospects.mjs automation/form-sales/prospects.csv
   ```
3. **送信**（手動・1件約60秒）：`output/messages_日付.md` を上から順に、相手のフォームに貼って送信
   - 送信前に「営業お断り」表記がないか一瞥（スクリプト検知＋目視の二重チェック）
   - 送信したら `sent.csv` に1行追記（次回から自動でスキップされる）
4. **返信が来たら24時間以内に電話** → 結果を `data/pipeline.md` へ

## ルール（戦略書§3の要約）
- 1日20件まで。完全無人送信はしない
- 「営業お断り」には送らない。「連絡不要」と言われたら `do-not-contact.csv` へ
- 文面に虚偽を書かない

## ファイル
- `check_prospects.mjs` … 診断＋文面生成（Node 18+、依存パッケージなし）
- `prospects.csv` … 見込み客リスト（社名,URL,業種。サイトがない場合URL空欄）
- `sent.csv` / `do-not-contact.csv` … 送信済み・連絡禁止の記録
- `output/` … 生成物（gitignore対象・コミットしない）
