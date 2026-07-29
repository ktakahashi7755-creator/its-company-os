#!/usr/bin/env python3
"""新案件の受付→設定を**決定論で**自動生成する（Issue受付ワークフローから呼ばれる）。

代表はスマホで「新案件」Issue（フォーム）を立て、JD＋数項目（両刀の軸・年齢方針・単価・鮮度・しきい値）
を入れるだけ。本スクリプトがそれを読み、次を生成する（LLM不使用＝ブレなし）：
  1) active-case.json  … 軸(プレフィルタ)・年齢ハード上限・鮮度・本命しきい値・単価（＝実行時に反映）
  2) 案件_<日付>_<slug>.md … 必須条件テーブル＋客先貼付用 MAIL-BLOCK（JDから年齢行を除去・単価は要員向けに正規化）
生成物は PR で提出され、代表はマージするだけ。会話のやり取りは不要。

使い方（ワークフロー）:
  ISSUE_BODY="<issue form body>" python intake_case.py --date 2026-07-29
  # ローカル確認:
  python intake_case.py --body-file sample.md --date 2026-07-29 --dry-run
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 両刀の軸ラベル（Issueフォームのdropdown）→ active-case.json の axis キー
AXIS_MAP = {
    "サーバ×NW": "サーバ×NW",
    "NW×セキュリティ": "NW×セキュリティ",
    "NW×Sec": "NW×セキュリティ",
    "サーバ×セキュリティ": "サーバ×セキュリティ",
    "指定なし": "指定なし（広め）",
}


def parse_issue_form(body):
    """GitHub Issue Form の本文（### ラベル\\n\\n値）を {ラベル: 値} に。"""
    out, cur, buf = {}, None, []
    for line in (body or "").splitlines():
        m = re.match(r"^###\s+(.*)$", line.strip())
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    # GitHub の未入力プレースホルダを空に
    for k, v in list(out.items()):
        if v.strip() in ("_No response_", "_なし_", "None"):
            out[k] = ""
    return out


def _field(form, *names, default=""):
    """ラベルの表記ゆれに強く取り出す（部分一致）。"""
    for n in names:
        for k, v in form.items():
            if n in k:
                return v.strip()
    return default


def _slug(name):
    s = re.sub(r"[\s　/\\:：<>|*?\"']+", "", name or "")
    return (s or "案件")[:24]


def _axis_key(label):
    label = (label or "").strip()
    for k, v in AXIS_MAP.items():
        if k in label:
            return v
    return "サーバ×NW"   # 既定＝現行


def _age_limit(label):
    """年齢方針ラベル → ハード上限(int) or None（フラグのみ/上限なし）。"""
    s = (label or "")
    if "ハード" in s or "除外" in s or "まで" in s:
        m = re.search(r"(\d{2})", s)
        if m:
            return int(m.group(1))
    return None


def clean_mailblock(jd, eng_rate):
    """JDを客先貼付用のMAIL-BLOCKに整形（決定論）：
      - 年齢の行は除去（属性は文面に出さない＝法令グレー回避）
      - 単価の値は要員向けレンジに正規化（内部のクライアント単価を客先に出さない）
    """
    lines = []
    skip_next_rate_value = False
    for raw in (jd or "").splitlines():
        line = raw.rstrip()
        low = line.replace(" ", "")
        # 年齢の記載は落とす（「35歳まで」「・35歳」「年齢：」「40歳程度」等）
        if re.search(r"\d{1,2}\s*歳", line) or "年齢" in line:
            continue
        # 単価の見出し直後の値、または単価を含む行は要員向けレンジに置換
        if skip_next_rate_value and re.search(r"[〜~\d]", line):
            lines.append(f"・{eng_rate}（スキル見合い）")
            skip_next_rate_value = False
            continue
        if re.search(r"単価", line):
            if re.search(r"[〜~\d]万", line):     # 「単価：80〜90万」等は行ごと置換
                lines.append(re.sub(r"[：:].*$", f"：{eng_rate}（スキル見合い）", line) if "：" in line or ":" in line else f"■単価\n・{eng_rate}（スキル見合い）")
            else:                                  # 「■単価」見出しのみ→次行の数値を置換
                lines.append(line)
                skip_next_rate_value = True
            continue
        lines.append(line)
    body = "\n".join(lines).strip()
    return body + "\n＝＝＝＝＝＝＝＝＝＝＝＝＝＝"


