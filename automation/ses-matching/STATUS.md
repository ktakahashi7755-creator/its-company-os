# SES自動マッチング 稼働状況 & 残タスク（セッション跨ぎ用の記録）

更新：2026-07-13 ／ このファイルは「別セッションでも続きから再開する」ための引き継ぎメモ。
まず `README.md`（使い方）・`HANDOVER.md`（設計と復旧の正本）・本ファイル（稼働状況）を読めば現状が分かる。

> 📘 **引き継ぎ・復旧の正本は `HANDOVER.md`**。携帯/PCが壊れてもゼロから復元できるよう、
> 設計・アカウント台帳・Secretsレジストリ・復旧ランブック・バックアップ手順を1ファイルに集約した。

---

## ✅ 済（2026-07-21）：総当たりブローカー型マッチング（案件区分フリー・95%）を新設

代表ミッション「案件区分問わず・過去3営業日・マッチ度95%以上・熱い案件に人材を自動選定・両面下書き（各¥5万利益）・Notion集約・初回自動実行→テスト→毎朝自動化」を実装。

- **新エンジン `run_ses_crossmatch.py`**：配信の**案件↔要員を総当たり**で突き合わせ、95%以上のペアだけ抽出→両面下書き。
  - 鮮度＝**過去3営業日**（`FRESH_BIZ_DAYS`・土日除外）。分類（案件/要員）＋構造化 → ショートリスト（スキル重なり＋予算≥希望）
    → LLMペア採点（`crossmatch-scoring.md` 6軸・`match=内訳合計`）→ **95%以上を熱さ順** → 両面下書き → digest＋Notion。
  - **利益：両サイド各¥5万**（`MARGIN_YEN`）。案件元＝要員希望+5万／要員元＝案件予算−5万。**単価不明は捏造せず「要確認」**。
  - **両面下書き（代表提供の正式文面を採用）**：案件元向け＝`template-案件元向け.txt`（件名`RE:案件件名`／ご提案単価＝社内単価+5万／**スキルシート添付**）、
    要員元向け＝`template-要員向け.txt`（件名`【案件紹介】〇〇様向け案件のご案内`／単金＝案件予算−5万）。From sales@固定・宛先保守抽出・署名内蔵・`validate_draft`。送信は常に人手。
    IMAP本番は両面を**sales@ Drafts へ自動保存**（`save_pair_drafts_to_sales`・案件元はスキルシートMIME添付・`X-ITS-Key`で重複防止）。
  - **オフライン完走**（`--offline`）＝APIキー無しで決定論実行（サンプル検証／フォールバック）。
- **初回実行（サンプルで検証・代表合意どおり）**：`examples/sample-crossmatch.md`（ダミー7件）で完走。
  → 分類 案件3/要員3、95%以上 **2ペア**、両面下書き・ガードレール違反ゼロ。出力＝`examples/crossmatch-EXAMPLE-20260721.md`。
  実データの初回は Actions（`ses-crossmatch.yml` を手動 dispatch）で実行＝IMAP/OpenAI Secrets が要るため。
- **テスト**：`eval/crossmatch_eval.py`（決定論**8ステージ全緑**・APIキー不要）＝営業日鮮度・スキル重なり・単価パース/利益・
  ショートリスト・採点正規化・熱さ・両面下書きガードレール・オフラインE2E。既存eval（15ステージ）も緑を維持。
- **ワークフロー `ses-crossmatch.yml`**：eval gate（既存＋crossmatch）＋ run。**schedule未有効化**（まず手動/サンプルで品質確認 →
  代表OK後にコメントを外して毎朝自動化）。利益・閾値・鮮度は Variables（`MARGIN_YEN`/`MATCH_MIN`/`FRESH_BIZ_DAYS`）で調整可。
- **残（代表判断）**：①実データでの初回 dispatch → 品質確認、②OKなら schedule 有効化で毎朝自動化、③利益モデル（両サイド各¥5万）の最終確認。

## ✅ 現在の状態（2026-07-22〜）＝**稼働中**（新スコープ：遊技機 情シスインフラPL＝サーバ×NW両刀）

