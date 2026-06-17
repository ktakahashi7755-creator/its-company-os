#!/usr/bin/env bash
# guard-operational-data.sh
#
# PreToolUse(Bash) ガード。
# 更新頻度の高い「業務データ」を git にコミットしようとしたら自動でブロックする。
# 業務データは Notion(MCP)に置く、というルールをハーネス側で強制するための仕組み。
#
# Claude Code の規約:
#   exit 0 = 許可 / exit 2 = ブロック(stderr の内容が Claude に渡る) / exit 1 = 非ブロック警告
#
# 必要: python3(標準でほぼ存在)。無い場合は grep フォールバックで動作する。

set -euo pipefail

input="$(cat)"

# Claude が実行しようとしている bash コマンドを取り出す
if command -v python3 >/dev/null 2>&1; then
  cmd="$(printf '%s' "$input" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("tool_input", {}).get("command", ""))
except Exception:
    print("")
')"
else
  # フォールバック: 入力全体を対象にする(精度は落ちるが安全側)
  cmd="$input"
fi

# git のステージ/コミット操作のときだけ検査する
case "$cmd" in
  *"git add"*|*"git commit"*) : ;;
  *) exit 0 ;;
esac

# Notion に置くべき業務データを示すパスパターン
patterns='営業進捗 商談 パイプライン pipeline sales-progress sales_progress
日次 daily-log daily_log kpi 実績 議事録 minutes meeting-notes
顧客メモ customer-notes crm タスク状況 task-status'

for p in $patterns; do
  if printf '%s' "$cmd" | grep -iq -- "$p"; then
    {
      echo "BLOCKED: \"$p\" は更新頻度の高い業務データです。git ではなく Notion(MCP)へ記録してください。"
      echo "ルール: 営業進捗・タスク状況・日次ログ・KPI実績・議事録・顧客メモ → Notion。"
      echo "        コード・スキル・確定戦略・ADR・テンプレート → git。"
    } >&2
    exit 2
  fi
done

exit 0
