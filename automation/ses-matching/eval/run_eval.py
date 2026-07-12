#!/usr/bin/env python3
"""SESマッチングの精度評価ハーネス。

「精度を上げる」を計測可能にする土台。ラベル付きの正解データ（fixtures_*.jsonl）に対して
パイプラインを走らせ、精度（precision/recall/F1・帯一致率）を数値で出す。
評価→改善→再評価 を回すための実行体。**すべてダミーの合成データ**（実在人物ではない）。

段階:
  prefilter … 段階①機械フィルタの精度。**APIキー不要・常に実行可**（決定論）。
  scoring   … 段階②LLM採点の帯（高/中/除外/flag）一致率。**APIキーが要る**（無ければskip）。

使い方:
  python run_eval.py                 # prefilter を評価（既定）
  python run_eval.py --stage scoring # LLM採点を評価（OPENAI/ANTHROPIC キーが必要）
  python run_eval.py --stage all
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)
import run_ses_matching as R  # noqa: E402

BASE_DATE = datetime.date(2026, 7, 12)  # fixtures の基準日（決定論のため固定）


def _load(name):
    rows = []
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def eval_prefilter():
    rows = _load("fixtures_prefilter.jsonl")
    tp = fp = fn = tn = 0
    misses = []
    for row in rows:
        items = [{"from_name": "", "from_addr": "", "subject": "",
                  "date": row["date"], "body": row["body"]}]
        kept, _ = R.prefilter(items, BASE_DATE, R.FRESH_DAYS)
        passed = bool(kept)
        want = bool(row["expect_pass"])
        if passed and want:
            tp += 1
        elif passed and not want:
            fp += 1
            misses.append((row, "誤通過(FP)"))
        elif not passed and want:
            fn += 1
            misses.append((row, "誤除外(FN)"))
        else:
            tn += 1
    p, r, f1 = _prf(tp, fp, fn)
    print("── 段階① プレフィルタ精度（決定論・APIキー不要）")
    print(f"   件数 {len(rows)}  TP {tp} / FP {fp} / FN {fn} / TN {tn}")
    print(f"   precision {p:.2f}  recall {r:.2f}  F1 {f1:.2f}  正解率 {(tp+tn)/len(rows):.2f}")
    for row, kind in misses:
        print(f"   ✗ {kind} [{row['id']}] {row['note']}")
    if not misses:
        print("   ✔ 全ケース正解（誤通過・誤除外なし）")
    return fp + fn == 0


def eval_scoring():
    if not (R._env("OPENAI_API_KEY") or R._env("ANTHROPIC_API_KEY")):
        print("── 段階② LLM採点：APIキー未設定のためスキップ（OPENAI_API_KEY か ANTHROPIC_API_KEY が必要）")
        return None
    rows = _load("fixtures_scoring.jsonl")
    items = [{"from_name": "", "from_addr": "", "subject": "", "date": r["date"], "body": r["body"]}
             for r in rows]
    kept, dropped = R.prefilter(items, BASE_DATE, R.FRESH_DAYS)
    result = R.score_with_llm(kept, dropped, BASE_DATE)
    # src→候補 / src→除外 を引けるよう対応表を作る（kept は元 items の部分集合）
    kept_bodies = {id(k): i for i, k in enumerate(kept)}  # 未使用だが将来の対応付け用
    band_by_body = {}
    for c in result.get("candidates", []):
        src = c.get("src")
        if isinstance(src, int) and 0 <= src < len(kept):
            band = "flag" if c.get("flags") else c.get("likelihood", "低")
            band_by_body[kept[src]["body"]] = band
    dropped_bodies = {d["body"] for d in dropped}
    ok = 0
    for row in rows:
        body = row["body"]
        want = row["expect_band"]
        if body in dropped_bodies:
            got = "除外"
        else:
            got = band_by_body.get(body, "除外")  # 候補に出なければ実質除外
        hit = (got == want) or (want == "除外" and got == "除外")
        ok += 1 if hit else 0
        mark = "✔" if hit else "✗"
        print(f"   {mark} [{row['id']}] 期待={want} 実際={got}  {row['note']}")
    print(f"── 段階② LLM採点 帯一致率： {ok}/{len(rows)} = {ok/len(rows):.2f}")
    return ok == len(rows)


DRAFT_CASES = [
    # (ラベル, 下書き文字列, 違反があるべきか)
    ("正常", "From: sales@its-tokyo.com\nTo: tanaka@intellect.co.jp\n件名：ご提案\n本文…\n"
             "ITS合同会社 営業部 村山愛 sales@its-tokyo.com HP https://its-tokyo.com/", False),
    ("From違反", "From: contact@reorga.co.jp\nTo: x@y.co.jp\n本文\nITS合同会社 sales@its-tokyo.com", True),
    ("REOorGA混入(本文)", "From: sales@its-tokyo.com\nTo: x@y.co.jp\n返信先 contact@reorga.co.jp まで\n"
                          "ITS合同会社 sales@its-tokyo.com its-tokyo.com", True),
    ("宛先REOorGAドメイン", "From: sales@its-tokyo.com\nTo: dist@reorga.co.jp\n本文\n"
                            "ITS合同会社 sales@its-tokyo.com", True),
    ("署名欠落", "From: sales@its-tokyo.com\nTo: x@y.co.jp\n件名\n本文のみ", True),
    ("空", "", True),
]


def eval_draft():
    print("── 下書き安全網（validate_draft・決定論・APIキー不要）")
    ok = 0
    for label, draft, want_issue in DRAFT_CASES:
        issues = R.validate_draft(draft)
        got_issue = bool(issues)
        hit = got_issue == want_issue
        ok += 1 if hit else 0
        mark = "✔" if hit else "✗"
        detail = ("／".join(issues) if issues else "問題なし")
        print(f"   {mark} [{label}] 期待={'違反あり' if want_issue else '正常'} → {detail}")
    print(f"   下書き検証 正解率： {ok}/{len(DRAFT_CASES)} = {ok/len(DRAFT_CASES):.2f}")
    return ok == len(DRAFT_CASES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["prefilter", "draft", "scoring", "all"], default="prefilter")
    args = ap.parse_args()
    print(f"[eval] provider={R.LLM_PROVIDER} base_date={BASE_DATE}")
    results = []
    if args.stage in ("prefilter", "all"):
        results.append(eval_prefilter())
    if args.stage in ("draft", "all"):
        results.append(eval_draft())
    if args.stage in ("scoring", "all"):
        results.append(eval_scoring())
    # 決定論部分に失敗があれば非0で返す（CI/反復で退行検知）
    hard_fail = any(r is False for r in results)
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
