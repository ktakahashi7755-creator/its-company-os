#!/usr/bin/env python3
"""
経営OSのMarkdownドキュメントをNotionページへ「綺麗に」ミラー同期する。

- Markdown(GFM) → Notionブロック（見出し/表/箇条書き/番号/引用/区切り/段落、
  インラインの **太字** と `コード` とリンク）に変換する。
- ミラー方式：対象ページの既存ブロックを全削除→最新で再生成。
  → Notion側は常にファイルの現在値（追記で増え続けない）。

これは「ドキュメントの整形・反映」のみ。お金・法務の行動はしない（人間がループに残る）。

設定: automation/notion-sync.config.json （file→page_idのマッピング。page_idは秘密ではない）
環境変数: NOTION_TOKEN（必須・Secretで管理）

使い方:
  python automation/sync_to_notion.py            # 設定の全ページを同期
  python automation/sync_to_notion.py --dry-run  # 変換結果のJSONを表示（ネットワークなし）
  python automation/sync_to_notion.py --file data/営業進捗シート.md --dry-run
"""
import os
import re
import sys
import json
import argparse
import datetime
import urllib.request
import urllib.error

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO_ROOT, "automation", "notion-sync.config.json")
NOTION_VERSION = "2022-06-28"
API = "https://api.notion.com/v1"

# ---------- インライン変換（**太字** / `コード` / [text](url)） ----------
_INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+?\]\([^)]+?\))")


def _rt(content, *, bold=False, code=False, link=None):
    out = []
    # Notionのtext.contentは2000字まで。長文は分割。
    for i in range(0, len(content), 2000) or [0]:
        chunk = content[i:i + 2000]
        t = {"type": "text", "text": {"content": chunk}}
        if link:
            t["text"]["link"] = {"url": link}
        if bold or code:
            t["annotations"] = {"bold": bold, "code": code}
        out.append(t)
    return out


def parse_inline(text):
    text = text.rstrip("\n")
    if not text:
        return []
    rich, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            rich += _rt(text[pos:m.start()])
        tok = m.group(0)
        if tok.startswith("**"):
            rich += _rt(tok[2:-2], bold=True)
        elif tok.startswith("`"):
            rich += _rt(tok[1:-1], code=True)
        else:  # link
            mm = re.match(r"\[([^\]]+?)\]\(([^)]+?)\)", tok)
            rich += _rt(mm.group(1), link=mm.group(2))
        pos = m.end()
    if pos < len(text):
        rich += _rt(text[pos:])
    return [r for r in rich if r["text"]["content"] != ""]


# ---------- ブロック変換 ----------
def _block(kind, **payload):
    return {"object": "block", "type": kind, kind: payload}


def _is_table_sep(line):
    return bool(re.fullmatch(r"\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*", line))


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def md_to_blocks(md):
    lines = md.split("\n")
    blocks, i = [], 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # コードフェンス
        if s.startswith("```"):
            lang = s[3:].strip() or "plain text"
            buf, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(_block("code", language=lang,
                                 rich_text=_rt("\n".join(buf))))
            continue

        # 空行
        if s == "":
            i += 1
            continue

        # 区切り線
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            blocks.append(_block("divider"))
            i += 1
            continue

        # 表（| で始まる連続行 + 区切り行）
        if s.startswith("|") and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
            header = _split_row(line)
            rows, i = [header], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            width = max(len(r) for r in rows)
            trows = []
            for r in rows:
                cells = [parse_inline(c) for c in r] + [[]] * (width - len(r))
                trows.append({"object": "block", "type": "table_row",
                              "table_row": {"cells": cells}})
            blocks.append(_block("table", table_width=width,
                                 has_column_header=True, has_row_header=False,
                                 children=trows))
            continue

        # 見出し
        h = re.match(r"(#{1,6})\s+(.*)", s)
        if h:
            level = min(len(h.group(1)), 3)
            blocks.append(_block(f"heading_{level}", rich_text=parse_inline(h.group(2))))
            i += 1
            continue

        # 引用
        if s.startswith(">"):
            blocks.append(_block("quote", rich_text=parse_inline(s[1:].strip())))
            i += 1
            continue

        # 箇条書き
        b = re.match(r"[-*+]\s+(.*)", s)
        if b:
            blocks.append(_block("bulleted_list_item", rich_text=parse_inline(b.group(1))))
            i += 1
            continue

        # 番号リスト
        n = re.match(r"\d+[.)]\s+(.*)", s)
        if n:
            blocks.append(_block("numbered_list_item", rich_text=parse_inline(n.group(1))))
            i += 1
            continue

        # 段落
        blocks.append(_block("paragraph", rich_text=parse_inline(s)))
        i += 1
    return blocks


# ---------- Notion API ----------
def _headers():
    return {
        "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _req(method, url, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")) if r.length != 0 else {}


def clear_page(page_id):
    """ページ直下の既存ブロックを全削除（アーカイブ）。"""
    cursor = None
    ids = []
    while True:
        url = f"{API}/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        res = _req("GET", url)
        ids += [b["id"] for b in res.get("results", [])]
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    for bid in ids:
        try:
            _req("DELETE", f"{API}/blocks/{bid}")
        except urllib.error.HTTPError as e:
            print(f"    [warn] delete {bid}: {e.code}")
    return len(ids)


def append_blocks(page_id, blocks):
    for j in range(0, len(blocks), 90):  # 100上限に余裕
        _req("PATCH", f"{API}/blocks/{page_id}/children",
             {"children": blocks[j:j + 90]})


def sync_page(file_rel, page_id, title):
    path = os.path.join(REPO_ROOT, file_rel)
    with open(path, encoding="utf-8") as f:
        md = f.read()
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    header = [
        _block("paragraph", rich_text=_rt(f"このページは {file_rel} から自動同期。最終同期 {ts}（手動編集は上書きされます）")),
        _block("divider"),
    ]
    blocks = header + md_to_blocks(md)
    removed = clear_page(page_id)
    append_blocks(page_id, blocks)
    print(f"  [ok] {file_rel} → {title} (旧{removed}ブロック削除 / 新{len(blocks)}ブロック)")


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="変換JSONを表示（ネットワークなし）")
    ap.add_argument("--file", help="単一ファイルのみ対象")
    args = ap.parse_args()

    cfg = load_config()
    pages = cfg.get("pages", [])
    if args.file:
        pages = [p for p in pages if p["file"] == args.file] or [{"file": args.file, "page_id": "", "title": args.file}]

    if args.dry_run:
        for p in pages:
            path = os.path.join(REPO_ROOT, p["file"])
            with open(path, encoding="utf-8") as f:
                blocks = md_to_blocks(f.read())
            print(f"# {p['file']} → {len(blocks)} blocks")
            print(json.dumps(blocks, ensure_ascii=False, indent=2))
        return

    if not os.environ.get("NOTION_TOKEN"):
        print("NOTION_TOKEN が未設定です。", file=sys.stderr)
        sys.exit(1)
    print("Notion同期を開始")
    for p in pages:
        if not p.get("page_id"):
            print(f"  [skip] {p['file']}: page_id 未設定")
            continue
        try:
            sync_page(p["file"], p["page_id"], p.get("title", p["file"]))
        except urllib.error.HTTPError as e:
            print(f"  [error] {p['file']}: {e.code} {e.read().decode('utf-8', 'ignore')}")
        except Exception as e:  # noqa
            print(f"  [error] {p['file']}: {e}")


if __name__ == "__main__":
    main()
