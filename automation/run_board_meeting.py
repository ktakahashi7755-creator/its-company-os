#!/usr/bin/env python3
"""
毎朝のAI取締役会を実行し、結果をNotion / LINE / Webhook に投稿する。
- 経営OSの状態ファイル（CLAUDE.md, docs/, finance/TODO, board-meetingスキル）を読み込み、
  AI取締役会の朝のブリーフィングを生成する。
- これは「助言ブリーフィングの生成と投稿」のみ。お金・法務に関わる行動はしない（人間がループに残る）。
環境変数:
  ANTHROPIC_API_KEY        (必須)
  ANTHROPIC_MODEL          (任意, 既定 claude-sonnet-4-6)
  NOTION_TOKEN, NOTION_PAGE_ID            (任意: Notion投稿)
  LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID (任意: LINE Messaging API push)
  WEBHOOK_URL              (任意: Slack/LINE WORKS等のIncoming Webhook)
"""
import os
import sys
import datetime
import json
import urllib.request
import urllib.error

import anthropic

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# 取締役会に渡す状態ファイル（無ければスキップ）
CONTEXT_FILES = [
    "CLAUDE.md",
    "skills/board-meeting/SKILL.md",
    "docs/action-plan.md",
    "docs/kpi.md",
    "docs/roadmap.md",
    "finance/TODO_緊急_税務.md",
]
# 前夜に任意で埋める当日インプット
DAILY_INPUT = "automation/daily-input.md"


def read_file(rel):
    path = os.path.join(REPO_ROOT, rel)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def build_context():
    parts = []
    for rel in CONTEXT_FILES:
        body = read_file(rel)
        if body:
            parts.append(f"===== {rel} =====\n{body.strip()}")
    daily = read_file(DAILY_INPUT)
    if daily and daily.strip():
        parts.append(f"===== 当日インプット（高橋が記入） =====\n{daily.strip()}")
    return "\n\n".join(parts)


SYSTEM_PROMPT = """あなたはITS合同会社のAI取締役会（CEO_Strategy / CFO_Finance_Tax / COO_Operations / CGO_Growth_Sales / CPO_Product_AI ほか必要なCXO）。
渡された経営OSの状態（CLAUDE.md・action-plan・kpi・roadmap・税務TODO・当日インプット）を読み、朝のブリーフィングを日本語で簡潔に出す。

必須フィルター: 現在はPhase 0（安定化）。すべてをまず「8月の第2期申告・納税の達成と資金の健全化を脅かさないか」で濾す。

出力フォーマット:
1. 今日の最重要（Phase 0基準で1つ）
2. 各CXOの一言（CFO=資金/税, CEO=戦略, COO=仕組み/日中解放, CPO=Familink, CGO=営業 ※関係するものだけ）
3. 本日のTOP3（時間順・各1行）
4. 要・高橋判断の論点（あれば。なければ「なし」）
5. リスク/危険信号（あれば）
6. フェーズ判定（Phase 0を脅かす兆候の有無）

当日インプットに具体的な「論点」がある場合は、上記に加えて、その論点を各CXOの賛否→対立点→推奨決定案（条件付き）の形で取締役会にかける。

厳守: 助言と整理のみ。お金・法務の最終判断はしない（税理士・弁護士へ、と必要時に添える）。資料がない数字を確定・補完しない。根拠なく「問題ない」と言わない。"""


def run_board():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d (%a)")
    context = build_context()
    user_msg = f"本日は {today}。以下が現在の経営OSの状態です。今朝の取締役会ブリーフィングを出してください。\n\n{context}"
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return today, text.strip()


def _post_json(url, headers, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def post_notion(title, body):
    token = os.environ.get("NOTION_TOKEN")
    page_id = os.environ.get("NOTION_PAGE_ID")
    if not (token and page_id):
        return
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    # 見出し + 本文を2000字以下のparagraphブロックに分割
    blocks = [{
        "object": "block", "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"AI取締役会 {title}"}}]},
    }]
    for chunk in [body[i:i + 1900] for i in range(0, len(body), 1900)] or [""]:
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        })
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    try:
        _post_json(url, headers, {"children": blocks[:100]})
        print("[notion] posted")
    except urllib.error.HTTPError as e:
        print(f"[notion] error {e.code}: {e.read().decode('utf-8', 'ignore')}")
    except Exception as e:  # noqa
        print(f"[notion] error: {e}")


def post_line(title, body):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    if not (token and user_id):
        return
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    text = f"AI取締役会 {title}\n\n{body}"[:4900]  # LINEは1メッセージ5000字まで
    try:
        _post_json("https://api.line.me/v2/bot/message/push", headers,
                   {"to": user_id, "messages": [{"type": "text", "text": text}]})
        print("[line] posted")
    except urllib.error.HTTPError as e:
        print(f"[line] error {e.code}: {e.read().decode('utf-8', 'ignore')}")
    except Exception as e:  # noqa
        print(f"[line] error: {e}")


def post_webhook(title, body):
    url = os.environ.get("WEBHOOK_URL")
    if not url:
        return
    try:
        _post_json(url, {"Content-Type": "application/json"},
                   {"text": f"AI取締役会 {title}\n\n{body}"})
        print("[webhook] posted")
    except Exception as e:  # noqa
        print(f"[webhook] error: {e}")


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY が未設定です。", file=sys.stderr)
        sys.exit(1)
    title, briefing = run_board()
    print("=" * 60)
    print(f"AI取締役会 {title}")
    print("=" * 60)
    print(briefing)
    print("=" * 60)
    post_notion(title, briefing)
    post_line(title, briefing)
    post_webhook(title, briefing)


if __name__ == "__main__":
    main()