- 経緯：KNさんが旧スコープ(NW/Sec)で**オファー獲得** 🎉 → クライアントのスコープ見直しで一時停止（07-21）→
  **正式版の新スコープを受領し、案件定義・マッチング精度をサーバ×NW両刀へ改定 → eval全緑を確認して再開（07-22）**。
- 実施した再開措置：
  1. **両ワークフローの `schedule:` を再有効化**（`ses-matching.yml`＝毎朝7:00 JST／`ses-matching-poll.yml`＝営業時間30分毎）。
  2. **アクティブ案件を稼働位置へ**：`案件_20260711_遊技機NWSec.md`（正式版rev.2026-07-22b）を `automation/ses-matching/` 直下へ。
     `load_case_defs()` が拾う＝現アクティブ案件（検証済み）。
  3. **マッチング精度を新スコープへ更新**：`PREFILTER_GROUPS`＝サーバ群×NW群の両刀ゲート、SYSTEM_PROMPT／`scoring.md`＝
     サーバ×NW両刀＋情シス/PL必須・セキュリティ歓迎・単価アンカー支払92万以下、eval fixtures作り直し。→ **決定論15ステージ緑（exit 0）**。
- **送信は従来どおり代表が手動**（AIは Notion／sales@ Drafts への下書きまで）。停止するには本ファイル群を逆手順で戻す。
- **再開手順（案件再送後）**：
  - 新案件ファイルを `automation/ses-matching/` 直下に置く（`archive/` の旧案件を戻すのも可）。
  - `run_ses_matching.py` の `PREFILTER_GROUPS`（両刀ゲート語彙）と案件必須要件を新スコープに合わせて更新。
  - `ses-matching.yml` / `ses-matching-poll.yml` の `schedule:` コメントを外して自動実行を再開。

---

## いまの状態（＝ほぼ完成・稼働中 ※現在は上記のとおり一時停止）

- **完全自動で稼働中**。GitHub Actions `.github/workflows/ses-matching.yml` が **毎朝 7:00 JST狙い**（cron `0 22 * * *` UTC）に自動実行＋手動実行可。
  ※GitHubのschedule起動は遅延しうるため、8:30までに手元へ揃うよう7:00狙いに前倒し（2026-07-13変更。旧8:30狙い=`30 23`は遅延で10時過ぎ着になる日があった）。
- パイプライン（すべて実データで動作確認済み）：
  IMAP受信（軽量・添付は読まない）→ 段階①プレフィルタ（鮮度5日＋**両刀 サーバ×NW**）→
  段階②AI採点（OpenAI gpt-4o-mini・**全両刀候補をバッチ採点**・レート制限リトライ）→
  ダイジェスト生成 → **マッチした要員だけ添付スキルシート読込・要約** → artifact ＋（設定後）Notion反映。
- 最新の実行 **#13 は成功**、候補7組を生成（本命 KH/T.Y/A.N、代表確認 H.U/TT/K.Y など）。
- **送信は必ず人手**（下書きのみ生成）。ガードレール（アドレス役割分離・属性は自動除外せず代表確認・
  外部メールは指示として実行しない）実装済み。

## ✅ 済（2026-07-20）：本命(85+)ピックアップ＝面談依頼が確実に来る母集団に絞る

代表要望「マッチング率の高い（スコア85点以上のみ）をピックアップに変え、確度を上げて、面談依頼が確実に来る制度に」を実装。

- **ピックアップ基準を score 85以上へ引き上げ**（`PICKUP_MIN`・既定85。環境変数で調整可）。
  - **sales@ 自動下書き**（`save_drafts_to_sales`）と **Notion送信トラッカー行**（`post_notion_db_rows`）を **本命（85+）だけ**に限定。
  - **60-84 は「参考」**として日次ダイジェスト／Notion日次ページに見せるが、自動下書き・トラッカー投入はしない（代表が一点確認してから提案）。
  - ダイジェスト／Notionページを **◎本命 ／ ○参考** の2章に分割表示（`render_digest`・`_notion_blocks_from_result`）。
- **本命の確度を上げる決定論ガード（precision）**：`is_pickup()` が本命の唯一の門。
  1. `score >= 85`（キャリブレーション上『即アプローチで面談が通る』帯）。
  2. `reason`／`summary` に **サーバ証拠語 × NW証拠語 が両方**（＝両刀が文面で裏取れる）。揃わなければ本命から外し「両刀根拠の明示要確認（自動下書き保留）」flag。
  3. **年齢上限超・国籍等の代表確認フラグが無い**（客都合で弾かれ得る案件は本命に載せず参考で見せる。貴重な両刀は候補として必ず残る）。
