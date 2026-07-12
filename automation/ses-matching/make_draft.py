#!/usr/bin/env python3
"""指示出し → 送信可能な下書き（1件）。

代表がチャットで「〔案件〕×〔イニシャル〕 出して」と指示したら、AIがこれを叩く。
その1件だけ、reply-template＋署名＋スキルシート要約から**送信可能な提案メール下書き**を確定生成する。

**このスクリプトは下書きを出すだけ。メール送信は一切しない**（送信は必ず代表が手動・ITSセールスから）。

候補の取得元（優先順）:
  1. --json PATH            候補JSONを明示（run_ses_matching.py が digests/candidates-YYYYMMDD.json に出力）
  2. --date YYYY-MM-DD      digests/candidates-YYYYMMDD.json を読む
  3. （既定）               digests/ の最新 candidates-*.json を読む
  4. --candidate-json '...' 候補1件のJSONを直接渡す（Notion/artifactから貼る用）

使い方:
  # 最新候補から「KH」を選んで送信可能な下書きを出す
  python make_draft.py --pick KH
  # 番号で選ぶ（ダイジェストの候補番号＝スコア降順）＋代表の補足指示つき
  python make_draft.py --pick 1 --note "単価は72万上限で。商流は元請直を強調"
  # 特定日の候補から
  python make_draft.py --date 2026-07-12 --pick T.Y
"""
import argparse
import glob
import json
import os
import sys

# 同ディレクトリの共通エンジンを再利用（下書き確定・LLM・設定は一箇所に集約）
from run_ses_matching import HERE, SALES_FROM, REOORGA_ADDR, finalize_draft


def load_candidates(args):
    if args.candidate_json:
        one = json.loads(args.candidate_json)
        return [one] if isinstance(one, dict) else list(one)
    if args.json:
        path = args.json
    elif args.date:
        path = os.path.join(HERE, "digests", f"candidates-{args.date}.json")
    else:
        cands = sorted(glob.glob(os.path.join(HERE, "digests", "candidates-*.json")))
        if not cands:
            sys.exit("候補JSONが見つかりません。先に run_ses_matching.py を実行するか、--candidate-json で渡してください。")
        path = cands[-1]
    if not os.path.exists(path):
        sys.exit(f"候補JSONが見つかりません: {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("candidates", data) if isinstance(data, dict) else data


def pick_candidate(cands, selector):
    """イニシャル（部分一致・大文字小文字無視）または 1始まりの番号（スコア降順）で選ぶ。"""
    ordered = sorted(cands, key=lambda c: c.get("score", 0), reverse=True)
    if selector.isdigit():
        i = int(selector)
        if 1 <= i <= len(ordered):
            return ordered[i - 1]
        sys.exit(f"番号 {i} は範囲外です（候補 {len(ordered)} 件）。")
    key = selector.replace(".", "").replace(" ", "").lower()
    hits = [c for c in ordered
            if key in str(c.get("engineer", "")).replace(".", "").replace(" ", "").lower()]
    if not hits:
        avail = " / ".join(f"{i+1}.{c.get('engineer','?')}" for i, c in enumerate(ordered))
        sys.exit(f"『{selector}』に一致する候補がありません。候補: {avail}")
    if len(hits) > 1:
        avail = " / ".join(f"{c.get('engineer','?')}（{c.get('case','?')}）" for c in hits)
        sys.exit(f"『{selector}』が複数一致。番号か案件で絞ってください: {avail}")
    return hits[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", help="要員イニシャル（例 KH / T.Y）または候補番号（スコア降順・1始まり）")
    ap.add_argument("--note", default="", help="代表の補足指示（単価強調・商流明記など）。任意")
    ap.add_argument("--date", default=None, help="candidates-YYYYMMDD.json の日付")
    ap.add_argument("--json", default=None, help="候補JSONのパスを明示")
    ap.add_argument("--candidate-json", default=None, help="候補1件のJSONを直接渡す")
    args = ap.parse_args()

    cands = load_candidates(args)
    if not cands:
        sys.exit("候補が空です。")

    if args.candidate_json:
        cand = cands[0]
    elif args.pick:
        cand = pick_candidate(cands, args.pick)
    elif len(cands) == 1:
        cand = cands[0]
    else:
        ordered = sorted(cands, key=lambda c: c.get("score", 0), reverse=True)
        listing = "\n".join(
            f"  {i+1}. {c.get('engineer','?')} × {c.get('case','?')}"
            f"（{c.get('score','?')}点・{c.get('likelihood','?')}）"
            for i, c in enumerate(ordered))
        sys.exit(f"--pick で1件選んでください。候補:\n{listing}")

    flags = "／".join(cand.get("flags", []) or [])
    draft = finalize_draft(cand, note=args.note)

    print("=" * 64)
    print(f"■ 送信可能な下書き： {cand.get('engineer','?')} × {cand.get('case','?')}"
          f"（{cand.get('score','?')}点・面談通過可能性 {cand.get('likelihood','?')}）")
    if flags:
        print(f"⚠️ 代表確認フラグ： {flags}")
    print("=" * 64)
    print(draft)
    print("=" * 64)
    print("■ 送信前チェック（代表・reply-template.md）")
    print(f"  [ ] From が ITSセールス（{SALES_FROM}）か／REOorGA（{REOORGA_ADDR}）になっていないか")
    print(f"  [ ] To が配信元担当のアドレスか（現在: {cand.get('to','要・宛先確認')}）")
    print("  [ ] 両刀（NW×Sec）・単価枠内（粗利¥8万）・商流OK・稼働開始が合うか")
    print("  [ ] スキルシートに誇張・虚偽がないか（強調順の最適化のみ）")
    if flags:
        print(f"  [ ] 属性フラグ（{flags}）を代表判断済みか")
    print("  → OKなら sales@ から手動送信。結果は data/pipeline.md へ。")


if __name__ == "__main__":
    main()
