# ITS合同会社 自社サイト（ポートフォリオ第1号）

`index.html` 1ファイルで完結する自社サイト。営業時の「作れる証明」兼リード獲得窓口。
戦略の正本は `docs/web-jutaku-strategy.md`。

## 公開手順（無料・約10分）

### 案A：GitHub Pages（最速）
1. GitHubで新しい**公開リポジトリ**を作る（例：`its-llc-site`）※この経営OSリポジトリとは分ける（内部情報を公開しないため）
2. `website/index.html` だけをそのリポジトリのルートにコピーしてpush
3. リポジトリの Settings → Pages → Branch: `main` / `(root)` → Save
4. 数分後 `https://<ユーザー名>.github.io/its-llc-site/` で公開される

### 案B：Cloudflare Pages（独自ドメイン運用ならこちら）
1. Cloudflare Pagesで「Direct Upload」→ `index.html` をアップロード
2. 独自ドメイン（例：its-llc.jp）を取得して接続（ドメイン代 年約¥1,500〜3,000のみ）

## 公開後にやること
- [ ] 営業文面（`templates/outreach-web.md`）のURL欄にサイトURLを記入
- [ ] Googleビジネスプロフィールに登録（無料・地域検索対策）
- [ ] 実績が1件できるたびに「制作実績」セクションを追加する

## 更新メモ
- 連絡先は現在Gmail。独自ドメイン取得後は `info@〜` に差し替える
- 価格改定（実績3件後）の際は料金カードと戦略書を同時に更新する