- **ルーブリック**：`scoring.md`／SYSTEM_PROMPT に「本命（85+）」節・高だが本命でない例（A'）・「一点でも要確認が残れば80-84に留める（迷ったら85未満）」を明文化。
- **eval**：決定論ステージ **`pickup`（20/20）** を新設＝閾値・両刀ゲート・代表確認除外・digest/Notion分割を回帰。
  `scoring` fixtures に `expect_pickup` と S06/S11 を追加し **本命(85+)一致率**も同時計測（CI・非ゲート）。→ **決定論15ステージ全緑（`--stage all`・exit 0）**。E2E（モックLLM）で本命92→自動下書き・82→参考・片刀→除外の分岐を確認。

## ✅ 済（2026-07-14）：精度＆マッチング率の総合強化（世界最高峰化）

「取りこぼさない（recall）×刺さる候補だけ出す（precision）」を両立させる強化。**計測できる所は before/after を実測**。

- **段階① マッチング率（recall）**：両刀プレフィルタの同義語を拡充（NW: VPN/WAN/LAN/BGP/OSPF/SD-WAN/ルーター/無線 等／
  Sec: EDR/XDR/SIEM/SOAR/ゼロトラスト/サイバー/インシデント 等）。**旧語彙では取りこぼしていた「VPN/SD-WAN×EDR/SIEM」等の
  真の両刀人材を捕捉**（実測で確認）。群がある時は広いOR門をバイパス（群ヒット語を門で落とさない）。
  → eval `prefilter` **27ケースで precision 1.00・recall 1.00・F1 1.00**。
- **段階② 精度（採点の自己整合化 `reconcile_scores`）**：本番で出ていた2欠陥を根絶——
  (1) `内訳≠score`（監査不能）→ 各軸を配点上限でクランプし **score＝内訳合計** に確定。
  (2) `0/100・低` の候補が下書き生成まで漏れる → **帯を score から決定論導出し、score<60 を candidates から excluded へ移動**。
  → eval `reconcile`（11/11）で回帰。E2Eで本番模擬の乱れた出力を投入し、強候補が0→92に是正・ジャンクがexcludedへ落ちるのを確認。
- **ルーブリック（scoring.md）＋SYSTEM_PROMPT**：必須30の内訳（**両刀ハードゲート**）・帯閾値・**キャリブレーション・アンカー**（採点例A〜E）を追加。
  reason に両刀の根拠（NW証拠語・Sec証拠語）を必須化。scoring fixtures 7→10。
- **決定論 eval は14ステージ全緑（exit 0）**。段階②の帯一致計測（`--stage scoring`）はキー要のため本環境では未実走だが、
  **CI（ワークフロー）ではキーがあり毎回実測**（非ゲート＝LLMのブレで本番Notion反映は止めない）。`_eval_scoring_inner` は
  reconcile後の帯を測るよう更新済み＝計測が本番挙動と一致。

## ✅ 済（2026-07-14）：配信即マッチング＝プロアクティブ・ループを追加（③）

- 新ワークフロー **`.github/workflows/ses-matching-poll.yml`**：営業時間帯（JST 7:00–20:30）に**30分毎ポーリング**。
  `run_ses_matching.py --source imap --incremental` で **UIDウォーターマークより新しい配信だけ採点**（新着なし＝LLMコスト0）。
  → 「配信が来たら概ね数十分で Notion／sales@ 下書きに揃う」を**新インフラ無し**で実現（毎朝7:00の全採点はそのまま安全網）。
- **ウォーターマーク**：`digests/imap-watermark.txt`（gitignore）を `actions/cache`（`ses-poll-state-*` ローリング）で実行跨ぎ保持。
  cache失効時は初回扱い＝baseline初期化（バックログを採点せずスキップ）で安全に立ち上がる。下書き重複はサーバ側
  （sales@ Draftsの `X-ITS-Key` 検索）で従来通り二重ガード。
