#!/usr/bin/env python3
"""人材（要員）の受付→台帳登録＋案件台帳との**決定論マッチング**＋提案下書きを自動生成する。

「案件を投入」（intake_case.py）と対称の「人材を投入」。代表はスマホで「新人材」Issue（フォーム）に
スキルシート本文＋数項目（年齢・希望単価・稼働・両刀の軸ヒント）を貼るだけ。本スクリプトが：
  1) data/talents.json  … 人材台帳へ upsert（以後この人材は案件投入時のマッチ対象になる）
  2) 人材_<id>.md       … 内部プロフィール＋客先貼付用サマリー（年齢は自動除去）
  3) digests/proposal-*.txt … 台帳の案件と自動マッチし、最有力案件への提案下書き（レビュー用）
生成物は PR で提出され、代表はマージ＋下書き確認するだけ（会話のやり取り不要）。
**メール送信は一切しない**（送信は必ず代表が手動・sales@ から）。

使い方（ワークフロー）:
  ISSUE_BODY="<issue form body>" python intake_talent.py --date 2026-08-06
  # ローカル確認:
  python intake_talent.py --body-file sample.md --date 2026-08-06 --dry-run
"""
import argparse
import json
import os
import re
import sys

import match_core as MC
from intake_case import parse_issue_form, _field, _slug   # フォーム解析は案件側と共用（重複しない）

HERE = os.path.dirname(os.path.abspath(__file__))

AXIS_MAP = {
    "サーバ×NW": "サーバ×NW", "NW×セキュリティ": "NW×セキュリティ",
    "NW×Sec": "NW×セキュリティ", "サーバ×セキュリティ": "サーバ×セキュリティ", "指定なし": "指定なし（広め）",
}


def _axis_hint(label):
    label = (label or "").strip()
    for k, v in AXIS_MAP.items():
        if k in label:
            return v
    return ""   # ヒント任意（マッチは案件側の軸で判定する）


def strip_age(text):
    """客先/案件元へ出す文面から年齢の記載を落とす（法令グレー回避＝案件MAIL-BLOCKと同じ規律）。"""
    out = []
    for line in (text or "").splitlines():
        if re.search(r"\d{1,2}\s*[歳才]", line) or "年齢" in line:
            continue
        out.append(line.rstrip())
    return "\n".join(l for l in out if l.strip()).strip()


def build_talent(form, date_str):
    name = _field(form, "識別", "イニシャル", "氏名", "人材名") or "要員"
    skills = _field(form, "スキルシート", "スキル", "経歴", "職務")
    age = _field(form, "年齢")
    rate = _field(form, "希望単価", "単価")
    avail = _field(form, "稼働", "参画")
    axis_hint = _axis_hint(_field(form, "両刀", "軸"))
    bp = _field(form, "所属", "BP", "配信元")
    summary = strip_age(skills)[:400]
    talent_id = f"{date_str.replace('-', '')}_{_slug(name)}"
    rec = {
        "talent_id": talent_id,
        "name": name,
        "age": age,
        "rate": rate,
        "availability": avail,
        "axis_hint": axis_hint,
        "bp": bp,
        "skills": skills,
        "summary": summary,
        "status": "active",
        "updated": date_str,
        "note": "Issue受付→intake_talent.py が自動生成。手編集も可。",
    }
    return rec


def _load_template(name):
    try:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def build_proposal_draft(talent, top):
    """最有力案件（top＝match_core の1件）への提案下書き（案件元向け・決定論・年齢は出さない）。
    宛先は投入時点で未確定＝プレースホルダ。送信は代表が手動。"""
    case = top["case"]
    m = top["match"]
    tmpl = _load_template("template-案件元向け.txt") or (
        "{担当者名}\n\n【{案件名}】\n＜要員サマリー＞\n{要員サマリー}\nご提案単価：{提案単価}\n")
    eng_rate = case.get("engineer_rate_pref") or talent.get("rate") or "スキル見合い"
    body = (tmpl
            .replace("{担当者名}", "ご担当者")
            .replace("{案件名}", str(case.get("case_title") or case.get("case_id") or "案件"))
            .replace("{要員サマリー}", strip_age(talent.get("summary") or talent.get("skills") or ""))
            .replace("{提案単価}", str(eng_rate)))
    header = (
        f"From: sales@its-tokyo.com\n"
        f"To: 要・宛先確認（案件元担当のアドレスを確認して入力）\n"
        f"件名: 【ご提案】{case.get('case_title','案件')} ／ {talent.get('name','要員')}\n"
        f"--- レビュー用下書き（決定論生成・送信は代表が手動・sales@から）---\n"
        f"■自動マッチ判定： {m['verdict']}／{m['score']}点"
        f"（{m['reason']}）{('／⚠ ' + '・'.join(m['flags'])) if m['flags'] else ''}\n\n"
    )
    return header + body.strip() + "\n"


