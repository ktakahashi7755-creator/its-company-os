# SETUP — Claude Codeで使い始める手順

リポジトリ作成は前提ではない。Claude CodeはローカルフォルダをそのままはOK。
git/GitHub化はバックアップと自動化のための推奨ステップ。

## A. 最小で使い始める（GitHub不要・今すぐ）
1. its-company-os.zip を解凍
   - Mac/Linux: `unzip its-company-os.zip -d ~/projects/`
   - Windows: 右クリック→展開、または `Expand-Archive its-company-os.zip`
2. （未導入なら）Claude Codeを入れる ※Node.js必要
   `npm install -g @anthropic-ai/claude-code`
3. フォルダで起動（CLAUDE.mdが自動で読まれる）
   `cd its-company-os && claude`
4. 最初の一言で確認
   - 「CLAUDE.mdを読んで、今のフェーズと最優先を3行で」
   - 「skills/board-meeting/SKILL.md に従って今朝の取締役会を回して」

## B. 推奨：git化＋プライベートGitHub
5. `git init && git add . && git commit -m "initial: ITS経営OS"`
6. `gh repo create its-company-os --private --source=. --remote=origin --push`
   - 財務情報が入るので必ず private
   - gh未認証なら先に `gh auth login`
   - Web UIで作る場合: 空のprivateリポジトリ作成 → `git remote add origin <URL>` → `git push -u origin main`
7. （自動化する時）GitHub Settings → Secrets に ANTHROPIC_API_KEY 等を登録 → 毎朝のActionsが動く

※5〜6はClaude Code自身に実行させてもよい（git/gh）。GitHubアカウントとgh認証は事前に必要。

## スキルの自動起動（任意）
skills/ は CLAUDE.md が読みに行くので今のままで機能する。
Claude Code純正の「スキル」として説明文で自動起動させたい場合は .claude/skills/ 配下へ。

## 順番
まずAだけで十分。B（git/GitHub）と自動化は後からでOK。
