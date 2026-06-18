# 毎朝のAI取締役会 自動化（レベル2）

GitHub Actionsで毎朝、AI取締役会のブリーフィングを生成し、Notion / LINE / Webhook に投稿する骨組み。
**これは「助言ブリーフィングの生成と投稿」だけを行う。** お金・法務に関わる行動は取らない（人間がループに残る）。

## 構成
- `.github/workflows/morning-board.yml` … スケジュール実行（既定 7:00 JST）＋手動実行
- `automation/run_board_meeting.py` … 経営OSの状態を読み→Claude APIで取締役会→投稿
- `automation/requirements.txt` … 依存（anthropic）
- `automation/daily-input.example.md` … 前夜に任意で埋める当日インプットの雛形

## セットアップ手順

### 1. このOSをGitHubの**プライベート**リポジトリに置く
`its-company-os` をプライベートリポジトリとしてpush（経営・財務情報が入るため必ず非公開）。

### 2. シークレットを登録（Settings → Secrets and variables → Actions）
- `ANTHROPIC_API_KEY`（必須）… Claude APIキー
- 任意：`NOTION_TOKEN` `NOTION_PAGE_ID`（Notion投稿）
- 任意：`LINE_CHANNEL_ACCESS_TOKEN` `LINE_USER_ID`（LINE投稿）
- 任意：`WEBHOOK_URL`（Slack / LINE WORKS 等のIncoming Webhook）
- 任意（Variables側）：`ANTHROPIC_MODEL`（未設定なら `claude-sonnet-4-6`。重い判断は `claude-opus-4-8` に変更可）

投稿先は設定したものだけ動く（未設定はスキップ）。**まずはNotionだけでOK。**

### 3. Notionの準備（一番ラク・推奨）
1. https://www.notion.so/my-integrations で内部インテグレーションを作成 → トークンを `NOTION_TOKEN` に。
2. 投稿先にしたいNotionページを開き、「接続」からそのインテグレーションを追加（共有）。
3. ページURL末尾の32桁IDを `NOTION_PAGE_ID` に。
→ 毎朝そのページに「AI取締役会 日付」の見出しで追記される。

### 4. LINEの準備（任意・Notifyは廃止済みなのでMessaging API）
1. LINE公式アカウント＋Messaging APIチャネルを作成（LINE Developers）。
2. チャネルアクセストークンを `LINE_CHANNEL_ACCESS_TOKEN` に。
3. その公式アカウントを自分で友だち追加し、自分の userId を `LINE_USER_ID` に。
   ※無料枠は月200通まで。自分だけへの通知なら十分。
（Slack / LINE WORKS を使うなら、Incoming Webhook URL を `WEBHOOK_URL` に入れる方が簡単）

### 5. スケジュール調整
`morning-board.yml` の cron はUTC。既定 `0 22 * * *` = 7:00 JST。
時刻を変えるならcronを編集（例 6:30 JST = `30 21 * * *`）。
※GitHubのスケジュールは混雑時に数分〜遅延あり。リポジトリが60日無活動だと自動停止する点に注意。

### 6. テスト実行
Actionsタブ →「毎朝のAI取締役会」→ Run workflow（workflow_dispatch）で手動実行。
ログに議事録が出て、設定済みの投稿先に届けば成功。

### 7. 当日インプット（任意で精度UP）
`automation/daily-input.example.md` を `automation/daily-input.md` にコピーして前夜に記入・push（または手動編集）すると、翌朝の取締役会がその内容（論点含む）を踏まえる。空でも動く。

## コスト
1日1回のSonnet呼び出し。入力は数千トークン、出力〜1,800トークン程度なので**1日あたり数円規模**（API課金）。GitHub Actionsはプライベートでも無料枠内で収まる想定。

## 安全・前提（重要）
- 生成するのは**ブリーフィング（助言）**。自動で送金・契約・申告などの**行動はしない**。
- 税務・法務の最終判断は税理士・弁護士へ。スクリプトもその旨を出力に添える設計。
- APIキー等は必ずGitHub Secretsで管理（コードに直書きしない）。
- Phase 0フィルター（「8月の生存と健全化を脅かさないか」）をプロンプトに内蔵。

---

## 営業進捗のNotion自動反映

`data/` の営業シートをNotionページへ**自動ミラー**する仕組み（取締役会とは別）。

### 構成
- `.github/workflows/sync-pipeline-notion.yml` … `data/pipeline.md` `data/bp-list.md` `data/partners.md` への push で自動実行＋手動実行。
- `automation/sync_pipeline_to_notion.py` … 上記Markdownテーブルを読み、Notionの表ブロックに変換して反映。

### 仕組み（重要）
- **ミラー方式**：実行のたびに対象ページの既存ブロックを全削除→最新内容で書き直し。常に最新シートの鏡になる（追記の重複なし）。
- このため、対象ページは**この営業ミラー専用のページ**を用意すること（他のメモと同居させない）。

### セットアップ
1. `NOTION_TOKEN` は朝会と同じものでOK（同じインテグレーション）。
2. 営業ミラー専用のNotionページを新規作成し、インテグレーションを「接続」で共有。
3. そのページの32桁IDを `NOTION_PIPELINE_PAGE_ID`（Secrets）に登録。
   - 未設定の場合は `NOTION_PAGE_ID` にフォールバックするが、朝会ページと共用するとブロックが消されるため**専用ページ推奨**。
4. シートを編集してpushすると自動反映。Actionsタブ →「営業進捗をNotionへ反映」→ Run workflow で手動実行も可。

### 手元で動かす（任意）
```
NOTION_TOKEN=xxx NOTION_PIPELINE_PAGE_ID=yyy python automation/sync_pipeline_to_notion.py
```

### 安全・前提
- これは**シート内容の転記のみ**。お金・法務の判断や数値の補完はしない（シートにある内容をそのまま反映）。
- 資料にない金額は反映されない（シート側で空欄管理のまま）。