def build_profile_md(talent, matches, date_str):
    name = talent["name"]
    top_lines = []
    for r in matches[:5]:
        m = r["match"]
        flags = ("／⚠ " + "・".join(m["flags"])) if m["flags"] else ""
        top_lines.append(
            f"| {m['verdict']} | {m['score']} | {r['case'].get('case_title', r['case'].get('case_id',''))} "
            f"| {m['reason']}{flags} |")
    table = "\n".join(top_lines) or "| — | — | （案件台帳が空） | — |"
    return f"""# 人材プロフィール（自動受付・要レビュー）：{name}

人材ID：`{talent['talent_id']}`　／　登録日：{date_str}　／　**Issue受付から自動生成（intake_talent.py）**

> このファイルは Issue 受付から**決定論で自動生成**されました。§3 の客先貼付用サマリーは**年齢を自動除去済み**ですが、必ず目視確認を。

## 1. 内部プロフィール（社内・年齢含む）
| 項目 | 内容 |
|---|---|
| 氏名/イニシャル | {name} |
| 年齢 | {talent.get('age') or '要確認'} |
| 希望単価 | {talent.get('rate') or '要確認'} |
| 稼働 | {talent.get('availability') or '要確認'} |
| 両刀の軸ヒント | {talent.get('axis_hint') or '（案件側で判定）'} |
| 所属BP/配信元 | {talent.get('bp') or '要確認'} |

## 2. 案件台帳との自動マッチ（決定論・投入時点）
| 判定 | 点 | 案件 | 根拠 |
|---|---|---|---|
{table}

> 本命＝両刀成立×年齢適合×粗利OK×しきい値以上。本番の面談通過可能性は run_ses_matching / crossmatch（LLM）で別途採点。

## 3. 客先/案件元 貼付用サマリー（MAIL-BLOCK・年齢除去済み）
<!-- MAIL-BLOCK-START -->
{strip_age(talent.get('skills') or '')}
＝＝＝＝＝＝＝＝＝＝＝＝＝＝
<!-- MAIL-BLOCK-END -->
"""


def run(body, date_str):
    form = parse_issue_form(body)
    talent = build_talent(form, date_str)
    cases = MC.load_cases()
    matches = MC.match_talent_to_cases(talent, cases)
    profile_md = build_profile_md(talent, matches, date_str)
    return talent, profile_md, matches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="登録日 YYYY-MM-DD")
    ap.add_argument("--body-file", help="Issue本文ファイル（無ければ環境変数 ISSUE_BODY）")
    ap.add_argument("--dry-run", action="store_true", help="ファイルを書かず内容を表示のみ")
    args = ap.parse_args()
    body = open(args.body_file, encoding="utf-8").read() if args.body_file else os.environ.get("ISSUE_BODY", "")
    if not body.strip():
        sys.exit("Issue本文が空です（ISSUE_BODY か --body-file を指定）。")

    talent, profile_md, matches = run(body, args.date)
    profile_path = os.path.join(HERE, f"人材_{talent['talent_id']}.md")
    # 提案下書きは「本命／提案可」の実マッチのみ生成（参考・除外では下書きを作らない＝空振り防止）
    top = next((r for r in matches if r["match"]["verdict"] in ("本命", "提案可")), None)
    draft = build_proposal_draft(talent, top) if top else None

    if args.dry_run:
        print("=== talents.json (upsert) ===")
        print(json.dumps(talent, ensure_ascii=False, indent=2))
        print(f"\n=== {os.path.basename(profile_path)} ===")
        print(profile_md)
        if draft:
            print("=== proposal draft（レビュー用・未送信）===")
            print(draft)
        else:
            print("（マッチする案件が台帳に無いため下書きは未生成）")
        return

    # 台帳へ upsert
    talents = MC.upsert(MC.load_talents(), talent, "talent_id")
    MC.save_talents(talents)
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(profile_md)
    if draft:
        digest_dir = os.path.join(HERE, "digests")
        os.makedirs(digest_dir, exist_ok=True)
        dpath = os.path.join(digest_dir, f"proposal-{talent['talent_id']}-{top['case'].get('case_id','case')}.txt")
        with open(dpath, "w", encoding="utf-8") as f:
            f.write(draft)
    top_desc = (f"最有力＝{top['match']['verdict']}/{top['match']['score']}点"
                f"（{top['case'].get('case_title','')}）") if top else "台帳に該当案件なし"
    print(f"[intake_talent] 生成: talents.json（{len(talents)}件）/ 人材_{talent['talent_id']}.md ／ {top_desc}")


if __name__ == "__main__":
    main()
