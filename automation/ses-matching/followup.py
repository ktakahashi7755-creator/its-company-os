#!/usr/bin/env python3
"""
SES 送信後フォローアップ下書きエンジン（クロージング支援・drafts only）。

目的：`run_ses_matching.py` は「提案の下書き供給」までで止まっており、**送信後**（面談化の一歩手前）が
自動化の空白だった。本モジュールは Notion「SES提案トラッカー」DB を唯一の真実源として、
**代表が『送信済』にした提案のうち、一定営業日 音沙汰が無いもの**へ、丁寧なリマインド返信の**下書き**を
sales@ の下書き(Drafts)フォルダに自動生成する。あわせて各下書きに **面談日程調整の定型文** と
**単価交渉の想定問答（クロージング支援メモ）** を「送信前メモ（要削除）」として同梱する。

**このモジュールは下書きの生成・保存のみ。メールの自動送信は一切しない**（人間がループに残る）。
ガードレール（From＝sales@固定・REOorGA混入禁止・ITS識別必須・捏造禁止）は `run_ses_matching.validate_draft`
を再利用して二重に担保する。設計思想は `../../docs/cache-automation-strategy.md`（§6-②）。

データの流れ：
  Notion「SES提案トラッカー」ステータス=送信済 の行を取得
   → 各行の last_edited_time（＝代表が『送信済』にした時刻）を送信日の代理値として営業日経過を算出
   → しきい値（既定3営業日）以上 音沙汰なし＆未リマインドの行だけを対象化
   → リマインド返信下書き＋クロージング支援メモを MIME 化 → sales@ Drafts へ APPEND（\Draft・送信しない）

重複防止：リマインド下書きの X-ITS-Key は原提案キー＋"|FU{n}" ＝ 実行跨ぎで sales@ Drafts を検索して
二重作成を防ぐ（原提案の下書きとも衝突しない）。既定は1提案につきリマインド1通（FOLLOWUP_MAX）。

環境変数：
  NOTION_TOKEN / NOTION_PAGE_ID   トラッカーDBの探索（run_ses_matching と共通）
  NOTION_DB_ID                    任意（トラッカーDBのidを固定。未設定なら親ページから探索）
  FOLLOWUP_BIZ_DAYS               リマインドまでの営業日しきい値（既定 3）
  FOLLOWUP_MAX                    1提案あたりのリマインド上限（既定 1）
  SALES_IMAP_HOST / SALES_IMAP_PASSWORD / SALES_IMAP_USER / SALES_DRAFTS_FOLDER   下書き保存（未設定ならスキップ）
  MARGIN_YEN                      単価交渉メモの粗利前提（既定 50000＝¥5万）

使い方：
  # オフライン（Notion/IMAP不要・決定論）でフィクスチャを流して配線と下書き文面を確認
  python followup.py --offline --input examples/sample-followup.json --date 2026-07-30
  # 本番（Actions・要 NOTION_* / SALES_IMAP_* Secrets）：送信済の停滞提案へリマインド下書きを自動生成
  python followup.py --source notion
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_ses_matching as R  # noqa: E402  署名/ガードレール/IMAP/Notionヘルパを再利用

MARGIN_YEN = int(R._env("MARGIN_YEN", "50000"))


# ---------- 日付・営業日 ----------
def parse_iso_to_jst_date(ts):
    """Notion の last_edited_time（RFC3339・UTC 例 '2026-07-27T09:12:00.000Z'）を JST の暦日に変換。
    パースできなければ None（＝送信日不明として対象外に倒す・捏造しない）。"""
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        # 秒未満やタイムゾーン表記の揺れに対する保険（先頭10桁の日付だけでも拾う）
        try:
            return datetime.date.fromisoformat(ts.strip()[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(R._JST).date()


def biz_days_between(start, end):
    """start（送信日）より後、end（基準日）までの営業日数（土日除外・祝日は将来拡張）。
    純粋関数。end <= start は 0。start/end が None なら -1（＝判定不能＝対象外に倒す）。"""
    if start is None or end is None:
        return -1
    if end <= start:
        return 0
    n = 0
    d = start
    while d < end:
        d = d + datetime.timedelta(days=1)
        if d.weekday() < 5:   # Mon-Fri
            n += 1
    return n


# ---------- キー（重複防止） ----------
def followup_key(orig_key, n):
    """リマインド下書きの X-ITS-Key。原提案キー＋'|FU{n}' で原提案の下書きと衝突させない。
    n はリマインド回数（1..FOLLOWUP_MAX）。"""
    return f"{str(orig_key or '').strip()}|FU{int(n)}"


# ---------- 文面（決定論・テンプレ差し込み） ----------
def load_reminder_template():
    return R.read("template-リマインド.txt") or ""


def reminder_parts(row):
    """送信済の1行から『件名／宛先／本文』を決定論で作る（リマインド返信）。純粋関数。"""
    tmpl = load_reminder_template()
    title = (row.get("title") or f"{row.get('engineer','')} × {row.get('case','')}").strip()
    pers = (row.get("person") or "").strip() or "ご担当者"
    subj_base = R._fmt_reply_subject(row.get("case") or title)
    body = (tmpl
            .replace("{担当者名}", pers)
            .replace("{案件×要員}", title)
            .replace("{署名}", R.load_signature())).strip()
    to = (row.get("to") or "要・宛先確認").strip() or "要・宛先確認"
    return {"subject": f"Re:{subj_base}の件_ITS村山", "to": to, "body": body}


def interview_slots_template(row):
    """面談日程調整の定型文（コピペ用・代表が候補時間を埋める）。返信が来た時にそのまま使える。"""
    title = (row.get("title") or "").strip()
    return (
        "――― 面談調整（返信が来たらコピペして候補を記入）―――\n"
        f"{(row.get('person') or 'ご担当者')}様\n\n"
        "ご検討ありがとうございます。オンライン面談の候補日時を下記いたします。\n"
        "（下記よりご都合のよい枠をお知らせください。所要30〜45分・Teams/Zoom等ご指定に合わせます）\n"
        "　・◯/◯（　）◯◯:◯◯〜\n"
        "　・◯/◯（　）◯◯:◯◯〜\n"
        "　・◯/◯（　）◯◯:◯◯〜\n"
        "上記でご都合が合わない場合は、貴社のご都合のよい候補を2〜3ついただけますと幸いです。\n"
        f"（案件：{title}）\n"
    )


def _yen(man_or_yen):
    """人が読める円表記の補助。数値(円)を『¥xx万』へ。Noneや0は '要確認'。"""
    try:
        v = int(man_or_yen)
    except (TypeError, ValueError):
        return "要確認"
    if v <= 0:
        return "要確認"
    if v % 10000 == 0:
        return f"¥{v // 10000}万"
    return f"¥{v:,}"


def rate_negotiation_qa(client_rate_yen=None, engineer_rate_yen=None, margin_yen=MARGIN_YEN):
    """単価交渉の想定問答（決定論）。**数値は与えられた実額のみ使用し、無ければ『要確認』**（捏造しない）。
    client_rate_yen＝案件予算（円）／engineer_rate_yen＝要員希望（円）。粗利＝margin_yen。"""
    c = _yen(client_rate_yen)
    e = _yen(engineer_rate_yen)
    gross = "要確認"
    if isinstance(client_rate_yen, (int, float)) and isinstance(engineer_rate_yen, (int, float)) \
            and client_rate_yen > 0 and engineer_rate_yen > 0:
        gross = _yen(int(client_rate_yen) - int(engineer_rate_yen))
    lines = [
        "――― 単価交渉 想定問答（送信前メモ・粗利死守 ¥8万/月）―――",
        f"　前提：案件予算={c} ／ 要員希望={e} ／ 想定粗利={gross}（不明は要確認・捏造しない）",
        "　Q. 「単価をもう少し上げられないか」",
        f"　A. 提示は{c}が上限想定。上げる場合は粗利下限(¥8万)を割らない範囲で要員希望{e}との差で調整。"
        "即答せず『社内確認します』で持ち帰る。",
        "　Q. 「他社はもっと安い」",
        "　A. 価格ではなくスキル適合・稼働開始の早さ・並行状況の確度で戻す（スキルシートの該当実績を指す）。",
        "　Q. 「開始時期を早められるか」",
        "　A. 要員の並行状況を再確認してから確約（未確認で前倒しを約束しない）。",
        "　Q. 「面談前に単価だけ確定したい」",
        "　A. スキル確認（面談）とセットが原則。単価は面談通過を前提に社内確認、と伝える。",
        "　※ 粗利が¥8万/月を割る条件は原則お断り（薄商流に依存しない・CLAUDE.md原則2）。",
    ]
    return "\n".join(lines)


def closing_kit_memo(row):
    """リマインド下書きに同梱する『クロージング支援メモ（送信前に削除）』。面談調整＋単価交渉を1本化。
    トラッカー行に単価が無ければ単価QAは『要確認』のまま（honest・数値捏造なし）。"""
    return (
        "\n\n"
        "＝＝＝【クロージング支援メモ｜送信前に削除してください】＝＝＝\n"
        + interview_slots_template(row)
        + "\n"
        + rate_negotiation_qa(row.get("client_rate_yen"), row.get("engineer_rate_yen"))
        + "\n＝＝＝（ここまでメモ・本文には含めない）＝＝＝"
    )


# ---------- 対象判定（純粋関数・テスト可） ----------
def select_due_reminders(rows, base_date, threshold, max_fu, already_keys):
    """送信済の行から『リマインド対象』を決定論で選ぶ。
    条件：送信日から threshold 営業日以上経過（音沙汰なしの代理）＋ 既に同じ FUキーの下書きが無い。
    返り値：[(row, n)]（n＝何通目のリマインドか）。already_keys＝既存の X-ITS-Key 集合。純粋関数。"""
    due = []
    for row in rows:
        sent = row.get("sent_date")
        elapsed = biz_days_between(sent, base_date)
        if elapsed < threshold:   # 送信日不明(-1)や未達はスキップ（捏造せず対象外）
            continue
        orig = row.get("key") or R._its_key(row.get("case"), row.get("engineer"))
        # まだ作っていない最小の n（1..max_fu）を1通だけ
        for n in range(1, int(max_fu) + 1):
            if followup_key(orig, n) not in already_keys:
                due.append((dict(row, key=orig), n))
                break
    return due


# ---------- MIME 下書き組み立て（ネット不要・テスト可） ----------
def build_reminder_message(row, n, with_kit=True):
    """リマインド返信を送信可能な MIME（下書き）に組み立てる。ガードレール違反なら (None, issues)。送信はしない。"""
    import email.message

    p = reminder_parts(row)
    check = R.validate_draft(f"From: {R.SALES_FROM}\nTo: {p['to']}\n件名: {p['subject']}\n\n{p['body']}")
    if check:
        return None, check
    to_ok = ("@" in p["to"]) and R._is_sendable_addr(p["to"])
    prefix = ""
    if not to_ok:
        prefix += "※宛先未確定：送信前に配信元担当のアドレスを To に入れてください。\n\n"
    body = prefix + p["body"] + (closing_kit_memo(row) if with_kit else "")
    msg = email.message.EmailMessage()
    msg["From"] = R.SALES_FROM
    if to_ok:
        msg["To"] = p["to"]
    msg["Subject"] = p["subject"]
    msg["X-ITS-Key"] = followup_key(row.get("key"), n)
    msg.set_content(body)
    return msg, []


# ---------- Notion：送信済の行を取得 ----------
def fetch_sent_rows_from_notion(token, db_id, page_limit=200):
    """トラッカーDBから ステータス=送信済 の行を取得し、正規化した行のリストで返す（best-effort）。
    各行：{key, title, engineer, case, to, company, person, sent_date(date)}。sent_date＝last_edited_time(JST)。"""
    rows, cursor = [], None
    for _ in range(0, max(1, page_limit // 100) + 1):
        body = {"filter": {"property": "ステータス", "select": {"equals": "送信済"}}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = R._notion_api("POST", f"https://api.notion.com/v1/databases/{db_id}/query", token, body)
        if not res:
            break
        for pg in res.get("results", []):
            rows.append(_row_from_notion_page(pg))
        if res.get("has_more") and res.get("next_cursor"):
            cursor = res["next_cursor"]
        else:
            break
    return [r for r in rows if r]


def _plain(prop):
    """Notion property から素のテキストを取り出す小ヘルパ（title/rich_text/select 対応）。"""
    if not isinstance(prop, dict):
        return ""
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in prop.get(t, []) if isinstance(x, dict)).strip()
    if t == "select":
        sel = prop.get("select") or {}
        return (sel.get("name") or "").strip()
    return ""


def _row_from_notion_page(pg):
    """Notionページ1件を正規化行へ。title『engineer × case』を分解し、配信元から担当者名を推定。"""
    if not isinstance(pg, dict):
        return None
    props = pg.get("properties", {}) or {}
    title = _plain(props.get("案件×要員", {}))
    key = _plain(props.get("キー", {}))
    to = _plain(props.get("宛先To", {}))
    haishin = _plain(props.get("配信元", {}))      # 例 "◯◯株式会社 田中"
    engineer, case = "", ""
    if " × " in title:
        engineer, case = [s.strip() for s in title.split(" × ", 1)]
    company, person = haishin, ""
    parts = haishin.split()
    if len(parts) >= 2:
        company, person = parts[0], " ".join(parts[1:])
    sent_date = parse_iso_to_jst_date(pg.get("last_edited_time"))
    return {"key": key or R._its_key(case, engineer), "title": title or f"{engineer} × {case}",
            "engineer": engineer, "case": case, "to": to or "要・宛先確認",
            "company": company, "person": person, "sent_date": sent_date}


# ---------- sales@ Drafts へ保存（IMAP APPEND・送信しない） ----------
def _existing_followup_keys(M, folder_q):
    """下書きフォルダにある FU 系 X-ITS-Key を集める（実行跨ぎの重複防止）。select失敗時は空集合。"""
    keys = set()
    try:
        if M.select(folder_q)[0] != "OK":
            return keys, False
        typ, data = M.search(None, "HEADER", "X-ITS-Key", "|FU")
        if typ == "OK" and data and data[0].split():
            for num in data[0].split():
                try:
                    typ2, md = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (X-ITS-Key)])")
                    if typ2 == "OK" and md and md[0]:
                        raw = md[0][1].decode("utf-8", "ignore") if isinstance(md[0][1], bytes) else str(md[0][1])
                        for line in raw.splitlines():
                            if line.lower().startswith("x-its-key:"):
                                keys.add(line.split(":", 1)[1].strip())
                except Exception:  # noqa
                    continue
        return keys, True
    except Exception:  # noqa
        return keys, False


def save_reminders_to_sales(due, base_date):
    """リマインド下書きを sales@ の下書きフォルダへ APPEND（\\Draft・送信はしない）。
    SALES_IMAP_HOST/PASSWORD 未設定ならスキップ。既存FUキーは作らない（実行跨ぎ重複防止）。"""
    host = R._env("SALES_IMAP_HOST")
    pw = R._env("SALES_IMAP_PASSWORD")
    user = R._env("SALES_IMAP_USER", R.SALES_FROM)
    if not (host and pw):
        print("[followup] SALES_IMAP_HOST/PASSWORD 未設定のため下書き保存はスキップ（Secret登録で有効化）")
        return 0
    import imaplib
    import time as _time

    port = int(R._env("SALES_IMAP_PORT", "993"))
    tmo = int(R._env("SALES_IMAP_TIMEOUT", "30"))
    tries = int(R._env("SALES_IMAP_RETRIES", "3"))
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
                print(f"[followup] 接続リトライ {attempt}/{tries}（{type(e).__name__}: {e}）→ {wait}秒待機")
                _time.sleep(wait)
            else:
                print(f"[followup] 接続失敗（{tries}回試行）。SALES_IMAP_* と到達性を確認: {e}")
                return 0
    saved = dup = skipped = 0
    folder = R._env("SALES_DRAFTS_FOLDER") or "Drafts"
    try:
        folder = R._env("SALES_DRAFTS_FOLDER") or R._detect_drafts_folder(M)
        folder_q = f'"{folder}"' if (" " in folder or "(" in folder) else folder
        print(f"[followup] 下書きフォルダ: {folder}")
        existing, selected = _existing_followup_keys(M, folder_q)
        for row, n in due:
            fk = followup_key(row.get("key"), n)
            if selected and fk in existing:
                dup += 1
                print(f"[followup] 既にリマインド下書きあり（重複回避）: {row.get('title')} FU{n}")
                continue
            msg, hard = build_reminder_message(row, n)
            if msg is None:
                skipped += 1
                print(f"[followup] スキップ（ガードレール違反）: {row.get('title')} {hard}")
                continue
            typ, _ = M.append(folder_q, "(\\Draft)", imaplib.Time2Internaldate(_time.time()), msg.as_bytes())
            if typ == "OK":
                saved += 1
                existing.add(fk)   # 同一run内の重複も防ぐ
                print(f"[followup] リマインド下書き保存: {row.get('title')} FU{n}")
            else:
                skipped += 1
                print(f"[followup] APPEND失敗（{typ}）: {row.get('title')}")
    except Exception as e:  # noqa  下書き保存の失敗は本体を止めない
        print(f"[followup] エラー: {e}")
    finally:
        try:
            M.logout()
        except Exception:  # noqa
            pass
    print(f"[followup] sales@ リマインド下書き：新規{saved}／重複回避{dup}／スキップ{skipped}（folder={folder}）")
    return saved


# ---------- オフライン入力（決定論・テスト/検証用） ----------
def load_offline_rows(path):
    """フィクスチャ(JSON)から送信済の行を読む。各要素：{key?,title?,engineer?,case?,to?,person?,sent_date}
    sent_date は 'YYYY-MM-DD'。Notion/IMAP 不要で下書き文面・対象判定を確認できる。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("rows", data) if isinstance(data, dict) else data
    rows = []
    for r in raw or []:
        sd = r.get("sent_date")
        if isinstance(sd, str):
            try:
                sd = datetime.date.fromisoformat(sd.strip()[:10])
            except ValueError:
                sd = None
        title = r.get("title") or f"{r.get('engineer','')} × {r.get('case','')}"
        rows.append({
            "key": r.get("key") or R._its_key(r.get("case"), r.get("engineer")),
            "title": title, "engineer": r.get("engineer", ""), "case": r.get("case", ""),
            "to": r.get("to", "要・宛先確認"), "company": r.get("company", ""),
            "person": r.get("person", ""), "sent_date": sd,
            "client_rate_yen": r.get("client_rate_yen"), "engineer_rate_yen": r.get("engineer_rate_yen"),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["notion", "offline"], default="offline")
    ap.add_argument("--offline", action="store_true", help="オフライン（決定論・Notion/IMAP不要）で走らせる")
    ap.add_argument("--input", default=None, help="offline時の行フィクスチャ(JSON)")
    ap.add_argument("--date", default=None, help="基準日 YYYY-MM-DD（省略時は本日JST）")
    ap.add_argument("--dry-run", action="store_true", help="下書き保存せず対象と文面だけ表示")
    args = ap.parse_args()
    if args.offline:
        args.source = "offline"

    base_date = (datetime.date.fromisoformat(args.date) if args.date
                 else datetime.datetime.now(R._JST).date())
    threshold = int(R._env("FOLLOWUP_BIZ_DAYS", "3"))
    max_fu = int(R._env("FOLLOWUP_MAX", "1"))

    if args.source == "notion":
        token = os.environ.get("NOTION_TOKEN")
        parent = R._env("NOTION_PAGE_ID") or R._env("NOTION_PARENT_ID")
        if not token or not parent:
            print("[followup] NOTION_TOKEN / NOTION_PAGE_ID 未設定のため実行できません（Secret登録で有効化）")
            return
        db_id = R._env("NOTION_DB_ID") or R.ensure_notion_db(token, parent)
        if not db_id:
            print("[followup] トラッカーDBが見つからないため終了（先に run_ses_matching で作成される想定）")
            return
        rows = fetch_sent_rows_from_notion(token, db_id)
    else:
        path = args.input or os.path.join(HERE, "examples", "sample-followup.json")
        rows = load_offline_rows(path)

    print(f"[followup] 送信済 {len(rows)} 件・基準日 {base_date}・しきい値 {threshold}営業日・上限 FU{max_fu}")

    # 既存FUキー（重複防止）：本番はDrafts検索で二重ガードするため、ここでは空集合から始める。
    due = select_due_reminders(rows, base_date, threshold, max_fu, already_keys=set())
    print(f"[followup] リマインド対象 {len(due)} 件")
    for row, n in due:
        print(f"   ・{row.get('title')}（送信日 {row.get('sent_date')}・{biz_days_between(row.get('sent_date'), base_date)}営業日経過）FU{n}")

    if args.dry_run or args.source == "offline":
        # 文面プレビュー（保存はしない＝決定論で確認）
        for row, n in due[:3]:
            msg, issues = build_reminder_message(row, n)
            print("-" * 60)
            if msg is None:
                print(f"[followup] 下書き不可（ガードレール）: {issues}")
            else:
                print(msg.get("Subject"))
                print(f"To: {msg.get('To') or '（未確定）'}")
                print(msg.get_content()[:800])
        print("-" * 60)
        print("[followup] （offline/dry-run のため sales@ への保存はしていません）")
        return

    save_reminders_to_sales(due, base_date)


if __name__ == "__main__":
    main()
