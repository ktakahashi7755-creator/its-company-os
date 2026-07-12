# SES自動マッチング 稼働状況 & 残タスク（セッション跨ぎ用の記録）

更新：2026-07-13 ／ このファイルは「別セッションでも続きから再開する」ための引き継ぎメモ。
まず `README.md`（使い方）・`HANDOVER.md`（設計と復旧の正本）・本ファイル（稼働状況）を読めば現状が分かる。

> 📘 **引き継ぎ・復旧の正本は `HANDOVER.md`**。携帯/PCが壊れてもゼロから復元できるよう、
> 設計・アカウント台帳・Secretsレジストリ・復旧ランブック・バックアップ手順を1ファイルに集約した。

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

## ✅ 済（2026-07-13）：Notion DB反映のハードニング（レビュー2巡目・4件）＋本番検証

- 独立レビュー2巡目の指摘4件を修正（PR #35・`fix(ses): Notion DB反映のレビュー指摘4件`）：
  - `post_notion_db_rows` に **in-memory重複排除**（検索インデックス遅延で同一run内に重複行ができる穴を封鎖）。
  - `ensure_notion_db` が作成した db_id を **ローカル(`digests/notion-db-id.txt`・gitignore)に保存・再利用** → 連続実行での重複DB作成を防止。
  - `_db_row_props` の面談通過可能性を `(c.get("likelihood") or "低")` に（空文字で空select名→400 を回避）。
  - `main()` の `post_notion_page` も **try で保護** → ページ投稿の失敗が後続（DB・下書き）を巻き込まない。
- **本番 run #21 で実走検証済み**：`[notion-db] データベース作成: SES提案トラッカー（id=39b44f16-641f-8127-abf5-fa44f8ffe335）`
  → `行追加 21／既存スキップ 1` → `sales@ 下書き 新規20`。eval 全決定論ステージ緑。
- **DBのid＝`39b44f16-641f-8127-abf5-fa44f8ffe335`**。Secret `NOTION_DB_ID` に登録すると最も安定（重複DB作成が起きない）。
- 最新安定版バックアップ：`backup/ses-2026-07-13-notiondb-hardened`（詳細は `HANDOVER.md` §8）。

## ✅ 済（2026-07-13）：Notion送信ステータスDB＋順序統一

- **Notion「SES提案トラッカー」DB** を自動作成し、候補を行として蓄積（`post_notion_db_rows`）。
  列：案件×要員／面談通過可能性／スコア／年齢／配信元／宛先To／**ステータス(未送信/送信済/見送り)**／日付／キー。
  重複キー(案件×要員)は行を作らない＝代表が変えたステータスを保全。スキル要約＋原本ファイルは行本文に。
- **代表の使い方（送った人を消す）**：DBで **フィルター「ステータス=未送信」のビュー** を作れば、
  送った相手を `送信済` に変えるだけで一覧から消える（＝実質「横棒で消す」より運用が楽）。
  ボード表示にすれば 未送信→送信済→見送り のカンバンでも管理可。
- **順序統一**：sales@下書きの保存順を**スコア降順**にし、Notion（スコア降順）と並びを一致。
- DBのidは初回作成時にログ出力。固定したい場合は Secret `NOTION_DB_ID` に登録（未登録でも毎回検索で再利用）。
- eval に `notiondb`（7/7）を追加。全決定論9ステージ緑。

## ✅ 済（2026-07-13）：ハードニング（レビュー2巡）＋バックアップ

- **コードレビュー2巡**で実バグ12件を修正（score型クラッシュ・受信IMAP無限ハング・
  ガードレールのドメイン検出漏れ・採点バッチ例外の巻き添え・重複排除・違反下書きの保存 等）。
  詳細はコミット履歴（PR #27/#28）と `eval/run_eval.py` の `robustness` ステージ。
- **接続リトライ**：sales@ IMAP を指数バックオフで最大3回試行（Xserverの間欠タイムアウト対策）。
  `SALES_IMAP_TIMEOUT`(30) / `SALES_IMAP_RETRIES`(3) で調整可。
- **eval 8ステージ全緑**：prefilter/draft/finalize/drafts/notion/contact/dedup/robustness。
  毎朝の eval gate で自動回帰チェック。
- **バックアップ（復元ポイント）**：リモートブランチ `backup/ses-matching-v1.0`（この安定版を指す）。
  戻し方：`git fetch origin && git checkout -B <作業ブランチ> origin/backup/ses-matching-v1.0`
  → そのままデフォルトへPR/マージすれば安定版に復帰。※タグはこの環境ではpush不可のためブランチで代替。

## ✅ 済（2026-07-12 追加）：Notionを簡潔化（縦に広げない）

- Notion候補ページは **要約＋マッチ度（スコア/7軸内訳）＋スキルシート要約＋ファイル名** のみ表示。
  **返信本文は載せない**（`_notion_blocks_from_result`）。返信全文は sales@ の下書きに入るため重複不要。
- eval `notion`（6/6）で「本文を含まない・要約/マッチ度/スキルシートを含む」を回帰チェック。
- 残：スキルシート原本(Excel/PDF)を**Notion内で直接開けるようにする**（Notionのファイルアップロードで添付）。
  現状はファイル名＋要約まで。原本の実ファイルは sales@ 下書きに添付する方向で対応予定（要・方針確認）。

## ✅ 済（2026-07-12 追加）：sales@ の下書きへ自動投入

