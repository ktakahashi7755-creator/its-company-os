# SESマッチング・システム（運用の全体像）

ITS合同会社のSESマッチングを **1つのシステム** として運用するための地図。
サーバは持たない（固定費ゼロ・Phase 0）。GitHubを土台に、投入→マッチ→下書き→送信を回す。

---

## 構成（5つの部品）

| 部品 | 実体 | 役割 |
|---|---|---|
| **投入UI** | GitHub Issue フォーム（`新案件` / `新人材`） | スマホで貼るだけ。会話不要 |
| **DB（台帳）** | `data/cases.json` / `data/talents.json` | 案件・人材の正本。投入で追記される |
| **マッチエンジン** | `match_core.py`（決定論）＋ 日次 `run_ses_matching.py`（LLM） | 両刀・年齢・粗利で採点 |
| **運用画面** | `dashboard.html`（`build_dashboard.py` が台帳から生成） | 本命・候補・台帳・KPIを実データで表示 |
| **出力** | `sales@` の下書き ＋ Notion トラッカー | **人間が確認して手動送信**（自動送信しない） |

---

## 日々の使い方

### 案件が来たら
1. GitHub → Issues → New issue → **「新案件」** にJDを貼って Submit
2. 数分で設定PR（＋1タップPRリンク）が立つ → 中身を確認して **Merge**
3. その案件が「現行案件」になり、要員台帳と自動マッチ

### 人材が来たら
1. GitHub → Issues → New issue → **「新人材」** にスキルシートを貼って Submit
2. 台帳登録＋案件マッチ＋提案下書きのPRが立つ → 確認して **Merge**
3. 以後、案件投入時のマッチ対象になる

### 提案する
- `dashboard.html` で本命・候補を確認 → `sales@` の下書きを開く → 宛先・添付・年齢非表示を確認 → **手動送信**
- チャット（ここ / ChatGPT）に貼って即マッチさせることも可能（`CHATGPT-運用プロンプト.md`）

---

## ガードレール（常時・自動適用）

- **自動送信しない**（下書きのみ・最終送信は代表）
- **客先文面に年齢を出さない**（MAIL-BLOCK・サマリーで自動除去）
- **年齢ハード上限**を明示した案件は、超過を自動除外（跨ぐ/不明は本命保留）
- **粗利¥8万死守**（クライアント上限 − 要員希望 が不足はフラグ）
- **両刀の軸ヒット必須**（片刀は本命にしない）

---

## 品質保証

- すべての決定論ロジックは `eval/run_eval.py`（全ステージ）で回帰検証。受付ワークフローは投入のたびに eval ゲートを通す。
- `python eval/run_eval.py --stage all` … 案件受付・人材受付・マッチ・ダッシュボード生成まで一括検証（APIキー不要）。

---

## ファイル早見

```
automation/ses-matching/
├── match_core.py          決定論マッチ中核（両刀/年齢/粗利）
├── intake_case.py         新案件受付（→active-case.json / cases.json / 案件_*.md）
├── intake_talent.py       新人材受付（→talents.json / 人材_*.md / 提案下書き）
├── build_dashboard.py     台帳→dashboard.html 生成（実データ・投入は実フォーム直リンク）
├── run_ses_matching.py    日次LLMマッチ（案件×受信要員メール→sales@下書き＋Notion）
├── run_ses_crossmatch.py  総当たりブローカー（案件↔要員・両面下書き）
├── data/cases.json        案件台帳（DB）
├── data/talents.json      人材台帳（DB）
├── dashboard.html         運用画面（自動生成物）
└── eval/                  回帰テスト
.github/
├── ISSUE_TEMPLATE/新案件.yml・人材.yml   投入フォーム
└── workflows/ses-case-intake.yml・ses-talent-intake.yml・ses-dashboard.yml
```
