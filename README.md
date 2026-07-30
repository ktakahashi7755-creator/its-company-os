# ITS合同会社 統合経営OS（its-company-os）

ITS合同会社を**Claudeで経営する**ための単一ワークスペース。成長計画（SES・AI受託・Familink・3年バイアウト）と、足元の税務・財務管理を1つに統合。

## 動かし方
### Claude Codeで経営する
このフォルダをプロジェクトとして開く。`CLAUDE.md`（マスター）が最初に読まれ、Claudeは「安定化→成長→出口」の順序と優先順位、ガードレールに従って動く。タスクに応じて `skills/` の該当SKILL.mdが参照される。

### Notionで管理する
`docs/` の各ファイルをそのまま貼る（Markdownはネイティブ変換）。

## まず読む順番
1. `CLAUDE.md` … 現在地・順序・優先順位（マスター）
2. `docs/action-plan.md` … いま何をやるか（Phase 0が最優先）
3. `finance/TODO_緊急_税務.md` … 8月の動かせない期限

## 構成
```
CLAUDE.md              マスター（会社の頭脳）
docs/                  business-plan / action-plan / roadmap / financial-model / exit-plan / kpi
                       cache-automation-strategy（24時間キャッシュマシン戦略の正本）
skills/                tax-compliance / finance-cfo / ses-sales / ses-ops / ai-jutaku /
                       familink-dev / familink-launch / management-meeting
skills/executives/   AI経営本部（10 CXO）／ skills/board-meeting/ AI取締役会
templates/             提案・見積・スキルシート・朝会
finance/               税務/経理の運用データ（00〜07・金額は空欄管理・CFO指示書）
data/                  BP・協力会社・パイプライン
```

## 順序（迷ったらここに戻る）
**① 安定化（決算・申告・未払い）→ ② 成長（SES＋Familink）→ ③ 出口（バイアウト）。**
足元の健全化は出口のステップ1。①が割れている間は②③を全開にしない。

## 重要な注意
- Claudeは税理士・弁護士ではない。申告・納税・休眠/整理/破産・契約の最終判断は専門家へ。
- 資料がない金額は空欄管理（勝手に補完しない）。
- Familinkの保有形態は専門家に確認する論点（distressedなITSに巻き込まない）。
- 数値は検証すべき計画値。
