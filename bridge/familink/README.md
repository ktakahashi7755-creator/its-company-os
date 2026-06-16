# Familink 紐付けキット（経営OS ⇄ Familink開発リポジトリ）

経営AIエージェントチーム（CPO/CTO/取締役会）と、GitHubで動くFamilink開発を「GitHubを共通の正本にして」つなぐためのファイル群。

## 配線の考え方
- 経営OS（its-company-os）：**何を・なぜ・優先順位**を決める（CPO_Product_AI / CTO_Technology / AI取締役会）。
- Familinkリポジトリ：**どう作るか**を実装する（既存のCLAUDE.md＋skills）。
- 接点：**GitHub上の共有ドキュメント**（roadmap / design-principles / decisions）。両チームが同じファイルを読む＝共通の記憶。

## 導入手順（Familinkリポジトリ側でやる）
1. `CLAUDE_追記.md` の中身を、Familinkリポジトリの既存 `CLAUDE.md` の冒頭付近に貼る。
2. `docs/product-roadmap.md` `docs/design-principles.md` `docs/product-decisions.md` `docs/HANDOFF.md` を、Familinkリポジトリの `docs/` に置く。
3. コミット。以後、Familink開発のClaude Codeは着手前にこの2つ（roadmap/design-principles）を必ず読む。

## 経営OS側の対応
`skills/familink-dev/SKILL.md` と CPO/CTO がこの配線を前提に動く（このリポジトリの roadmap を正本として参照）。

## 同期のルール
- 優先順位を変えたい → 経営OSのCPO/取締役会が `product-roadmap.md` を更新。
- 実装側が仕様を変えたい → `product-decisions.md` に論点を書き、CPOの判断を待つ（勝手に変えない）。
