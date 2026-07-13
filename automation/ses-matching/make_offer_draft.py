#!/usr/bin/env python3
"""逆方向マッチング：ITSの要員（プロパー）を、配信で来た案件に提案する下書きを作る。

従来（`make_draft.py`）は「ITSの案件 × 配信で来た要員」だったが、こちらは対の逆方向：
**「配信で来た案件 × ITSのプロパー要員（KN 等）」** の提案下書きを確定生成する。

- テンプレ：`reply-template-offer.txt`（`{会社名}{担当者名}{案件名}{要員サマリー}{署名}`）
- 要員サマリー：`要員_〇〇_*.md` の `<!-- MAIL-BLOCK-START/END -->` を**そのまま**挿入
- 件名：`RE:〔案件配信の件名〕`（代表テンプレ準拠）
- スキルシートPDFは提案時に添付（`--attach` を渡すと .eml に添付して書き出す）

**このスクリプトは下書きを出すだけ。メール送信は一切しない**（送信は必ず代表が手動・ITSセールスから）。
ガードレール（From＝sales@固定・REOorGA混入禁止・宛先は保守的抽出）は `run_ses_matching.py` の
既存関数をそのまま再利用する。

使い方:
  # 単一案件を渡して提案下書きを1件つくる（①②③は配信メールから手入力）
  python make_offer_draft.py \
    --subject "【PMO補佐】大手SIer 進捗管理支援 8月〜" \
    --company "株式会社〇〇" --person "山田" \
    --to "yamada@example.co.jp" \
    --case-name "PMO補佐案件"
  # 案件本文を渡すと宛先(To)を自動抽出（--to 省略時）
  python make_offer_draft.py --subject "..." --company "..." --person "..." --body-file 案件.txt
  # スキルシートPDFを添付した送信可能な .eml を書き出す
  python make_offer_draft.py --subject "..." --company "..." --person "..." \
    --attach ../../data/skillsheets/KN_スキルシート.pdf --eml /tmp/KN_offer.eml
  # 案件インボックス（複数案件）を一括で洗い出し＋下書き化（鮮度5日＋KN適合）
  python make_offer_draft.py --inbox inbox-案件.md --date 2026-07-12
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

from run_ses_matching import (HERE, SALES_FROM, REOORGA_ADDR, read, load_signature,
                              extract_contact, validate_draft, _is_sendable_addr,
                              _fmt_reply_subject, load_proposed, append_proposed, _dupe_key, _env,
                              _notion_api, _nt_block, post_notion_db_rows,
                              fetch_imap, _detect_drafts_folder, _its_key)

# 既定の要員（当面は KN 一人。複数プロパーになったら --engineer で切替）
DEFAULT_ENGINEER = "KN"

# 要員のプロフィール既定値（Notion行・年齢等の表示に使用。正本は 要員_*.md）
ENGINEER_META = {
    "KN": {"age": "30", "gender": "女", "want_rate": "48万（応相談）",
           "pdf": os.path.join(HERE, "..", "..", "data", "skillsheets", "KN_スキルシート.pdf")},
}

# KN の「刺さる／外れる」語（正本は 要員_KN_PMOサポート.md §4。ここは判定用の写し）
FIT_POS = ["pmo", "pmo補佐", "pmサポート", "pm補佐", "プロジェクト推進", "プロジェクトアシスタント",
           "pjアシスタント", "アシスタント", "it事務", "事務", "サービス導入", "導入支援", "導入サポート",
           "オンボーディング", "サポート", "ヘルプデスク", "バックオフィス", "営業事務", "秘書",
           "進捗管理", "課題管理", "タスク管理", "資料作成", "議事録", "調整", "問い合わせ",
           "カスタマーサクセス", "推進支援", "pm支援", "運用サポート"]
FIT_NEG = ["設計", "構築", "開発", "プログラ", "コーディング", "java", "python", "インフラ構築",
           "ネットワーク設計", "サーバ構築", "dba", "保守開発", "実装"]


def load_engineer_mail_block(eng_hint=""):
    """要員_*.md の MAIL-BLOCK（要員サマリー）を返す。eng_hint で優先マッチ、無ければ最初。"""
    blocks = []
    for name in sorted(os.listdir(HERE)):
        if name.startswith("要員_") and name.endswith(".md"):
            body = read(name) or ""
            m = re.search(r"<!--\s*MAIL-BLOCK-START\s*-->\s*(.*?)\s*<!--\s*MAIL-BLOCK-END\s*-->", body, re.S)
            if m:
                blocks.append((name, m.group(1).strip()))
    if not blocks:
        return ""
    key = (eng_hint or "").lower()
    if key:
        for name, blk in blocks:
            if key in name.lower():
                return blk
    return blocks[0][1]


def offer_subject(subject):
    """件名 → 『RE:〔案件件名〕』（既存の Re:/Fwd: は剥がしてから付け直す）。"""
    return "RE:" + _fmt_reply_subject(subject)


def build_offer_parts(subject=None, company=None, person=None, case_name=None,
                      to=None, body="", engineer=DEFAULT_ENGINEER):
    """提案を『件名／宛先／本文』の部品で返す（決定論・テンプレ差し込み）。"""
    tmpl = read("reply-template-offer.txt") or ""
    comp = (company or "").strip() or "〇〇株式会社"
    pers = (person or "").strip() or "ご担当者"
    cname = (case_name or _fmt_reply_subject(subject or "")).strip() or "ご案内の案件"
    summary = load_engineer_mail_block(engineer)
    body_txt = (tmpl
                .replace("{会社名}", comp)
                .replace("{担当者名}", pers)
                .replace("{案件名}", cname)
                .replace("{要員サマリー}", summary)
                .replace("{署名}", load_signature())).strip()
    # 宛先：手入力があれば最優先、無ければ案件本文/件名から保守的抽出
    if to and _is_sendable_addr(to):
        to_addr = to.strip()
    else:
        to_addr = extract_contact("", body or "", subject or "")["to"]
    return {"subject": offer_subject(subject or cname), "to": to_addr, "body": body_txt}


def finalize_offer_draft(parts, note="", engineer=DEFAULT_ENGINEER):
    draft = f"From: {SALES_FROM}\nTo: {parts['to']}\n件名: {parts['subject']}\n\n{parts['body']}"
    if note:
        draft += f"\n\n【代表の補足指示メモ（送信前に反映/削除）】{note}"
    return draft


def build_offer_eml(parts, attach_path=None, engineer=DEFAULT_ENGINEER):
    """送信可能な MIME 下書き（.eml）を組み立てる。--attach でスキルシートPDFを添付。
    送信はしない（\\Draft 相当）。ガードレール違反があれば (None, issues) を返す。"""
    import email.message
    import mimetypes

    draft_txt = finalize_offer_draft(parts, engineer=engineer)
    issues = validate_draft(draft_txt)
    if issues:
        return None, issues
    to_ok = ("@" in parts["to"]) and _is_sendable_addr(parts["to"])
    prefix = ""
    if not to_ok:
        prefix += "※宛先未確定：送信前に配信元担当のアドレスを To に入れてください。\n\n"
    msg = email.message.EmailMessage()
    msg["From"] = SALES_FROM
    if to_ok:
        msg["To"] = parts["to"]
    msg["Subject"] = parts["subject"]
    msg.set_content(prefix + parts["body"])
    if attach_path:
        if not os.path.exists(attach_path):
            return None, [f"添付ファイルが見つからない: {attach_path}"]
        ctype, _ = mimetypes.guess_type(attach_path)
        maintype, subtype = (ctype.split("/", 1) if ctype else ("application", "octet-stream"))
        with open(attach_path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(attach_path))
    return msg, []


# ---------- 案件インボックスの一括処理（洗い出し＋下書き化） ----------
def parse_case_inbox(text):
    """inbox-案件.md（## 案件 … ブロック）を素朴にパースして案件リストを返す。
    各案件: {title, date, body}. 本文は ``` フェンス内 or 見出し以降を採用。"""
    cases = []
    # 「## 案件 …」で分割
    chunks = re.split(r"\n(?=##\s*案件)", text)
    for ch in chunks:
        if "案件" not in ch:
            continue
        title_m = re.search(r"##\s*(案件[^\n]*)", ch)
        if not title_m:   # 見出し前の説明ブロック等（## 案件 で始まらない）は案件ではない
            continue
        date_m = re.search(r"配信日[^\d]*(\d{4}-\d{2}-\d{2})", ch)
        fence = re.search(r"```(?:\w+)?\n(.*?)```", ch, re.S)
        body = (fence.group(1).strip() if fence else ch).strip()
        if not body or body == title_m.group(0):
            continue
        cases.append({
            "title": (title_m.group(1).strip() if title_m else "案件"),
            "date": (date_m.group(1) if date_m else ""),
            "body": body,
        })
    return cases


def offer_fit(subject, body):
    """KN の案件適合を決定論で採点（keyword）。総合判断は代表。
    返り値: {pos, neg, hits, likelihood, concerns}"""
    hay = f"{subject}\n{body}".lower()
    pos = [k for k in FIT_POS if k in hay]
    neg = [k for k in FIT_NEG if k in hay]
    concerns = []
    if neg and not pos:
        concerns.append("技術専任寄り・要確認（PMO/事務/サポート要素が見当たらない）")
    if len(pos) >= 2 and not (neg and not pos):
        likelihood = "高"
    elif len(pos) >= 1:
        likelihood = "中"
    else:
        likelihood = "低"
    if neg and pos:
        concerns.append("技術要素あり・非技術PMO/事務としての当て方を面談前に確認")
    return {"pos": pos, "neg": neg, "hits": len(pos), "likelihood": likelihood, "concerns": concerns}


def within_fresh(date_str, base_date, fresh_days):
    if not date_str:
        return None  # 不明＝判定保留（除外はしない・フラグ）
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        return None
    return 0 <= (base_date - d).days <= fresh_days


def _score_from_fit(fit, fresh):
    """洗い出しの並べ替え・Notion表示用の目安スコア（0-100）。判定の主軸は likelihood。"""
    base = min(88, fit["hits"] * 11)
    if fresh is True:
        base += 12
    elif fresh is None:
        base += 4
    if fit["neg"] and not fit["pos"]:
        base = min(base, 40)
    return min(100, base)


def build_candidate(case, fit, fresh, base_date, engineer, seen):
    """洗い出し1件を、既存Notion関数と互換の候補dictにする（engineer=要員固定・case=案件名）。"""
    flags = []
    if fresh is False:
        flags.append(f"鮮度超過（配信{case['date']}・{base_date.isoformat()}基準5日超）→対象外")
    if fresh is None:
        flags.append("配信日不明・要確認")
    flags += fit["concerns"]
    if _dupe_key(case["title"], engineer) in seen:
        flags.append("既提案・重複")
    to = extract_contact(case.get("from_addr", ""), case["body"], case["title"])["to"]
    meta = ENGINEER_META.get(engineer, {})
    summary = ("適合語：" + " / ".join(fit["pos"][:8])) if fit["pos"] else "KN適合語ヒットなし"
    company = (case.get("from_name") or "").strip() or "要確認（配信元）"
    return {
        "engineer": engineer,
        "case": case["title"],
        "company": company,
        "person": "",
        "to": to,
        "score": _score_from_fit(fit, fresh),
        "likelihood": ("低" if fresh is False else fit["likelihood"]),
        "age": meta.get("age", "不明"),
        "src_date": case["date"],
        "flags": flags,
        "summary": summary,
        "_fit": fit,
        "_fresh": fresh,
        "_body": case["body"],
    }


def write_offer_digest(rows, base_date, engineer):
    """洗い出しをMarkdownダイジェストにして digests/offer-digest-YYYYMMDD.md へ（gitignore）。"""
    d = base_date.isoformat()
    lines = [f"# 逆方向マッチング（要員 {engineer} × 配信案件）ダイジェスト（{d}）", "",
             f"基準日 {d}／鮮度5日／面談通過可能性の主軸は KN 適合。**送信は代表が手動**（下書きまで）。", ""]
    for i, c in enumerate(rows, 1):
        mark = "🚫対象外" if c["_fresh"] is False else {"高": "◎", "中": "○", "低": "△"}[c["likelihood"]]
        lines.append(f"## {i}. {mark} {c['case']}")
        lines.append(f"- 面談通過可能性：**{c['likelihood']}**（目安{c['score']}点）／配信日：{c['src_date'] or '不明'}")
        lines.append(f"- 宛先To：{c['to']}")
        lines.append(f"- {c['summary']}")
        if c["flags"]:
            lines.append(f"- ⚠️ {' / '.join(c['flags'])}")
        lines.append("")
    out_dir = os.path.join(HERE, "digests")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"offer-digest-{d.replace('-', '')}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def write_offer_emls(rows, base_date, engineer):
    """高/中・鮮度内の候補について、スキルシートPDF添付済みの .eml を digests/ に書き出す（gitignore）。
    宛先・会社・担当は配信本文から取れた分のみ。未確定は本文冒頭に注記。**送信はしない**。"""
    meta = ENGINEER_META.get(engineer, {})
    pdf = meta.get("pdf")
    pdf = pdf if (pdf and os.path.exists(pdf)) else None
    out_dir = os.path.join(HERE, "digests")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for i, c in enumerate(rows, 1):
        if c["_fresh"] is False or c["likelihood"] not in ("高", "中"):
            continue
        parts = build_offer_parts(subject=c["case"], company=None, person=None,
                                  case_name=c["case"], to=c["to"], body=c["_body"], engineer=engineer)
        msg, issues = build_offer_eml(parts, attach_path=pdf, engineer=engineer)
        if msg is None:
            print(f"[offer-eml] スキップ（{issues}）: {c['case']}")
            continue
        safe = re.sub(r"[^\w぀-ヿ一-鿿]+", "_", c["case"])[:40]
        path = os.path.join(out_dir, f"offer-{base_date.isoformat()}-{i:02d}-{safe}.eml")
        with open(path, "wb") as f:
            f.write(msg.as_bytes())
        written.append(path)
    return written, bool(pdf)


def offer_notion_blocks(rows, engineer):
    """『KN案件 YYYY-MM-DD』ページ用のブロック（洗い出しの可視化・返信本文は載せない）。"""
    blocks = [_nt_block("heading_2", f"提案候補（要員 {engineer} × 配信案件・スコア順）")]
    for c in rows:
        mark = "🚫対象外" if c["_fresh"] is False else {"高": "◎", "中": "○", "低": "△"}[c["likelihood"]]
        flag = ("　⚠️" + " / ".join(c["flags"])) if c["flags"] else ""
        blocks.append(_nt_block("heading_3", f"{mark} {c['case']}　{c['score']}/100・{c['likelihood']}{flag}"))
        blocks.append(_nt_block("bulleted_list_item",
                                f"配信日 {c['src_date'] or '不明'}｜To {c['to']}｜{c['summary']}"))
        blocks.append({"object": "block", "type": "divider", "divider": {}})
    return blocks[:95]


def post_offer_notion(rows, base_date, engineer):
    """① 日次スナップショットページ『{engineer}案件 YYYY-MM-DD』を親ページ配下に作成。
    ② 高/中・鮮度内の候補を既存『SES提案トラッカー』DBへ行追加（engineer×案件・ステータス=未送信）。
    NOTION_TOKEN/NOTION_PAGE_ID 未設定なら何もしない（Actions/ローカルでトークン設定時に有効）。"""
    token = os.environ.get("NOTION_TOKEN")
    parent = _env("NOTION_PAGE_ID") or _env("NOTION_PARENT_ID")
    if not (token and parent):
        print("[notion] NOTION_TOKEN/NOTION_PAGE_ID 未設定のためNotion反映はスキップ（トークン設定で有効化）")
        return
    title = f"{engineer}案件 {base_date.isoformat()}"
    page = _notion_api("POST", "https://api.notion.com/v1/pages", token, {
        "parent": {"page_id": parent},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
        "children": offer_notion_blocks(rows, engineer),
    })
    print(f"[notion] page created: {title}" if page else "[notion] page 作成に失敗（トークン/共有を確認）")
    # DBは高/中・鮮度内のみ（低・対象外は行にしない）
    actionable = [c for c in rows if c["_fresh"] is not False and c["likelihood"] in ("高", "中")]
    try:
        post_notion_db_rows({"candidates": actionable}, base_date)
    except Exception as e:  # noqa  DB反映の失敗は本体を止めない
        print(f"[notion-db] スキップ（エラー）: {e}")


def load_cases_from_imap(base_date, fresh_days):
    """contact@（REOorGA受信箱）から直近days日のメールを取得し、案件cases形式に整える。
    既存 run_ses_matching.fetch_imap を再利用（読むだけ・添付は読まない）。NW/Sec用プレフィルタは通さず、
    全件を KN の offer_fit で選定する（逆方向は案件の型が違うため）。"""
    items = fetch_imap(base_date, fresh_days)
    cases = []
    for it in items:
        subj = (it.get("subject") or "").strip()
        body = (it.get("body") or "").strip()
        if not (subj or body):
            continue
        cases.append({
            "title": subj or "（件名なし）",
            "date": it.get("date") or "",
            "body": body,
            "from_addr": it.get("from_addr", ""),
            "from_name": it.get("from_name", ""),
        })
    return cases


def save_offer_drafts_to_sales(rows, engineer):
    """高/中・鮮度内の提案下書きを sales@ の下書きフォルダに IMAP APPEND で保存（**送信しない**）。
    スキルシートPDFを添付。同一(案件×要員)は X-ITS-Key で重複作成しない。
    run_ses_matching.save_drafts_to_sales と同じ接続/フォルダ/重複ロジックを踏襲（別テンプレのため別関数）。
    SALES_IMAP_HOST/PASSWORD 未設定なら何もしない。"""
    host = _env("SALES_IMAP_HOST")
    pw = _env("SALES_IMAP_PASSWORD")
    user = _env("SALES_IMAP_USER", SALES_FROM)
    if not (host and pw):
        print("[drafts] SALES_IMAP_HOST/PASSWORD 未設定のため sales@下書き保存はスキップ（Secret登録で有効化）")
        return
    import imaplib
    import time as _time

    meta = ENGINEER_META.get(engineer, {})
    pdf = meta.get("pdf")
    pdf = pdf if (pdf and os.path.exists(pdf)) else None
    targets = [c for c in rows if c["_fresh"] is not False and c["likelihood"] in ("高", "中")]
    targets.sort(key=lambda c: c.get("score", 0) if isinstance(c.get("score"), (int, float)) else 0, reverse=True)
    if not targets:
        print("[drafts] 対象候補（高/中）なし")
        return
    port = int(_env("SALES_IMAP_PORT", "993"))
    tmo = int(_env("SALES_IMAP_TIMEOUT", "30"))
    tries = int(_env("SALES_IMAP_RETRIES", "3"))
    folder = _env("SALES_DRAFTS_FOLDER") or "Drafts"
    saved = skipped = dup = 0
    M = None
    for attempt in range(1, tries + 1):
        try:
            M = imaplib.IMAP4_SSL(host, port, timeout=tmo)
            M.login(user, pw)
            break
        except Exception as e:  # noqa
            try:
                if M is not None:
                    M.logout()
            except Exception:  # noqa
                pass
            M = None
            if attempt < tries:
                wait = 5 * attempt
                print(f"[drafts] 接続リトライ {attempt}/{tries}（{type(e).__name__}: {e}）→ {wait}秒待機")
                _time.sleep(wait)
            else:
                print(f"[drafts] 接続失敗（{tries}回試行）。SALES_IMAP_HOST/PORT/PASSWORD・到達性を確認: {e}")
                return
    try:
        folder = _env("SALES_DRAFTS_FOLDER") or _detect_drafts_folder(M)
        folder_q = f'"{folder}"' if (" " in folder or "(" in folder) else folder
        print(f"[drafts] 下書きフォルダ: {folder}")
        selected = False
        try:
            selected = M.select(folder_q)[0] == "OK"
        except Exception:  # noqa
            selected = False
        _seen = set()
        for c in targets:
            key = _its_key(c.get("case"), c.get("engineer"))
            if key in _seen:
                dup += 1
                continue
            _seen.add(key)
            if selected:
                try:
                    typ, data = M.search(None, "HEADER", "X-ITS-Key", key)
                    if typ == "OK" and data and data[0].split():
                        dup += 1
                        print(f"[drafts] 既に下書きあり（重複回避）: {c.get('engineer')} × {c.get('case')}")
                        continue
                except Exception:  # noqa
                    pass
            parts = build_offer_parts(subject=c["case"], case_name=c["case"], to=c["to"],
                                      body=c["_body"], engineer=engineer)
            msg, hard = build_offer_eml(parts, attach_path=pdf, engineer=engineer)
            if msg is None:
                skipped += 1
                print(f"[drafts] スキップ（ガードレール違反）: {c.get('case')} {hard}")
                continue
            msg["X-ITS-Key"] = key
            typ, _ = M.append(folder_q, "(\\Draft)", imaplib.Time2Internaldate(_time.time()), msg.as_bytes())
            if typ == "OK":
                saved += 1
                print(f"[drafts] 下書き保存: {c.get('engineer')} × {c.get('case')}")
            else:
                skipped += 1
                print(f"[drafts] APPEND失敗（{typ}）: {c.get('case')}")
    except Exception as e:  # noqa
        print(f"[drafts] エラー: {e}")
    finally:
        try:
            M.logout()
        except Exception:  # noqa
            pass
    print(f"[drafts] sales@ 下書き：新規{saved}／重複回避{dup}／スキップ{skipped}（folder={folder}）")


def run_batch(inbox_path, base_date, fresh_days, engineer, note, do_notion=False,
              source="file", save_drafts=False):
    if source == "imap":
        cases = load_cases_from_imap(base_date, fresh_days)
        if not cases:
            print("[imap] 取得0件（鮮度内メールなし or 接続失敗）。処理を終了します。")
            return []
    else:
        text = read(os.path.relpath(inbox_path, HERE)) if os.path.exists(os.path.join(HERE, inbox_path)) else None
        if text is None:
            with open(inbox_path, encoding="utf-8") as f:
                text = f.read()
        cases = parse_case_inbox(text)
        if not cases:
            sys.exit(f"案件が見つかりません（{inbox_path}）。inbox-案件.example.md の形式で貼ってください。")
    seen = load_proposed()
    rows = []
    for c in cases:
        fresh = within_fresh(c["date"], base_date, fresh_days)
        fit = offer_fit(c["title"], c["body"])
        rows.append(build_candidate(c, fit, fresh, base_date, engineer, seen))
    # スコア降順（鮮度超過は末尾）
    rows.sort(key=lambda c: (c["_fresh"] is not False, c["score"]), reverse=True)

    print("=" * 72)
    print(f"■ 逆方向マッチング（要員 {engineer} × 配信案件）洗い出し　基準日 {base_date.isoformat()}／鮮度{fresh_days}日")
    print("=" * 72)
    for i, c in enumerate(rows, 1):
        mark = "🚫対象外" if c["_fresh"] is False else {"高": "◎", "中": "○", "低": "△"}[c["likelihood"]]
        print(f"{i:>2}. {mark} 面談通過可能性:{c['likelihood']}（{c['score']}点）"
              f"　配信日:{c['src_date'] or '不明'}　{c['case']}")
        if c["_fit"]["pos"]:
            print(f"      刺さる: {' / '.join(c['_fit']['pos'][:8])}｜To {c['to']}")
        if c["flags"]:
            print(f"      ⚠️ {' / '.join(c['flags'])}")
    print("=" * 72)
    actionable = [c for c in rows if c["_fresh"] is not False and c["likelihood"] in ("高", "中")]
    dpath = write_offer_digest(rows, base_date, engineer)
    emls, has_pdf = write_offer_emls(rows, base_date, engineer)
    # 候補JSON（gitignore）も残す
    out_dir = os.path.join(HERE, "digests")
    with open(os.path.join(out_dir, f"offer-candidates-{base_date.isoformat().replace('-','')}.json"),
              "w", encoding="utf-8") as f:
        json.dump({"date": base_date.isoformat(), "engineer": engineer,
                   "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in rows]},
                  f, ensure_ascii=False, indent=2)
    print(f"提案候補（高/中・鮮度内）：{len(actionable)}件")
    print(f"[ok] ダイジェスト → {dpath}")
    print(f"[ok] 提案下書き .eml（{'PDF添付' if has_pdf else 'PDF無し'}・要手動送信）→ {len(emls)}件 digests/ に出力")
    if do_notion:
        post_offer_notion(rows, base_date, engineer)
    else:
        print("（Notion可視化するには --notion を付けて実行。NOTION_TOKEN/NOTION_PAGE_ID が必要）")
    if save_drafts:
        save_offer_drafts_to_sales(rows, engineer)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engineer", default=DEFAULT_ENGINEER, help="提案する自社要員（既定 KN）。要員_*.md に対応")
    # 単一案件モード（配信メールの①②③を手入力）
    ap.add_argument("--subject", default=None, help="①案件配信の件名（RE:〔件名〕 に使う）")
    ap.add_argument("--company", default=None, help="②配信元の会社名")
    ap.add_argument("--person", default=None, help="③先方担当者名（「様」は自動付与）")
    ap.add_argument("--case-name", default=None, help="本文『配信にて頂きました〇〇について』の案件名（省略時は件名）")
    ap.add_argument("--to", default=None, help="宛先アドレス（省略時は本文/件名から保守的抽出）")
    ap.add_argument("--body", default=None, help="案件本文（To抽出用・任意）")
    ap.add_argument("--body-file", default=None, help="案件本文のファイルパス（To抽出用・任意）")
    ap.add_argument("--attach", default=None, help="スキルシートPDF等の添付パス（.eml出力時に添付）")
    ap.add_argument("--eml", default=None, help="送信可能な .eml の出力先（添付込みMIMEを書き出す）")
    ap.add_argument("--note", default="", help="代表の補足指示（送信前メモ）")
    ap.add_argument("--no-log", action="store_true", help="既提案ログに記録しない（試作のみ）")
    ap.add_argument("--date-str", default=None, help="既提案ログの日付（省略時は today 相当を渡すこと）")
    # 一括モード（案件インボックスの洗い出し）
    ap.add_argument("--inbox", default=None, help="案件インボックス（複数案件）を一括で洗い出し（--source file）")
    ap.add_argument("--source", choices=["file", "imap"], default="file",
                    help="一括モードの案件ソース。imap＝contact@（REOorGA受信箱）から取得（要 IMAP_* Secret）")
    ap.add_argument("--date", default=None, help="一括モードの基準日 YYYY-MM-DD（鮮度判定）")
    ap.add_argument("--fresh-days", type=int, default=int(_env("FRESH_DAYS", "5")), help="鮮度（既定5日）")
    ap.add_argument("--notion", action="store_true",
                    help="一括モードでNotionに反映（『〔要員〕案件 YYYY-MM-DD』ページ＋提案トラッカーDB行）")
    ap.add_argument("--save-drafts", action="store_true",
                    help="高/中候補の下書きを sales@ の下書きフォルダに保存（要 SALES_IMAP_* Secret・送信はしない）")
    args = ap.parse_args()

    if args.inbox or args.source == "imap":
        base = datetime.date.fromisoformat(args.date) if args.date else \
            datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
        if args.source == "file" and not args.inbox:
            sys.exit("--source file では --inbox が必要です（案件の貼り込み）。imap 取得は --source imap。")
        run_batch(args.inbox, base, args.fresh_days, args.engineer, args.note,
                  do_notion=args.notion, source=args.source, save_drafts=args.save_drafts)
        return

    if not args.subject:
        sys.exit("--subject（案件配信の件名）は必須です。単一案件モードは --subject/--company/--person を渡してください。")

    body = args.body or ""
    if args.body_file and os.path.exists(args.body_file):
        with open(args.body_file, encoding="utf-8") as f:
            body = f.read()

    parts = build_offer_parts(subject=args.subject, company=args.company, person=args.person,
                              case_name=args.case_name, to=args.to, body=body, engineer=args.engineer)
    draft = finalize_offer_draft(parts, note=args.note, engineer=args.engineer)
    issues = validate_draft(draft)
    case_key = (args.case_name or _fmt_reply_subject(args.subject)).strip()
    dup = _dupe_key(case_key, args.engineer) in load_proposed()

    print("=" * 64)
    print(f"■ 送信可能な下書き（提案）： 要員 {args.engineer} × 案件『{case_key}』")
    if dup:
        print("⚠️ 既提案・重複： この 案件×要員 は過去に提案済みです（proposed-log）。二重提案に注意。")
    print("=" * 64)
    print(draft)
    print("=" * 64)
    if issues:
        print("🔴 ガードレール違反（送信不可・要修正）：")
        for x in issues:
            print(f"  - {x}")
        print("=" * 64)
    if args.eml:
        msg, hard = build_offer_eml(parts, attach_path=args.attach, engineer=args.engineer)
        if msg is None:
            print(f"🔴 .eml 生成不可： {hard}")
        else:
            with open(args.eml, "wb") as f:
                f.write(msg.as_bytes())
            att = f"（添付: {os.path.basename(args.attach)}）" if args.attach else "（添付なし）"
            print(f"■ 送信可能な .eml を書き出しました: {args.eml} {att}")
            print("  → sales@ でこの下書きを開いて内容確認 → 手動送信（AIは送信しない）。")
    print("■ 送信前チェック（代表）")
    print(f"  [ ] From が ITSセールス（{SALES_FROM}）か／REOorGA（{REOORGA_ADDR}）になっていないか")
    print(f"  [ ] To が配信元担当のアドレスか（現在: {parts['to']}）")
    print("  [ ] 件名 RE:〔案件件名〕・会社名・担当者名・案件名が正しいか")
    print("  [ ] KNスキルシートPDFを添付したか（提案時添付）")
    print("  [ ] 単価（48万・応相談）・稼働（即日〜）・勤務形態が案件と整合するか")
    print("  → OKなら sales@ から手動送信。結果は ../../data/pipeline.md へ。")

    if not args.no_log and not issues and not dup:
        date_str = args.date_str or "unknown"
        append_proposed(case_key, args.engineer, date_str)
        print("  （既提案ログに記録しました。次回以降この組は『既提案・重複』で警告されます）")


if __name__ == "__main__":
    main()
