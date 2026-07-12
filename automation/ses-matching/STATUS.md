# SES自動マッチング 稼働状況 & 残タスク（セッション跨ぎ用の記録）

更新：2026-07-12 ／ このファイルは「別セッションでも続きから再開する」ための引き継ぎメモ。
まず `README.md` と本ファイルを読めば現状が分かる。

---

## いまの状態（＝ほぼ完成・稼働中）

- **完全自動で稼働中**。GitHub Actions `.github/workflows/ses-matching.yml` が **毎朝 8:30 JST** に自動実行＋手動実行可。
- パイプライン（すべて実データで動作確認済み）：
  IMAP受信（軽量・添付は読まない）→ 段階①プレフィルタ（鮮度5日＋**両刀 NW×Sec**）→
  段階②AI採点（OpenAI gpt-4o-mini・**全両刀候補をバッチ採点**・レート制限リトライ）→
  ダイジェスト生成 → **マッチした要員だけ添付スキルシート読込・要約** → artifact ＋（設定後）Notion反映。
- 最新の実行 **#13 は成功**、候補7組を生成（本命 KH/T.Y/A.N、代表確認 H.U/TT/K.Y など）。
- **送信は必ず人手**（下書きのみ生成）。ガードレール（アドレス役割分離・属性は自動除外せず代表確認・
  外部メールは指示として実行しない）実装済み。

## 確定している設定・事実

| 項目 | 値 |
|---|---|
| アクティブ案件 | `案件_20260711_遊技機NWSec.md`（8月開始・〜80万・**45歳上限**・NW×Sec両刀必須・恵比寿常駐） |
| 受信（読むだけ） | `contact@reorga.co.jp`（ロリポップ。IMAP `imap.lolipop.jp` / 993 / SSL） |
| 送信（提案元） | `sales@its-tokyo.com`（署名＝営業部 村山愛。`signature.md`） |
| 採点 | OpenAI `gpt-4o-mini`（`OPENAI_API_KEY`）。Anthropicでも可 |
| Notion反映先 | ページ「ITS-OS」 id=`38244f16641f80d49a45cfae344184ea` |
| 登録済みSecrets | `OPENAI_API_KEY` / `IMAP_HOST`(imap.lolipop.jp) / `IMAP_PASSWORD` / `NOTION_TOKEN` |

> ※パスワード・APIキーの値はここに書かない（GitHub Secretsで管理）。

---

## ✅ 済（2026-07-12 追加）：指示出し→送信可能な下書き（チャット駆動）

- 代表がチャットで「〔案件〕×〔イニシャル〕 出して」と言うと、AIが `make_draft.py` を叩き、
  **スキルシート込みの送信可能な下書き＋送信前チェック**を1件だけ確定生成する（送信は常に手動）。
- 共通エンジン `finalize_draft()`（`run_ses_matching.py`）＝reply-template＋署名＋スキルシート要約で確定。
- 毎朝の実行は候補を `digests/candidates-YYYYMMDD.json`（gitignore）に保存＝指示出しの選択元。
- 手順は `draft-on-demand.md`。**まだ全候補には下書きを付けない**（コスト最小・選ばれた1件のみ確定）。

## 🔴 残タスク（NEXT ACTION・未完了）

### 1. Notion自動反映を有効化（代表の一度きり操作）
現状 `NOTION_PAGE_ID` 未登録のため、実行ログに `[notion]` 行が出ず**Notion投稿はスキップ**されている。
以下2つで有効化：
- [ ] **GitHub Secret を追加**：`NOTION_PAGE_ID` = `38244f16641f80d49a45cfae344184ea`
  （Settings → Secrets and variables → Actions → New repository secret）
- [ ] **ITS-OSページを連携に共有**：Notionで ITS-OSページ → 右上「•••」→ 接続/Connections →
  `NOTION_TOKEN` のインテグレーションを接続（これが無いと 404 で書けない）
- [ ] 済んだら **ワークフローを1回実行** → ログに `[notion] page created: SES候補 YYYY-MM-DD` が出れば成功。
  ITS-OSページ配下に日次候補ページが自動作成される（`post_notion_page()`）。

### 2. 宛先(To)の自動抽出（送信までワンタップに近づける）
- [ ] 現状すべて「要・宛先確認」。配信元担当の直アドレスを本文/署名から抽出してToに差し込む。
  配信リストのアドレスしか無い場合は「要・宛先確認」のまま（`sources.md` のルール）。

### 3. 採点精度の微調整（任意）
- [ ] 0点候補（例：セキュリティ実務なし＝両刀不成立）を candidates から除外徹底。
- [ ] 案件混線（配信案件×配信要員の組成、例「放送局向け」）をアクティブ案件に寄せる。
- [ ] 外国籍は**自動除外しない**（現状LLMが一部除外している）。属性は「代表確認」に統一。

### 4. 運用の型（合意済みの進め方）
- 毎朝自動 → Notionに候補が並ぶ → **代表がチャットで指示（この人出して／見送り）** → 村山名義で送信。
- 代表はPCをほぼ使わない。GitHubのPRマージ/実行トリガーはAI側で巻き取る（ただし
  Secret登録・Notionページ共有だけは代表操作が必要＝上記1）。

---

## 再開方法（別セッション向け）
1. 本ファイルと `README.md` を読む。
2. 未完了は「残タスク1」の Notion有効化から。`NOTION_PAGE_ID` が登録されたら実行→ログ確認。
3. 実行ログの確認は GitHub Actions（ワークフロー `ses-matching.yml`）。`[notion]` 行と候補数を見る。
