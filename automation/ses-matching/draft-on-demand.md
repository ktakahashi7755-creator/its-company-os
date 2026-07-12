# 指示出し → 送信可能な下書き（チャット駆動）

代表がチャットで「**この要員を出して**」と指示したら、AIがその1件だけ **送信可能な提案メール下書き** を返す仕組み。
**送信は必ず代表が手動**（ITSセールス `sales@its-tokyo.com` から）。AIは下書きまで（`README.md` ガードレール）。

> 毎朝の自動マッチング（`run_ses_matching.py`）は「候補＋たたき台下書き」を出す。
> ここはその先の「**代表が1人選んだら、スキルシート込みの送信可能な下書きに確定する**」工程。

## 使い方（代表）

Notion（または朝のダイジェスト）で候補を見て、チャットでこう言うだけ：

- 「**遊技機 × KH を出して**」
- 「**1番の人で。単価は72万上限、商流は元請直を強調して**」（補足指示つき）
- 「**T.Y で下書き**」

AIが `make_draft.py` を叩き、**From/To/件名/本文/署名まで入った下書き** ＋ **送信前チェック** を返す。
代表は内容を確認し、OKなら **sales@ から手動送信**。結果は `../../data/pipeline.md` へ。

## AI側の手順（このリポジトリで作業するAI＝Claude向け）

代表の「〇〇を出して」を受けたら：

1. **候補データを用意する**（`digests/candidates-YYYYMMDD.json`＝gitignore・毎朝の実行が生成）。
   - 手元に無ければ、当日のマッチングを実行して生成：`python run_ses_matching.py --source imap`
     （または GitHub Actions `ses-matching.yml` を実行 → artifact `ses-digest` を取得）。
   - Notion運用中なら、当日候補ページ／レビューDBの該当行から候補材料を拾ってもよい。
2. **下書きを確定生成**：
   ```bash
   python automation/ses-matching/make_draft.py --pick "KH" --note "代表の補足があれば"
   # 番号でも可（スコア降順・1始まり）: --pick 1
   # 特定日: --date 2026-07-12 --pick T.Y
   # Notion/artifactから貼る: --candidate-json '{"case":"...","engineer":"...","to":"...","skillsheet_summary":"..."}'
   ```
3. 出力された **下書き全文＋送信前チェック** をそのまま代表に提示する。**AIは送信しない。**

## ガードレール（再掲・厳守）

- **From は `sales@its-tokyo.com` 固定**。REOorGA受信アドレス（`contact@reorga.co.jp`）からは絶対に送らない。
- **To は候補の宛先をそのまま**。不明なら「要・宛先確認」のまま残す（アドレスを創作しない）。
- 資料に無い情報は捏造しない（単価・稼働開始などが不明なら「要確認」）。
- 属性（年齢・国籍等）は本文に書かない。フラグは代表確認事項として本文外で扱う（`scoring.md`）。
- **送信は必ず代表が手動**。ステータスをAIが勝手に「送信済」にしない。

## 関連ファイル

- `make_draft.py`……下書き確定の実体（共通エンジン `finalize_draft()` を `run_ses_matching.py` から再利用）。
- `reply-template.md`……提案メールの作法（5点・書き出し・送信前チェック）の正本。
- `signature.md`……送信者名・署名の正本（村山愛／営業部）。
- `notion-review.md`……代表レビュー面（候補の並び・ステータス運用）。