def build_case_md(form, date_str, axis, age_limit, client_rate, eng_rate, fresh, pickup):
    name = _field(form, "案件名", "識別") or "新案件"
    jd = _field(form, "JD", "案件内容", "業務内容", "案件JD")
    hard = f"{age_limit}歳まで（ハード除外＝{age_limit+1}歳以上は選定しない）" if age_limit else "指定なし（属性は自動除外せずフラグのみ）"
    mailblock = clean_mailblock(jd, eng_rate)
    return f"""# 案件定義（自動受付・要レビュー）：{name}

案件ID：`{date_str.replace('-', '')}_{_slug(name)}`　／　登録日：{date_str}　／　**Issue受付から自動生成（intake_case.py）**

> このファイルは Issue 受付から**決定論で自動生成**されました。マージ前に §2 の必須条件と §7 の MAIL-BLOCK（客先文面）を確認してください。
> 実行時の軸/年齢/単価/しきい値は `active-case.json` に入っています（このPRで同時更新）。

## 1. サマリー
{name}。両刀の軸＝**{axis}**。詳細は下記 JD（§8）。

## 2. 要件（マッチング基準・自動抽出は最小限＝JD原文を正とする）
| 項目 | 内容 |
|---|---|
| 両刀の軸（段階①ゲート） | **{axis}**（各群から最低1語必須） |
| 年齢 | **{hard}** |
| 単価 | クライアント支払 **{client_rate}** ／ 要員希望 **{eng_rate}** を優先（粗利¥8万死守） |
| 鮮度 | 配信 **{fresh}日**以内 |
| 本命しきい値 | **{pickup}点**以上（自動下書き/Notion本命） |

詳細な必須スキル・歓迎・勤務条件は §8 の JD 原文を参照（scoring.md の採点で評価）。

## 7. 注記（ガードレール）
- 年齢：{hard}。ハード上限がある場合は `active-case.json` の `age_hard_limit` で36歳以上等を自動除外（跨ぐ/不明は本命保留）。
- 外国籍等の属性は自動フィルタに組み込まない（法令グレー・記録のみ・代表判断）。
- 単価：要員希望が「クライアント見込 − 粗利¥8万」超は単価足切り。**客先文面(MAIL-BLOCK)には年齢を書かない・単価は要員向け**。

## 8. メール貼付用・案件本文（MAIL-BLOCK・客先へそのまま挿入）
`finalize_draft` が下のブロックをそのまま返信に差し込む。**年齢は自動除去済み／単価は要員向けに正規化済み**だが、必ず目視確認を。

<!-- MAIL-BLOCK-START -->
{mailblock}
<!-- MAIL-BLOCK-END -->
"""


def run(body, date_str):
    form = parse_issue_form(body)
    name = _field(form, "案件名", "識別") or "新案件"
    axis = _axis_key(_field(form, "両刀", "軸"))
    age_limit = _age_limit(_field(form, "年齢"))
    client_rate = _field(form, "クライアント", "支払単価") or "要確認"
    eng_rate = _field(form, "要員希望", "希望単価") or "要確認"
    fresh = _field(form, "鮮度") or "5"
    pickup = _field(form, "しきい値", "本命") or "85"
    fresh_i = int(re.search(r"\d+", fresh).group()) if re.search(r"\d+", fresh) else 5
    pickup_i = int(re.search(r"\d+", pickup).group()) if re.search(r"\d+", pickup) else 85

    case_id = f"{date_str.replace('-', '')}_{_slug(name)}"
    active = {
        "case_id": case_id,
        "case_title": name,
        "axis": axis,
        "age_hard_limit": age_limit,
        "fresh_days": fresh_i,
        "pickup_min": pickup_i,
        "client_rate": client_rate,
        "engineer_rate_pref": eng_rate,
        "updated": date_str,
        "note": "Issue受付→intake_case.py が自動生成。手編集も可。",
    }
    case_md = build_case_md(form, date_str, axis, age_limit, client_rate, eng_rate, fresh_i, pickup_i)
    return active, case_md, case_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="登録日 YYYY-MM-DD")
    ap.add_argument("--body-file", help="Issue本文ファイル（無ければ環境変数 ISSUE_BODY）")
    ap.add_argument("--dry-run", action="store_true", help="ファイルを書かず内容を表示のみ")
    args = ap.parse_args()
    body = open(args.body_file, encoding="utf-8").read() if args.body_file else os.environ.get("ISSUE_BODY", "")
    if not body.strip():
        sys.exit("Issue本文が空です（ISSUE_BODY か --body-file を指定）。")
    active, case_md, case_id = run(body, args.date)
    case_path = os.path.join(HERE, f"案件_{case_id}.md")
    if args.dry_run:
        print("=== active-case.json ===")
        print(json.dumps(active, ensure_ascii=False, indent=2))
        print(f"\n=== {os.path.basename(case_path)} ===")
        print(case_md)
        return
    # 旧アクティブ案件ファイルは archive へ退避（案件_ で始まる .md）
    arch = os.path.join(HERE, "archive")
    os.makedirs(arch, exist_ok=True)
    for fn in os.listdir(HERE):
        if fn.startswith("案件_") and fn.endswith(".md") and fn != f"案件_{case_id}.md":
            os.replace(os.path.join(HERE, fn), os.path.join(arch, fn))
    with open(os.path.join(HERE, "active-case.json"), "w", encoding="utf-8") as f:
        json.dump(active, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(case_path, "w", encoding="utf-8") as f:
        f.write(case_md)
    print(f"[intake] 生成: active-case.json / 案件_{case_id}.md（軸={active['axis']}・年齢上限={active['age_hard_limit']}・鮮度{active['fresh_days']}日・本命{active['pickup_min']}点）")


if __name__ == "__main__":
    main()
