# 受け渡しフロー（経営OS → Familink開発）

優先順位が「実際の実装」になるまでの流れ。

## 基本（今日から・コードもActions不要）
1. ITS経営OSのCPO_Product_AIが次の優先を決め、`docs/product-roadmap.md` を更新（このリポジトリにコミット）。
2. Familink開発のClaude Codeを開く → CLAUDE.md経由で roadmap と design-principles を読む。
3. ロードマップ上位の項目を、design-principles に従ってDBスキーマ先行で実装 → PR。
4. 仕様変更が必要なら `docs/product-decisions.md` に論点 → CPO/取締役会へ。

## タスク単位で回す場合（GitHub Issue）
Issueテンプレ：
```
タイトル：[Familink] <機能名>
背景（roadmapのどれか）：
受け入れ基準（完了の定義）：
スキーマ影響：有/無
design-principles順守チェック：✓
```

## 自動化したくなったら（Phase 2以降・任意）
- `/install-github-app` でGitHub Actionsを入れ、Issue/PRで @claude を呼ぶと自動実装・レビューを試せる。
- いまは不要。まずは上の「基本」で手動受け渡しから。
