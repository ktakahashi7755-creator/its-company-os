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
import os
import re
import sys

from run_ses_matching import (HERE, SALES_FROM, REOORGA_ADDR, read, load_signature,
                              extract_contact, validate_draft, _is_sendable_addr,
                              _fmt_reply_subject, load_proposed, append_proposed, _dupe_key, _env)

# 既定の要員（当面は KN 一人。複数プロパーになったら --engineer で切替）
DEFAULT_ENGINEER = "KN"

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


def run_batch(inbox_path, base_date, fresh_days, engineer, note):
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
        flags = []
        if fresh is False:
            flags.append(f"鮮度超過（配信{c['date']}・{fresh_days}日超）→対象外")
        if fresh is None:
            flags.append("配信日不明・要確認")
        flags += fit["concerns"]
        if _dupe_key(c["title"], engineer) in seen:
            flags.append("既提案・重複")
        rows.append({"case": c, "fit": fit, "fresh": fresh, "flags": flags})
    # スコア降順（鮮度超過は末尾）
    rows.sort(key=lambda r: (r["fresh"] is not False, r["fit"]["hits"]), reverse=True)

    print("=" * 72)
    print(f"■ 逆方向マッチング（要員 {engineer} × 配信案件）洗い出し　基準日 {base_date.isoformat()}／鮮度{fresh_days}日")
    print("=" * 72)
    for i, r in enumerate(rows, 1):
        c, fit = r["case"], r["fit"]
        mark = "🚫対象外" if r["fresh"] is False else {"高": "◎", "中": "○", "低": "△"}[fit["likelihood"]]
        print(f"{i:>2}. {mark} 面談通過可能性:{fit['likelihood']}／適合語{fit['hits']}件"
              f"　配信日:{c['date'] or '不明'}　{c['title']}")
        if fit["pos"]:
            print(f"      刺さる: {' / '.join(fit['pos'][:8])}")
        if r["flags"]:
            print(f"      ⚠️ {' / '.join(r['flags'])}")
    print("=" * 72)
    actionable = [r for r in rows if r["fresh"] is not False and r["fit"]["likelihood"] in ("高", "中")]
    print(f"提案候補（高/中・鮮度内）：{len(actionable)}件。個別の下書きは各案件で "
          f"`--subject/--company/--person/--to` を指定して生成してください。")
    print("（宛先・会社名・担当者は配信メールから手入力が確実。本文貼付があれば --body-file で To 自動抽出も可）")
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
    ap.add_argument("--inbox", default=None, help="案件インボックス（複数案件）を一括で洗い出し")
    ap.add_argument("--date", default=None, help="一括モードの基準日 YYYY-MM-DD（鮮度判定）")
    ap.add_argument("--fresh-days", type=int, default=int(_env("FRESH_DAYS", "5")), help="鮮度（既定5日）")
    args = ap.parse_args()

    if args.inbox:
        base = datetime.date.fromisoformat(args.date) if args.date else None
        if base is None:
            sys.exit("一括モードは --date YYYY-MM-DD（基準日）が必要です（鮮度5日の判定に使用）。")
        run_batch(args.inbox, base, args.fresh_days, args.engineer, args.note)
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
