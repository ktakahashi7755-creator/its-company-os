#!/usr/bin/env python3
"""総当たりマッチング（run_ses_crossmatch）の決定論評価ハーネス。APIキー不要・退行検知（exit 1）。

営業日鮮度・スキル重なり・単価パース／利益・総当たりショートリスト・採点正規化・熱さ・
両面下書きのガードレール・オフライン完走 を回帰チェックする。すべてダミー（実在しない）。

  python eval/crossmatch_eval.py            # 全ステージ
  python eval/crossmatch_eval.py --stage freshness
"""
import argparse
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)
import run_ses_crossmatch as X  # noqa: E402
import run_ses_matching as R  # noqa: E402

BASE = datetime.date(2026, 7, 21)  # 火曜。過去3営業日＝7/16(木)/17(金)/20(月)/21(火)


def _runner(fn):
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1
        ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")
    fn(chk)
    print(f"   {fn.__name__} 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def freshness(chk):
    print("── 営業日鮮度（business_days_between / fresh_biz）")
    d = datetime.date
    chk("同日=0", X.business_days_between(d(2026, 7, 21), d(2026, 7, 21)) == 0)
    chk("前営業日(月→火)=1", X.business_days_between(d(2026, 7, 20), d(2026, 7, 21)) == 1)
    chk("金→火は土日跨ぎで2営業日", X.business_days_between(d(2026, 7, 17), d(2026, 7, 21)) == 2)
    chk("木→火は3営業日", X.business_days_between(d(2026, 7, 16), d(2026, 7, 21)) == 3)
    chk("水→火は4営業日", X.business_days_between(d(2026, 7, 15), d(2026, 7, 21)) == 4)
    chk("土日は営業日でない", not X.is_business_day(d(2026, 7, 18)) and not X.is_business_day(d(2026, 7, 19)))
    chk("3営業日以内は鮮度OK(7/16)", X.fresh_biz("2026-07-16", BASE, 3) is True)
    chk("4営業日前は鮮度NG(7/15)", X.fresh_biz("2026-07-15", BASE, 3) is False)
    chk("未来日は許容", X.fresh_biz("2026-07-25", BASE, 3) is True)
    chk("日付不明/不正は取りこぼし回避でTrue", X.fresh_biz(None, BASE, 3) and X.fresh_biz("13-40", BASE, 3))


def skills(chk):
    print("── スキル正規化・重なり（norm_skills / skill_overlap）")
    chk("同義語を正準化(network→nw)", "nw" in X.norm_skills(["Network", "ネットワーク"]))
    chk("同一集合の重なり=1.0", X.skill_overlap(["Java", "AWS"], ["java", "aws"]) == 1.0)
    chk("無関係=0.0", X.skill_overlap(["Java"], ["Cisco"]) == 0.0)
    chk("空は0.0", X.skill_overlap([], ["Java"]) == 0.0)
    ov = X.skill_overlap(["Cisco", "FW", "PL"], ["cisco", "fw"])
    chk("部分一致は0<ov<1", 0 < ov < 1)


def pricing(chk):
    print("── 単価パース・利益（parse_rate_man / quote_* / margin_feasible）")
    chk("〜80万→(80,80)", X.parse_rate_man("単価〜80万") == (80, 80))
    chk("60〜75万→(60,75)", X.parse_rate_man("希望60〜75万です") == (60, 75))
    chk("記載なし→(None,None)", X.parse_rate_man("単価応相談") == (None, None))
    chk("妥当域外(5万/500万)は無視", X.parse_rate_man("5万や500万") == (None, None))
    chk("案件元提示=要員希望+5万", X.quote_to_case(75) == 80)
    chk("要員元提示=案件予算-5万", X.quote_to_talent(85) == 80)
    chk("単価不明は None（捏造しない）", X.quote_to_case(None) is None and X.quote_to_talent(None) is None)
    chk("fmt: 数値→万円/月", X.fmt_man(80) == "80万円/月")
    chk("fmt: None→要確認", "要確認" in X.fmt_man(None))
    chk("余白10万=both", X.margin_feasible(85, 75) == "both")
    chk("余白5万=one", X.margin_feasible(80, 75) == "one")
    chk("余白2万=tight", X.margin_feasible(77, 75) == "tight")
    chk("単価不明=unknown", X.margin_feasible(None, 75) == "unknown")


def shortlist(chk):
    print("── 総当たりショートリスト（shortlist_pairs）")
    cases = [{"skills": ["Cisco", "FW"], "rate_max": 85, "title": "NW"},
             {"skills": ["Java", "AWS"], "rate_max": 70, "title": "Java"}]
    talents = [{"skills": ["cisco", "fw", "pl"], "rate_max": 75, "title": "T-NW"},
               {"skills": ["java", "aws"], "rate_max": 60, "title": "T-Java"},
               {"skills": ["php"], "rate_max": 55, "title": "T-PHP"}]
    pairs = X.shortlist_pairs(cases, talents, overlap_min=0.12, max_pairs=10)
    keys = {(c["title"], t["title"]) for c, t, _ in pairs}
    chk("NW×T-NW を含む", ("NW", "T-NW") in keys)
    chk("Java×T-Java を含む", ("Java", "T-Java") in keys)
    chk("無関係(PHP)は含まない", not any(t["title"] == "T-PHP" for _, t, _ in pairs))
    # 予算<希望は落とす
    p2 = X.shortlist_pairs([{"skills": ["Java"], "rate_max": 50, "title": "安"}],
                           [{"skills": ["java"], "rate_max": 80, "title": "高"}], overlap_min=0.12)
    chk("予算<希望のペアは除外", p2 == [])
    chk("重なり降順に並ぶ", all(pairs[i][2] >= pairs[i + 1][2] for i in range(len(pairs) - 1)))


def scoring(chk):
    print("── ペア採点の正規化（normalize_pair_score）")
    full = {"スキル適合": 40, "単価整合": 20, "稼働": 12, "勤務地": 10, "商流": 10, "見せ方": 8}
    r = X.normalize_pair_score({"breakdown": dict(full), "match": 0})
    chk("match＝内訳合計(100)に確定", r["match"] == 100)
    over = {"スキル適合": 99, "単価整合": 20, "稼働": 12, "勤務地": 10, "商流": 10, "見せ方": 8}
    r = X.normalize_pair_score({"breakdown": over, "match": 500})
    chk("軸上限クランプ(スキル40)", r["breakdown"]["スキル適合"] == 40 and r["match"] == 100)
    chk("非dict breakdownはmatchクランプ", X.normalize_pair_score({"match": 150, "breakdown": "x"})["match"] == 100)
    chk("文字列matchも数値化", X.normalize_pair_score({"match": "88", "breakdown": None})["match"] == 88)
    chk("非dict入力でも落ちない", X.normalize_pair_score("nope")["match"] == 0)


def hot(chk):
    print("── 熱さ（hotness・決定論）")
    fresh_hot = {"date": "2026-07-21", "urgency": "急募", "business_flow": "元請直", "rate_max": 85,
                 "subject": "急募", "body": "急募"}
    cold = {"date": "2026-07-16", "urgency": "不明", "business_flow": "2次", "rate_max": 70,
            "subject": "", "body": ""}
    t = {"rate_max": 75}
    hh, hc = X.hotness(fresh_hot, t, BASE), X.hotness(cold, t, BASE)
    chk("急募・元請直・当日は高い", hh >= 90)
    chk("古い・2次は低い", hc < hh)
    chk("0-100に収まる", 0 <= hh <= 100 and 0 <= hc <= 100)


def drafts(chk):
    print("── 両面下書きのガードレール（build_pair_drafts）")
    case = {"title": "NW案件", "skills": ["Cisco", "FW"], "rate_max": 85, "location": "恵比寿",
            "start": "8月", "business_flow": "元請直", "summary": "NW/Sec支援",
            "from_addr": "sato@alpha.example.co.jp", "from_name": "アルファ", "body": "担当 sato@alpha.example.co.jp"}
    talent = {"title": "NW要員", "skills": ["Cisco", "FW", "PL"], "rate_max": 75, "start": "即日",
              "business_flow": "自社", "seniority": "PL", "summary": "両刀PL",
              "from_addr": "tanaka@beta.example.co.jp", "from_name": "ベータ", "body": "担当 tanaka@beta.example.co.jp"}
    d = X.build_pair_drafts({"case": case, "talent": talent})
    cs, ts = d["case_source"], d["talent_source"]
    chk("案件元: From=sales@", cs["from"] == R.SALES_FROM)
    chk("案件元: 提示単価=希望75+5=80万（社内単価＋50,000円）",
        "80万円/月" in cs["body"] and "社内単価＋50,000円" in cs["body"])
    chk("案件元: 正式文面（件名RE:・書き出し・要員サマリー）",
        cs["subject"].startswith("RE:") and "ご紹介可能な要員をご提案いたします" in cs["body"]
        and "＜要員サマリー＞" in cs["body"])
    chk("案件元: 署名(村山 愛/E-mail)あり", "村山 愛" in cs["body"] and "sales@its-tokyo.com" in cs["body"])
    chk("案件元: ガードレール違反ゼロ", cs["issues"] == [])
    chk("案件元: スキルシート添付情報を持つ", "attachments" in cs)
    chk("要員元: 提示単価=予算85-5=80万", "80万円/月" in ts["body"])
    chk("要員元: 正式文面（件名【案件紹介】…様向け案件のご案内）",
        ts["subject"].startswith("【案件紹介】") and ts["subject"].endswith("様向け案件のご案内"))
    chk("要員元: 正式文面の書き出し・案件概要ブロック",
        "配信にてご共有いただきました" in ts["body"] and "＜案件概要＞" in ts["body"] and "単金：" in ts["body"])
    chk("要員元: 署名（村山 愛／E-mail）", "村山 愛" in ts["body"] and "sales@its-tokyo.com" in ts["body"])
    chk("要員元: ガードレール違反ゼロ", ts["issues"] == [])
    chk("REOorGA不在(両下書き)", R.REOORGA_ADDR not in cs["body"] and R.REOORGA_ADDR not in ts["body"])
    # 単価不明なら要確認（捏造しない）
    d2 = X.build_pair_drafts({"case": {**case, "rate_max": None}, "talent": {**talent, "rate_max": None}})
    chk("単価不明→両下書きに要確認", "要確認" in d2["case_source"]["body"] and "要確認" in d2["talent_source"]["body"])
    # フェイルクローズ：案件元の連絡先が REOorGA でも、To は要確認に倒れ、本文にも reorga を出さない
    bad = X.build_pair_drafts({"case": {**case, "from_addr": "dist@reorga.co.jp", "body": "返信は dist@reorga.co.jp まで"},
                               "talent": talent})
    chk("reorga宛は要確認に倒れ本文にも出ない",
        bad["case_source"]["to"] == "要・宛先確認"
        and "reorga" not in X._draft_text(bad["case_source"]).lower())
    # MIME組み立て：案件元向けにスキルシートを添付（sales@ 下書き保存用）
    cs_att = {**cs, "_ss_files": [("技術経歴書_KT.xlsx", b"PK\x03\x04dummy")], "_key": "abc123"}
    m, hard = X.build_pair_mime(cs_att)
    chk("MIME: 組み立て成功", m is not None and not hard)
    if m is not None:
        chk("MIME: From=sales@／X-ITS-Key付与", m["From"] == R.SALES_FROM and m["X-ITS-Key"] == "abc123")
        chk("MIME: スキルシートを添付", [a.get_filename() for a in m.iter_attachments()] == ["技術経歴書_KT.xlsx"])
    # フェイルクローズ：From違反(reorga)ならMIMEを作らない（None＋違反理由）
    m2, hard2 = X.build_pair_mime({"from": "contact@reorga.co.jp", "to": "x@y.co.jp",
                                   "subject": "x", "body": "村山 its-tokyo.com"})
    chk("MIME: From違反は作らない(None)", m2 is None and bool(hard2))


def offline_e2e(chk):
    print("── オフライン完走E2E（分類→総当たり→95%→両面下書き）")
    items = R.load_from_files([os.path.join(PARENT, "examples", "sample-crossmatch.md")])
    fresh = [it for it in items if X.fresh_biz(it.get("date"), BASE)]
    enriched = X.offline_classify(fresh)
    picked, allp = X.build_pairs(enriched, BASE, scorer=X.offline_score_pair)
    chk("サンプルで案件・要員が分類される",
        any(e["type"] == "案件" for e in enriched) and any(e["type"] == "要員" for e in enriched))
    chk("95%以上ペアが1件以上出る", len(picked) >= 1)
    chk("全picked が MATCH_MIN 以上", all(p["match"] >= X.MATCH_MIN for p in picked))
    chk("熱さ順に並ぶ", all(picked[i]["hot"] >= picked[i + 1]["hot"] for i in range(len(picked) - 1)))
    for p in picked:
        p["drafts"] = X.build_pair_drafts(p)
    chk("全picked に両面下書き・違反ゼロ",
        all(p["drafts"]["case_source"]["issues"] == [] and p["drafts"]["talent_source"]["issues"] == []
            for p in picked))
    chk("見出し(#)・配信日・担当・メールが要約に残らない",
        all("配信日" not in p["case"]["summary"] and "@" not in p["case"]["summary"]
            and not p["case"]["title"].startswith("#") for p in picked))
    dig = X.render_digest(picked, BASE, len(fresh), 3, 3)
    chk("digestに95%章と両面下書き", f"マッチ度{X.MATCH_MIN}%以上" in dig and "案件元への下書き" in dig and "要員元への下書き" in dig)


STAGES = {"freshness": freshness, "skills": skills, "pricing": pricing, "shortlist": shortlist,
          "scoring": scoring, "hot": hot, "drafts": drafts, "offline_e2e": offline_e2e}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=list(STAGES) + ["all"], default="all")
    args = ap.parse_args()
    print(f"[cross-eval] base={BASE} provider={R.LLM_PROVIDER}")
    results = []
    for name, fn in STAGES.items():
        if args.stage in (name, "all"):
            results.append(_runner(fn))
    sys.exit(1 if any(r is False for r in results) else 0)


if __name__ == "__main__":
    main()