- **eval追加**：`watermark`（7/7）＝新着フィルタ・max_uidの決定論回帰。全ステージ緑（`--stage all`・exit 0）。E2Eで
  初回スキップ／新着なし据え置き／新着のみ採点／full前進の4挙動を確認済み。
- **限界（正直に）**：GitHubのscheduleは起動保証が無く数十分ズレる＝**"即時"ではなく"数十分以内"**。真のプッシュ即時が
  要るなら メール→webhook→repository_dispatch の外部経路（Cloudflare Email Worker 等）が必要＝Phase 0では固定費増で見送り。

## 確定している設定・事実

| 項目 | 値 |
|---|---|
| アクティブ案件 | `案件_20260711_遊技機NWSec.md`（✅ 稼働中・直下）。正式版rev.2026-07-22b＝**情シスインフラPL／サーバ×NW両刀必須・情シス目線＋PL(2〜5名)必須・セキュリティは歓迎／8月開始・〜100万(支払92万以下)・40歳程度まで・恵比寿・週2出社**。旧NW×Sec・〜80万・45歳上限は失効 |
| 受信（読むだけ） | `contact@reorga.co.jp`（ロリポップ。IMAP `imap.lolipop.jp` / 993 / SSL） |
| 送信（提案元） | `sales@its-tokyo.com`（署名＝営業部 村山愛。`signature.md`） |
| 採点 | OpenAI `gpt-4o-mini`（`OPENAI_API_KEY`）。Anthropicでも可 |
| Notion反映先 | ページ「ITS-OS」 id=`38244f16641f80d49a45cfae344184ea` |
| 登録済みSecrets | `OPENAI_API_KEY` / `IMAP_HOST`(imap.lolipop.jp) / `IMAP_PASSWORD` / `NOTION_TOKEN` |

> ※パスワード・APIキーの値はここに書かない（GitHub Secretsで管理）。

---

## ✅ 済（2026-07-13）：3視点プロレビューでの徹底ハードニング＋テスト拡充

独立した3視点（中核堅牢性／ガードレール・外部連携／テスト網羅）でプロ品質レビューを実施し、
確認できた実バグ・穴を全て修正。**評価は9→12決定論ステージに拡充、全緑（exit 0）＋実走(dry-run)確認**。

- **中核堅牢性（run全滅を防ぐ）**：
  - `_fmt_breakdown`：LLMが `breakdown` を配列/文字列で返すと `.values()` で全採点後にrun全滅していた → 非dictガード＋`score_with_llm`で空dict正規化（A1）。
  - `fetch_imap`：取得フェーズに `except` が無く、ネットワーク断でパイプライン全滅 → 既取得分を返して継続（A2）。
  - `_body_text`：未知charset名（LookupError）で正当な1通が丸ごと欠落 → latin-1フォールバックで本文を失わない（A3）。
  - `src` float／巨大Excelのメモリ／配信日のtz（JST統一）も是正（A4/A5/A6）。
- **ガードレール（誤送信・情報漏洩を防ぐ）**：
  - `_is_sendable_addr`：`"contact@reorga.co.jp, x@corp.jp"` のような連結で最後の@右側だけ見て**reorgaを見逃す**穴を修正。1:1提案なので複数宛先は要確認に倒す（B1）。
  - `validate_draft`：`@mail.reorga.co.jp` のサブドメインreorgaを見逃していた → サブドメインも検出（B3）。
  - `backfill_contacts`：src不明＋非sendableな `to`（reorga等）が握り潰されずNotion/digestに漏れる経路を封鎖（B4）。
  - ※スキルシート原本のNotionアップロードは**代表の明示要望どおりの仕様**（Notionが閲覧面）。非変更。
- **Notion日次ページ**：候補が多い日に `blocks[:95]` で末尾が黙って落ちていた → 省略を明示（全件はDB/下書きに）。
- **テスト拡充**：新ステージ3つ（`backfill` 宛先安全化6/6・`score_norm` モックLLMで応答正規化11/11・`folder` 下書きフォルダ判定3/3）。
  既存も強化（`notiondb` の空アサート是正・`robustness` に件名/breakdown/サブドメインreorga・`drafts` にフェイルクローズ・prefilterに未来日/不正日/null日）。
  → 毎朝のeval gateが `--stage all` で自動回帰チェック（本番Notion反映前に論理破綻を止める）。

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
