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

---

# ドキュメントのNotion自動同期（営業進捗・財務・経営）

経営OSのMarkdownを**Notionページへ綺麗にミラー同期**する仕組み。表・見出し・箇条書き・太字までNotionブロックに変換する。追記ではなく**ミラー（毎回クリア→最新で再生成）**なので、Notion側は常にファイルの現在値。

## 構成
- `automation/sync_to_notion.py` … Markdown→Notionブロック変換＋ミラー同期（標準ライブラリのみ）
- `automation/notion-sync.config.json` … `file→page_id` のマッピング（page_idは秘密ではない）
- `.github/workflows/notion-sync.yml` … 対象ファイルのpushで自動実行＋手動実行

## セットアップ
1. Notionインテグレーションのトークンを `NOTION_TOKEN`（Secret）に登録（取締役会と共用可）。
2. **同期先ページをNotionで1つずつ作成**し、各ページの「接続」にインテグレーションを追加（共有）。
3. 各ページURL末尾の32桁IDを `notion-sync.config.json` の対応する `page_id` に記入してpush。
4. 以降、対象ファイルをpushすると自動でNotionへ反映。手動はActionsタブ →「Notionへ自動同期」→ Run workflow。

## 使い方（ローカル確認）
```
python automation/sync_to_notion.py --file data/営業進捗シート.md --dry-run   # 変換結果を確認（ネットワーク不要）
NOTION_TOKEN=xxx python automation/sync_to_notion.py                          # 実同期
```

## 対応Markdown
見出し(#〜###)／表(GFM)／箇条書き・番号リスト／引用(>)／区切り(---)／コードフェンス／インラインの **太字**・`コード`・[リンク](url)。

## 安全・前提
- **財務(`finance/`)はNotionが非公開（自分専用・共有なし）である前提で同期する**（2026-06 高橋承認済み）。Notionの共有設定を緩めないこと。
- page_id未設定のエントリは自動スキップ。トークンはSecret管理（コードに直書きしない）。
- これは整形・反映のみ。お金・法務の行動はしない。

## 手で貼る場合（同期を使わないとき）
各 `.md` の**生のMarkdownをコピー**してNotionに貼ると、Notionが自動変換（表・見出し・リストはそのまま整形）。1ファイル丸ごと貼れば綺麗に反映される。

---

## コスト
1日1回のSonnet呼び出し。入力は数千トークン、出力〜1,800トークン程度なので**1日あたり数円規模**（API課金）。GitHub Actionsはプライベートでも無料枠内で収まる想定。Notion同期はAPI課金なし（GitHub Actions実行のみ）。

## 安全・前提（重要）
- 生成するのは**ブリーフィング（助言）**。自動で送金・契約・申告などの**行動はしない**。
- 税務・法務の最終判断は税理士・弁護士へ。スクリプトもその旨を出力に添える設計。
- APIキー等は必ずGitHub Secretsで管理（コードに直書きしない）。
- Phase 0フィルター（「8月の生存と健全化を脅かさないか」）をプロンプトに内蔵。
EOF
echo "README done"