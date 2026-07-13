# 逆方向：ITSの要員に案件を当てる（要員先行提案）

従来（`draft-on-demand.md`）は「**ITSの案件 × 配信で来た要員**」だった。
こちらは対の逆方向：「**配信で来た案件 × ITSのプロパー要員（KN 等）**」を提案する下書きを作る仕組み。

- ソース・鮮度5日・網羅・重複排除・**送信は必ず代表が手動**は従来と同じ（`README.md`／`sources.md`）。
- 生成は **LLMで書かせず、決定論のテンプレ差し込み**（`reply-template-offer.txt` ＋ 要員定義の MAIL-BLOCK）。
- 実体は `make_offer_draft.py`。ガードレール（From＝sales@固定・REOorGA混入禁止・宛先の保守的抽出）は
  `run_ses_matching.py` の既存関数をそのまま再利用（＝安全網は共通・二重実装しない）。

## 対象要員

- `要員_KN_PMOサポート.md`（KN／PMO補佐・プロジェクト推進支援）。スキルシート原本 PDF は
  `../../data/skillsheets/`（gitignore・個人情報）に置き、**提案時に添付**する。
- 別のプロパーを増やすときは `要員_〇〇_*.md` を同じ形式で追加し、`--engineer` で切り替える。

## 使い方（代表）

### ① 洗い出し（マッチ度検証）＋提案下書き＋Notion可視化

REOorGA配信の案件を `inbox-案件.md` に貼って（`inbox-案件.example.md` の形式・**配信日必須**）：

```bash
# マッチ度検証＋ダイジェスト＋提案下書き(.eml)を生成（Notionには出さない）
python make_offer_draft.py --inbox inbox-案件.md --date <今日 YYYY-MM-DD>
# ↑にNotion可視化を追加（『KN案件 YYYY-MM-DD』ページ＋提案トラッカーDB行）
python make_offer_draft.py --inbox inbox-案件.md --date <今日 YYYY-MM-DD> --notion
```

**やること（自動）**：
- 案件を「面談通過可能性（高/中/低）／KNに刺さる語／鮮度」で並べ、**5日超過は対象外**、
  技術専任寄りは「要確認」でフラグ。
- `digests/offer-digest-YYYYMMDD.md`（ダイジェスト）＋ `offer-candidates-*.json`＋
  **高/中・鮮度内の提案下書き `.eml`（KNスキルシートPDF添付済み）** を `digests/` に出力（すべて**gitignore**）。
- `--notion` 付きなら、親ページ配下に **『KN案件 YYYY-MM-DD』スナップショットページ** を作成し、
  高/中候補を既存 **『SES提案トラッカー』DB** に `KN × 〔案件〕`（ステータス=未送信）で行追加。
  → 従来方向（案件×要員）と**同じDBで一元管理**でき、未送信/送信済/見送りのカンバンで可視化できる。
  `NOTION_TOKEN`/`NOTION_PAGE_ID` 未設定ならNotionはスキップ（`.eml`／ダイジェストは出る）。

**やらないこと（人間＝代表）**：本命の最終確認と **送信**（`.eml` を sales@ で開いて手動送信・PDF添付は自動済み）。

#### contact@ から直接取り込む（自動・GitHub Actions）

案件を貼らずに、**従来と同じ受信箱 `contact@reorga.co.jp`（REOorGA）から直接**取り込んで選定できる。
NW/Sec用プレフィルタは通さず、**全件を要員KNの適合(offer_fit)で選定**する（逆方向は案件の型が違うため）。

```bash
# contact@ から取得 → KN選定 → 下書き.eml → Notion → sales@下書き保存（送信しない）
python make_offer_draft.py --source imap --engineer KN --notion --save-drafts
```

- 認証情報（`IMAP_HOST`/`IMAP_PASSWORD` 等）は **GitHub Secrets**。ローカルには置かない＝**実行はActions**。
- ワークフロー：**`.github/workflows/ses-offer-matching.yml`**（`workflow_dispatch` で手動実行。cronは
  ライブ検証後に既定ブランチマージで有効化）。従来 `ses-matching.yml`（8:30）と別ジョブ。**LLMキー不要**。
- 出力：`ses-offer-digest` アーティファクト＋Notion『KN案件 YYYY-MM-DD』＋sales@の下書き（`\Draft`）。

