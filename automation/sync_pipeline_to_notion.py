#!/usr/bin/env python3
"""
営業進捗シート（data/ の Markdown テーブル）を Notion ページにミラーする。

何をするか:
- data/pipeline.md / data/bp-list.md / data/partners.md を読み、
  各 Markdown テーブルを Notion の table ブロックへ変換し、指定ページに反映する。

2つのモード（NOTION_SYNC_MODE で切替。既定は安全な append）:
- append（既定 / 安全）: 既存ブロックを一切削除せず、ページ末尾に「日時付きスナップショット」を追記する。
  朝会の議事録など他の内容があるページと共用しても消えない。スナップショットは溜まっていく。
- mirror（要・専用ページ）: 実行のたびに対象ページの既存ブロックを全削除→最新内容で書き直し。
  常に最新シートの鏡になる（重複なし）が、ページ内の他の内容も消すため**ミラー専用ページにのみ使う**。

重要:
- これは「シートの内容を Notion へ転記する」だけ。お金・法務の判断はしない。
- 資料にない数値は補完しない（シートにある内容をそのまま反映する）。

環境変数:
  NOTION_TOKEN            (必須) Notion インテグレーションのトークン
  NOTION_SYNC_MODE        (任意) "append"(既定) または "mirror"
  NOTION_PIPELINE_PAGE_ID (推奨) 反映先ページのID。未設定なら NOTION_PAGE_ID を使う
  NOTION_PAGE_ID          (任意) 朝会と同じページに追記する場合などのフォールバック
"""
import os
import sys
import json
import datetime
import urllib.request
import urllib.error

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTION_VERSION = "2022-06-28"

# 反映する営業シート（見出し, ファイルパス）
SHEETS = [
    ("営業パイプライン", "data/pipeline.md"),
    ("BPリスト（発注元）", "data/bp-list.md"),
    ("協力会社・エンジニアプール", "data/partners.md"),
]


def read_file(rel):
    path = os.path.join(REPO_ROOT, rel)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def parse_markdown_tables(md):
    """Markdown 本文からテーブル群を抽出して [[行...], ...] を返す（行はセルのリスト）。
    区切り行（|---|---|）はヘッダ判定に使い、データには含めない。"""
    tables = []
    current = []
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            # 区切り行（--- のみ）はスキップ
            if all(set(c) <= set("-: ") and c for c in cells):
                continue
            current.append(cells)
        else:
            if current:
                tables.append(current)
                current = []
    if current:
        tables.append(current)
    return tables


def rich_text(content):
    content = content or ""
    # Notion のテキスト上限は 2000 字。余裕を持って切る。
    return [{"type": "text", "text": {"content": content[:1900]}}]


def table_block(rows):
    """セル行のリストを Notion table ブロックに変換（1行目をヘッダ扱い）。"""
    width = max(len(r) for r in rows)
    children = []
    for r in rows:
        cells = [rich_text(r[i] if i < len(r) else "") for i in range(width)]
        children.append({
            "object": "block", "type": "table_row",
            "table_row": {"cells": cells},
        })
    return {
        "object": "block", "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            "children": children,
        },
    }


def heading_block(text, level=2):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def paragraph_block(text):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rich_text(text)}}


def build_blocks(mode="append"):
    jst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    if mode == "append":
        # 共用ページに溜める前提。区切りと日時付き見出しで1スナップショットを明示。
        blocks = [
            {"object": "block", "type": "divider", "divider": {}},
            heading_block(f"営業進捗 スナップショット {now}", 1),
            paragraph_block("出典: data/ の各シート（このセクションは自動追記）"),
        ]
    else:
        blocks = [
            heading_block("営業進捗（自動反映）", 1),
            paragraph_block(f"最終更新: {now} ／ 出典: data/ の各シート（このページは自動ミラー）"),
        ]
    for title, rel in SHEETS:
        md = read_file(rel)
        blocks.append(heading_block(title, 2))
        if not md:
            blocks.append(paragraph_block("(ファイルが見つかりません)"))
            continue
        tables = parse_markdown_tables(md)
        data_tables = [t for t in tables if len(t) >= 1]
        if not data_tables:
            blocks.append(paragraph_block("(まだ記録がありません)"))
            continue
        for t in data_tables:
            if len(t) <= 1:
                blocks.append(paragraph_block("(ヘッダのみ・データ未記入)"))
            else:
                blocks.append(table_block(t))
    return blocks


def _request(method, url, headers, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def clear_page(page_id, headers):
    """対象ページの既存子ブロックをすべて削除（アーカイブ）する。"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
    removed = 0
    while True:
        res = _request("GET", url, headers)
        for blk in res.get("results", []):
            bid = blk["id"]
            try:
                _request("DELETE", f"https://api.notion.com/v1/blocks/{bid}", headers)
                removed += 1
            except urllib.error.HTTPError as e:
                print(f"[notion] delete error {e.code}: {e.read().decode('utf-8', 'ignore')}")
        if res.get("has_more") and res.get("next_cursor"):
            url = (f"https://api.notion.com/v1/blocks/{page_id}/children"
                   f"?page_size=100&start_cursor={res['next_cursor']}")
        else:
            break
    print(f"[notion] cleared {removed} blocks")


def append_blocks(page_id, headers, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    # Notion は1リクエスト100ブロックまで。テーブルは children 付きで送れる。
    for i in range(0, len(blocks), 100):
        _request("PATCH", url, headers, {"children": blocks[i:i + 100]})
    print(f"[notion] appended {len(blocks)} blocks")


def main():
    token = os.environ.get("NOTION_TOKEN")
    page_id = os.environ.get("NOTION_PIPELINE_PAGE_ID") or os.environ.get("NOTION_PAGE_ID")
    mode = os.environ.get("NOTION_SYNC_MODE", "append").strip().lower()
    if mode not in ("append", "mirror"):
        print(f"NOTION_SYNC_MODE は append か mirror。受け取った値: {mode}", file=sys.stderr)
        sys.exit(1)
    if not token or not page_id:
        print("NOTION_TOKEN と NOTION_PIPELINE_PAGE_ID（または NOTION_PAGE_ID）が必要です。",
              file=sys.stderr)
        sys.exit(1)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    blocks = build_blocks(mode)
    try:
        if mode == "mirror":
            # 専用ページ前提。既存ブロックを消して書き直す。
            clear_page(page_id, headers)
        # append は何も消さず末尾に追記するだけ。
        append_blocks(page_id, headers, blocks)
        print(f"[notion] 営業進捗を反映しました（mode={mode}）。")
    except urllib.error.HTTPError as e:
        print(f"[notion] error {e.code}: {e.read().decode('utf-8', 'ignore')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