- マッチした候補（高/中）の**返信下書きを毎朝 sales@ の下書き(Drafts)フォルダへ IMAP APPEND で自動保存**
  （`save_drafts_to_sales`／`\Draft` フラグ・**送信はしない**）。代表は下書きを開いて1社ずつ送信するだけ。
- 同一(案件×要員)は `drafts-log.jsonl`（gitignore）で**重複作成しない**。ガードレール違反(REOorGA混入等)はスキップ。
  宛先未確定は To 空＋本文冒頭に注記／属性フラグは本文冒頭に「代表確認」として付す。
- eval に `drafts` ステージ追加（MIME組み立て 10/10）。モックIMAPで保存2件・重複0を確認。
- **🔴 有効化に代表操作が必要**：GitHub Secret に `SALES_IMAP_HOST` / `SALES_IMAP_PASSWORD`
  （`SALES_IMAP_USER` 既定 sales@its-tokyo.com）を登録。下書きフォルダ名が `Drafts` 以外なら
  Variable `SALES_DRAFTS_FOLDER`（例 `INBOX.Drafts`）。未登録の間は自動でスキップ（他機能は通常稼働）。

## ✅ 済（2026-07-12 追加）：精度評価ハーネス＋精度改善（測定値つき）

- **評価ハーネス `eval/`**：ラベル付き合成データでパイプラインを計測（precision/recall/F1・帯一致）。
  決定論の段（prefilter/draft）は**APIキー不要で常時実行可**。退行時 exit 1。`ses-matching.yml` の
  eval gate で毎回自動チェック（候補がNotionに出る前に論理破綻を止める）。
- **R1 プレフィルタ誤爆修正**：ASCII短語（soc/ids/ips 等）の substring 誤爆で純NW案件が
  「両刀成立」で誤通過していた（`soc`∈associate 等）→ 語境界一致に変更。
  **precision 0.67→1.00・F1 0.80→1.00**（recall 1.00維持）。
- **R2 下書き安全網 `validate_draft`**：From違反・**REOorGA受信アドレス混入**・宛先ドメイン・署名欠落を
  決定論で検知（6/6）。`make_draft.py` は違反時に一度作り直し→残れば「送信不可」を明示。
- **R3 採点の監査可能化**：LLM採点に7軸 breakdown を必須化。内訳計とscoreのズレをダイジェストで⚠️。
- **R4 宛先自動化＋重複防止**：`extract_contact` で担当アドレスを保守的に自動抽出（6/6）。
  REOorGA/noreply/複数ドメインは「要・宛先確認」に倒す。`backfill_contacts` はLLMがreorga宛を
  入れてもデータ層で安全化（＝送信先事故の二重ガード）。`flag_duplicates`＋`proposed-log.jsonl`
  （gitignore）で既提案の 案件×要員 を再掲時に警告（2/2）。プレフィルタは境界/件名/大文字を追加し
  **18ケース F1 1.00**。eval gate は `--stage all`。
- **未実走**：段階②LLM採点の帯一致（`--stage scoring`）は OPENAI/ANTHROPIC キーが要るため本環境では
  未実行（コードは実装済み・キーがあれば即回せる）。→ 残タスク5。

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

### 2. 宛先(To)の自動抽出 ← ✅ 実装済（R4）／実データで精度確認が残
- [x] `extract_contact`＋`backfill_contacts` で担当アドレスを保守的に自動抽出・差し込み。
  配信リスト/REOorGA/noreply/複数ドメインは「要・宛先確認」に倒す（誤送信より安全側）。
- [ ] **実配信メールでの精度確認**：REOorGA配信の実際のFrom/署名の形に合わせ、拾えない/曖昧の割合を計測。
  必要なら署名ブロック検出（会社名近傍のアドレス優先）を足す。← IMAP接続後にサンプルで検証。

### 3. 採点精度の微調整（任意）
- [ ] 0点候補（例：セキュリティ実務なし＝両刀不成立）を candidates から除外徹底。
- [ ] 案件混線（配信案件×配信要員の組成、例「放送局向け」）をアクティブ案件に寄せる。
- [ ] 外国籍は**自動除外しない**（現状LLMが一部除外している）。属性は「代表確認」に統一。

### 4. 運用の型（合意済みの進め方）
- 毎朝自動 → Notionに候補が並ぶ → **代表がチャットで指示（この人出して／見送り）** → 村山名義で送信。
- 代表はPCをほぼ使わない。GitHubのPRマージ/実行トリガーはAI側で巻き取る（ただし
  Secret登録・Notionページ共有だけは代表操作が必要＝上記1）。

### 5. LLM採点の帯一致を実測（本環境ではキー無しで未実走）
- [ ] `OPENAI_API_KEY` を積んだ状態で `python eval/run_eval.py --stage scoring` を実行し、
  帯一致率（高/中/除外/flag）を計測 → `eval/README.md` の改善履歴に追記。
- [ ] 一致しないケースを `fixtures_scoring.jsonl` に足し、SYSTEM_PROMPT・`scoring.md` を調整して再計測。
  → **これが「採点精度を継続的に上げる」ループの回し方**。

---

## 再開方法（別セッション向け）
1. 本ファイルと `README.md` を読む。
2. 未完了は「残タスク1」の Notion有効化から。`NOTION_PAGE_ID` が登録されたら実行→ログ確認。
3. 実行ログの確認は GitHub Actions（ワークフロー `ses-matching.yml`）。`[notion]` 行と候補数を見る。