**氾濫防止のガードレール（重要）**：contact@ は案件と要員が混在し日数千件流れる。誤って大量の下書き/Notion行を
作らないよう、逆方向は次の3段で絞る：
1. **案件性フィルタ** `looks_like_case()`：募集/案件/参画/単価/常駐 等の案件マーカーが薄く、
   スキルシート系の語（要員配信）が濃いメールは**対象外**。
2. **役割必須** `offer_fit()`：PMO/PM補佐/IT事務/導入支援/サポートデスク等の**役割語（STRONG）が無い**メールは
   汎用スキル語（調整/資料作成/サポート）だけでは**中+に上げない**（＝誤爆させない）。
3. **件数上限** `OFFER_MAX`（既定30）：提案対象＝高/中・鮮度内をスコア降順で上限まで。超過は「今回見送り・要確認」でログ。
sales@下書き/Notion行/`.eml` はこの**絞り込み後の対象のみ**に作る。X-ITS-Key で実行跨ぎの重複も作らない。

### ② 個別の提案下書きを作る（1案件＝1下書き）

配信メールから **会社名・担当者・件名（と可能なら宛先）** を拾って：

```bash
python make_offer_draft.py \
  --subject "〔案件配信の件名〕" \
  --company "株式会社〇〇" --person "山田" \
  --to "tanto@example.co.jp" \
  --case-name "PMO補佐案件"
```

- `--to` 省略時は `--body`/`--body-file`（案件本文）から宛先を**保守的に自動抽出**（曖昧なら「要・宛先確認」）。
- 件名は自動で `RE:〔案件件名〕`（既存 Re:/Fwd: は剥がして付け直す）。
- 本文『配信にて頂きました〇〇について』の〇〇は `--case-name`（省略時は件名）。

### ③ スキルシートPDFを添付した送信可能な .eml を書き出す（任意）

```bash
python make_offer_draft.py --subject "..." --company "..." --person "..." --to "..." \
  --attach ../../data/skillsheets/KN_スキルシート.pdf --eml /tmp/KN_offer.eml
```

→ From/件名/本文＋**KNスキルシートPDF添付**入りの `.eml`。sales@ で開いて確認 → **手動送信**。
（`SALES_IMAP_*` を使う自動下書き投入は従来同様。PDF原本の自動添付は Notion/Drive 運用が前提＝`skillsheet-intake.md`。
 当面は代表が送信時に手動添付でも可。）

## 送信前チェック（代表）

- [ ] **From が ITSセールス**（`sales@its-tokyo.com`）／REOorGA受信アドレスになっていないか（最重要）
- [ ] **To が配信元担当のアドレス**か（配信リスト宛・REOorGA宛になっていないか）
- [ ] 件名 `RE:〔案件件名〕`・会社名・担当者名・案件名が正しいか
- [ ] **KNスキルシートPDFを添付したか**（提案時添付）
- [ ] 単価（48万・応相談）・稼働（即日〜）・勤務形態が案件と整合するか
- [ ] 案件側の属性条件（年齢/性別/国籍等）は**自動選別しない**（法令グレー・代表判断・本文に書かない）

## ガードレール（再掲・厳守）

- **From は `sales@its-tokyo.com` 固定**。REOorGA受信アドレス（`contact@reorga.co.jp`）からは絶対に送らない。
- **To は保守的に**。不明なら「要・宛先確認」のまま（アドレスを創作しない）。
- スキルシート原本（PDF＝個人情報）は **gitにコミットしない**（`data/skillsheets/`＝gitignore）。
- 資料に無い情報は捏造しない。**送信は必ず代表が手動**（AIは下書きまで）。

## 関連ファイル

- `make_offer_draft.py`……逆方向の下書き確定＋洗い出しの実体（共通エンジンの関数を再利用）。
- `reply-template-offer.txt`……差し込みテンプレ本体（`{会社名}{担当者名}{案件名}{要員サマリー}{署名}`）。
- `要員_KN_PMOサポート.md`……要員定義＋提案本文に挿入する MAIL-BLOCK（要員サマリー）。
- `examples/offer-sample-inbox.md`……動作確認用のダミー案件（`--inbox` で試せる）。
- `draft-on-demand.md`……従来方向（案件×配信要員）の対の手順書。
