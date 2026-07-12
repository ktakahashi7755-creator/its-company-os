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
        items = [{"from_name": "", "from_addr": "", "subject": row.get("subject", ""),
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
    """LLM採点の帯一致を**計測**する。※これは測定であり合否ゲートではない（Noneを返す）。
    LLMのばらつきや一時的なAPIエラーで本番実行(=Notion反映)を止めないため、失敗しても None。"""
    if not (R._env("OPENAI_API_KEY") or R._env("ANTHROPIC_API_KEY")):
        print("── 段階② LLM採点：APIキー未設定のためスキップ（OPENAI_API_KEY か ANTHROPIC_API_KEY が必要）")
        return None
    try:
        return _eval_scoring_inner()
    except Exception as e:  # noqa  計測失敗はゲートを落とさない
        print(f"── 段階② LLM採点：計測中にエラー（ゲートは落とさない）: {e}")
        return None


def _eval_scoring_inner():
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
    print(f"── 段階② LLM採点 帯一致率： {ok}/{len(rows)} = {ok/len(rows):.2f}（計測・非ゲート）")
    return None  # 計測のみ。合否ゲートにはしない


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


CONTACT_CASES = [
    # (ラベル, from_addr, body, 期待To)
    ("署名の担当アドレスを採用", "dist@reorga.co.jp",
     "案件のご案内です。\nインテレクト株式会社 田中\ntanaka@intellect.co.jp", "tanaka@intellect.co.jp"),
    ("REOorGA宛は使わない→要確認", "contact@reorga.co.jp",
     "配信専用アドレスからのご案内。返信は contact@reorga.co.jp まで。", "要・宛先確認"),
    ("noreplyは宛先にしない→要確認", "noreply@reorga.co.jp",
     "no-reply@service.example.com 宛には返信しないでください。", "要・宛先確認"),
    ("本文に担当なし・from_addrが会社直→from_addr採用", "tanaka@intellect.co.jp",
     "案件のご案内です。詳細は添付。", "tanaka@intellect.co.jp"),
    ("複数ドメインで曖昧→要確認", "dist@reorga.co.jp",
     "田中 tanaka@intellect.co.jp / 佐藤 sato@routezero.co.jp", "要・宛先確認"),
    ("自社アドレスis除外・会社直を採用", "dist@reorga.co.jp",
     "担当 田中 tanaka@intellect.co.jp（弊社 sales@its-tokyo.com ではない）", "tanaka@intellect.co.jp"),
]


def eval_contact():
    print("── 宛先(To)自動抽出（extract_contact・決定論・APIキー不要）")
    ok = 0
    for label, frm, body, want in CONTACT_CASES:
        got = R.extract_contact(frm, body, "")["to"]
        hit = got == want
        ok += 1 if hit else 0
        print(f"   {'✔' if hit else '✗'} [{label}] 期待={want} 実際={got}")
    print(f"   宛先抽出 正解率： {ok}/{len(CONTACT_CASES)} = {ok/len(CONTACT_CASES):.2f}")
    return ok == len(CONTACT_CASES)


def eval_dedup():
    print("── 既提案の重複検知（flag_duplicates・決定論・APIキー不要）")
    seen = {("遊技機メーカー NW/Sec", "KH")}
    result = {"candidates": [
        {"case": "遊技機メーカー NW/Sec", "engineer": "KH", "flags": []},   # 既提案→フラグ付くべき
        {"case": "遊技機メーカー NW/Sec", "engineer": "TY", "flags": []},   # 新規→付かない
    ]}
    R.flag_duplicates(result, seen)
    c0, c1 = result["candidates"]
    hit0 = "既提案・重複" in c0["flags"]
    hit1 = "既提案・重複" not in c1["flags"]
    for c, ok_, lbl in ((c0, hit0, "既提案KHにフラグ"), (c1, hit1, "新規TYは無フラグ")):
        print(f"   {'✔' if ok_ else '✗'} [{lbl}] flags={c['flags']}")
    print(f"   重複検知 正解率： {int(hit0)+int(hit1)}/2 = {(int(hit0)+int(hit1))/2:.2f}")
    return hit0 and hit1


def eval_finalize():
    """返信下書きの決定論テンプレ差し込み（finalize_draft）を検証。
    ①②③＋要員名が正しく入り、固定の案件本文が挿入され、ガードレール違反ゼロであること。"""
    print("── 返信下書きのテンプレ差し込み（finalize_draft・決定論・APIキー不要）")
    cand = {"case": "遊技機メーカー NW/Sec 支援", "engineer": "A.N", "company": "ルートゼロ株式会社",
            "person": "伝刀", "to": "要・宛先確認", "src_subject": "Re:【7/12】NW A.N 20年 即日"}
    d = R.finalize_draft(cand)
    checks = [
        ("From固定", d.startswith(f"From: {R.SALES_FROM}")),
        ("件名Re:…_ITS村山", "件名: Re:" in d and d.count("_ITS村山") == 1),
        ("Re:の重ね付け無し", "Re:Re:" not in d and "Re:【7/12】NW A.N 20年 即日" in d),
        ("会社名", "ルートゼロ株式会社" in d),
        ("担当者＋様", "伝刀様" in d),
        ("要員名＋様", "配信で頂きましたA.N様" in d),
        ("案件本文の固定挿入", "大手遊技機メーカー向けに" in d and "＝＝＝＝＝" in d),
        ("面談可能日を尋ねる", "オンライン面談可能日" in d),
        ("ガードレール違反ゼロ", R.validate_draft(d) == []),
        ("REOorGA不在", R.REOORGA_ADDR not in d),
    ]
    ok = 0
    for label, hit in checks:
        ok += 1 if hit else 0
        print(f"   {'✔' if hit else '✗'} [{label}]")
    # 未知の会社/担当はプレースホルダに倒れること
    d2 = R.finalize_draft({"case": "遊技機メーカー NW/Sec 支援", "engineer": "K.H"})
    ph = ("〇〇株式会社" in d2 and "ご担当者様" in d2)
    print(f"   {'✔' if ph else '✗'} [未知の会社/担当はプレースホルダ]")
    ok += 1 if ph else 0
    total = len(checks) + 1
    print(f"   テンプレ差し込み 正解率： {ok}/{total} = {ok/total:.2f}")
    return ok == total


def eval_drafts():
    """sales@ 下書きへ入れる MIME メールの組み立て（build_draft_message）を検証（ネットワーク不要）。
    From が sales@・件名 Re:○○_ITS村山・本文に案件本文・REOorGA不在。宛先未確定なら To 空＋注記。"""
    print("── sales@下書きのMIME組み立て（build_draft_message・決定論・APIキー不要）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    # 宛先ありの候補
    c1 = {"case": "遊技機メーカー NW/Sec 支援", "engineer": "A.N", "company": "ルートゼロ株式会社",
          "person": "伝刀", "to": "dento@routezero.example.co.jp", "src_subject": "NW A.N 20年", "likelihood": "中"}
    c1["_ss_files"] = [("技術経歴書_A.N.xlsx", b"PK\x03\x04dummy")]
    m1, hard1 = R.build_draft_message(c1)
    chk("組み立て成功(宛先あり)", m1 is not None and not hard1)
    if m1 is not None:
        chk("From=sales@", m1["From"] == R.SALES_FROM)
        chk("To=担当アドレス", m1["To"] == "dento@routezero.example.co.jp")
        chk("件名 Re:…_ITS村山", (m1["Subject"] or "").startswith("Re:") and (m1["Subject"] or "").endswith("_ITS村山"))
        bp = m1.get_body(preferencelist=("plain",))
        body = bp.get_content() if bp is not None else ""
        chk("本文に案件本文", "大手遊技機メーカー向けに" in body)
        chk("REOorGA不在", R.REOORGA_ADDR not in m1.as_string())
        atts = [p.get_filename() for p in m1.iter_attachments()]
        chk("スキルシート原本を添付", "技術経歴書_A.N.xlsx" in atts)
    # 宛先未確定の候補 → To 空＋注記
    c2 = {"case": "遊技機メーカー NW/Sec 支援", "engineer": "K.H", "company": "〇〇株式会社",
          "person": "", "to": "要・宛先確認", "likelihood": "高", "flags": ["年齢上限超・代表確認"]}
    m2, _ = R.build_draft_message(c2)
    chk("組み立て成功(宛先未確定)", m2 is not None)
    if m2 is not None:
        chk("To空(要確認は入れない)", m2["To"] is None)
        chk("本文に宛先未確定の注記", "宛先未確定" in m2.get_content())
        chk("本文に代表確認フラグ", "代表確認" in m2.get_content())
    print(f"   MIME組み立て 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_notion():
    """Notion候補ページの簡潔ブロック（_notion_blocks_from_result）を検証。
    要約・マッチ度・スキルシート要約を含み、返信本文（縦に広がる原因）は含まないこと。"""
    print("── Notion簡潔ブロック（_notion_blocks_from_result・決定論・APIキー不要）")
    res = {"candidates": [{
        "case": "遊技機メーカー NW/Sec 支援", "engineer": "A.N", "score": 65, "likelihood": "中", "tier": "①",
        "company": "ルートゼロ株式会社", "person": "伝刀", "to": "要・宛先確認", "summary": "Azure20年",
        "breakdown": {"必須": 18, "鮮度": 15, "単価": 12, "商流": 9, "タイミング": 7, "見せ方": 3, "継続": 1},
        "skillsheet_summary": "Cisco/F5設計〜運用、脆弱性診断。", "skillsheet_files": ["技術経歴書_A.N.xlsx"],
        "flags": ["年齢上限超・代表確認"],
        "draft": "From: sales@its-tokyo.com\n件名: Re:X_ITS村山\n\nルートゼロ株式会社\n伝刀様\nITS営業部の村山でございます。\n▼案件\n大手遊技機メーカー向けに"}],
        "excluded": [{"item": "M.R", "reason": "両刀足切り"}]}
    blocks = R._notion_blocks_from_result(res)
    allc = " ".join(b[b["type"]]["rich_text"][0]["text"]["content"]
                    for b in blocks if b["type"] != "divider")
    checks = [
        ("スコア/マッチ度を含む", "65/100" in allc and "マッチ内訳" in allc),
        ("サマリーを含む", "サマリー" in allc),
        ("スキルシート要約＋ファイル名を含む", "技術経歴書_A.N.xlsx" in allc and "スキルシート" in allc),
        ("返信本文を含まない(縦に広がらない)", "▼案件" not in allc and "村山でございます" not in allc),
        ("代表確認フラグを表示", "年齢上限超・代表確認" in allc),
        ("除外・低を含む", "両刀足切り" in allc),
    ]
    ok = sum(1 for _, c in checks if c)
    for label, c in checks:
        print(f"   {'✔' if c else '✗'} [{label}]")
    print(f"   Notion簡潔ブロック 正解率： {ok}/{len(checks)} = {ok/len(checks):.2f}")
    return ok == len(checks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage",
                    choices=["prefilter", "draft", "finalize", "drafts", "notion", "contact",
                             "dedup", "scoring", "all"],
                    default="prefilter")
    args = ap.parse_args()
    print(f"[eval] provider={R.LLM_PROVIDER} base_date={BASE_DATE}")
    results = []
    if args.stage in ("prefilter", "all"):
        results.append(eval_prefilter())
    if args.stage in ("draft", "all"):
        results.append(eval_draft())
    if args.stage in ("finalize", "all"):
        results.append(eval_finalize())
    if args.stage in ("drafts", "all"):
        results.append(eval_drafts())
    if args.stage in ("notion", "all"):
        results.append(eval_notion())
    if args.stage in ("contact", "all"):
        results.append(eval_contact())
    if args.stage in ("dedup", "all"):
        results.append(eval_dedup())
    if args.stage in ("scoring", "all"):
        results.append(eval_scoring())
    # 決定論部分に失敗があれば非0で返す（CI/反復で退行検知）
    hard_fail = any(r is False for r in results)
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
