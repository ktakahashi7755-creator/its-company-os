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
    R.reconcile_scores(result)  # 本番と同じ自己整合化（score＝内訳合計・帯導出・<60除外）後の帯を計測する
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
        ("末尾にITS村山の署名", "ITS合同会社 営業部　村山愛" in d and d.rstrip().endswith("◆◇")),
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
        body = m1.get_content()
        chk("本文に案件本文", "大手遊技機メーカー向けに" in body)
        chk("REOorGA不在", R.REOORGA_ADDR not in m1.as_string())
        chk("スキルシート添付なし（廃止）", list(m1.iter_attachments()) == [])
    # 宛先未確定の候補 → To 空＋注記
    c2 = {"case": "遊技機メーカー NW/Sec 支援", "engineer": "K.H", "company": "〇〇株式会社",
          "person": "", "to": "要・宛先確認", "likelihood": "高", "flags": ["年齢上限超・代表確認"]}
    m2, _ = R.build_draft_message(c2)
    chk("組み立て成功(宛先未確定)", m2 is not None)
    if m2 is not None:
        chk("To空(要確認は入れない)", m2["To"] is None)
        chk("本文に宛先未確定の注記", "宛先未確定" in m2.get_content())
        chk("本文に代表確認フラグ", "代表確認" in m2.get_content())
    # フェイルクローズ：To が REOorGA なら下書きを作らない（None＋違反理由）。＝送信物にreorgaを出さない最終網
    c3 = {"case": "遊技機メーカー NW/Sec 支援", "engineer": "X.Y", "company": "配信元",
          "person": "", "to": "dist@reorga.co.jp", "likelihood": "高"}
    m3, hard3 = R.build_draft_message(c3)
    chk("REOorGA宛は下書き化しない(None)", m3 is None and bool(hard3))
    print(f"   MIME組み立て 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_notion():
    """Notion候補ページの簡潔ブロック（_notion_blocks_from_result）を検証。
    要約・マッチ度・スキルシート要約を含み、返信本文（縦に広がる原因）は含まないこと。"""
    print("── Notion簡潔ブロック（_notion_blocks_from_result・決定論・APIキー不要）")
    res = {"candidates": [{
        "case": "遊技機メーカー NW/Sec 支援", "engineer": "A.N", "score": 65, "likelihood": "中", "tier": "①",
        "company": "ルートゼロ株式会社", "person": "伝刀", "to": "要・宛先確認", "summary": "Azure20年",
        "age": "50代",
        "breakdown": {"必須": 18, "鮮度": 15, "単価": 12, "商流": 9, "タイミング": 7, "見せ方": 3, "継続": 1},
        "skillsheet_summary": "Cisco/F5設計〜運用、脆弱性診断。", "skillsheet_files": ["技術経歴書_A.N.xlsx"],
        "flags": ["年齢上限超・代表確認"],
        "draft": "From: sales@its-tokyo.com\n件名: Re:X_ITS村山\n\nルートゼロ株式会社\n伝刀様\nITS営業部の村山でございます。\n▼案件\n大手遊技機メーカー向けに"}],
        "excluded": [{"item": "M.R", "reason": "両刀足切り"}]}
    blocks = R._notion_blocks_from_result(res)  # token無し＝ファイルアップロードはしない
    allc = " ".join(b[b["type"]]["rich_text"][0]["text"]["content"]
                    for b in blocks if b["type"] != "divider")
    checks = [
        ("スコア/マッチ度を含む", "65/100" in allc and "マッチ内訳" in allc),
        ("年齢を表示", "年齢 50代" in allc),
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


def eval_notiondb():
    """Notion送信ステータスDBの行プロパティ生成（_db_row_props）を検証。決定論・APIキー不要。"""
    import datetime as _dt
    print("── Notion送信ステータスDBの行生成（_db_row_props・決定論）")
    c = {"case": "遊技機 NW/Sec", "engineer": "KH", "score": 93, "likelihood": "高",
         "age": "40歳", "company": "インテレクト", "person": "田中", "to": "tanaka@x.co.jp"}
    p = R._db_row_props(c, _dt.date(2026, 7, 13))
    checks = [
        ("タイトル 案件×要員", p["案件×要員"]["title"][0]["text"]["content"] == "KH × 遊技機 NW/Sec"),
        ("重複キー(rich_text)", p["キー"]["rich_text"][0]["text"]["content"] == R._its_key("遊技機 NW/Sec", "KH")),
        ("スコア(number)", p["スコア"]["number"] == 93),
        ("年齢", p["年齢"]["rich_text"][0]["text"]["content"] == "40歳"),
        ("ステータス既定=未送信", p["ステータス"]["select"]["name"] == "未送信"),
        ("日付", p["日付"]["date"]["start"] == "2026-07-13"),
        # 文字列scoreは _db_row_props では数値化されず 0 に落ちる（数値化は上流 score_with_llm の責務）
        ("文字列scoreは0に落ちる", R._db_row_props({"score": "77"}, _dt.date(2026, 7, 13))["スコア"]["number"] == 0),
        ("int scoreはそのまま", R._db_row_props({"score": 77}, _dt.date(2026, 7, 13))["スコア"]["number"] == 77),
        # likelihood空文字→空select名(400)にならず既定『低』へ（レビュー修正の回帰ガード）
        ("空likelihoodは低に倒れる", R._db_row_props({"likelihood": ""}, _dt.date(2026, 7, 13))["面談通過可能性"]["select"]["name"] == "低"),
    ]
    ok = sum(1 for _, x in checks if x)
    for label, x in checks:
        print(f"   {'✔' if x else '✗'} [{label}]")
    print(f"   DB行生成 正解率： {ok}/{len(checks)} = {ok/len(checks):.2f}")
    return ok == len(checks)


def eval_robustness():
    """コードレビューで見つかった実バグの回帰テスト（H1/H3/L2/L3/M3）。決定論・APIキー不要。"""
    print("── 堅牢性の回帰テスト（レビュー指摘の修正・決定論）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    # H1: score が文字列/欠落混在でも sorted() がクラッシュしない
    try:
        R._notion_blocks_from_result({"candidates": [
            {"case": "A", "engineer": "X", "score": "65", "likelihood": "中"},
            {"case": "B", "engineer": "Y", "likelihood": "高"}]})
        chk("H1 score文字列混在でsorted落ちない", True)
    except Exception:
        chk("H1 score文字列混在でsorted落ちない", False)
    # H3: 本文に別の @reorga.co.jp アドレスが混入したら 🔴
    d = "From: sales@its-tokyo.com\nTo: x@y.co.jp\n件名:X\n\n返信先 dist@reorga.co.jp 村山 its-tokyo.com"
    chk("H3 別reorgaアドレスを検出", any("🔴" in x and "reorga" in x for x in R.validate_draft(d)))
    # L3: Re:/Fwd: の重ね付け除去＋空フォールバック（Fwd/Fw/全角/混在も網羅）
    chk("L3 Re:Re:除去", R._fmt_reply_subject("Re: Re: 【NW】A.N") == "【NW】A.N")
    chk("L3 空件名フォールバック", R._fmt_reply_subject("Re:") == "案件ご紹介")
    chk("L3 Fwd:除去", R._fmt_reply_subject("Fwd: 案件") == "案件")
    chk("L3 Fw:除去", R._fmt_reply_subject("Fw: X") == "X")
    chk("L3 全角ｒｅ：除去", R._fmt_reply_subject("ｒｅ：案件") == "案件")
    chk("L3 全角大文字Ｒｅ：除去", R._fmt_reply_subject("Ｒｅ：案件") == "案件")
    chk("L3 Fwd:+RE:混在除去", R._fmt_reply_subject("Fwd: RE: 案件") == "案件")
    # A1: breakdown が非dict（配列/文字列/数値）でも _fmt_breakdown が落ちない（run全滅の回帰ガード）
    for bad in ([30, 15], "abc", 42):
        chk(f"A1 breakdown非dict({type(bad).__name__})で落ちない", R._fmt_breakdown({"breakdown": bad, "score": 45}) == "（内訳形式不正）")
    # B3: サブドメインの reorga アドレス（@mail.reorga.co.jp）も validate_draft が検出する
    d_sub = "From: sales@its-tokyo.com\nTo: x@corp.jp\n件名:X\n\n返信は a@mail.reorga.co.jp へ 村山 its-tokyo.com"
    chk("B3 サブドメインreorgaを検出", any("REOorGA" in x for x in R.validate_draft(d_sub)))
    print(f"   堅牢性 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_backfill():
    """宛先(To)のデータ層安全化 backfill_contacts を検証（決定論・APIキー不要）。
    LLMが reorga/ロール/複数宛先を to に入れても、抽出器で上書きし Notion/digest に漏らさない二重ガード。"""
    print("── 宛先データ層の安全化（backfill_contacts・決定論）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    kept = [{"from_addr": "dist@reorga.co.jp", "body": "担当 田中 tanaka@intellect.co.jp", "subject": "【NW】A.N"}]
    # 1) LLMが reorga を to に → 抽出器で担当アドレスに上書き（reorgaを残さない）
    res = {"candidates": [{"src": 0, "to": "contact@reorga.co.jp"}]}
    R.backfill_contacts(res, kept)
    c = res["candidates"][0]
    chk("reorga宛を担当アドレスに上書き", c["to"] == "tanaka@intellect.co.jp")
    chk("reorgaが残らない", "reorga" not in c["to"])
    chk("src_subjectを保持", c.get("src_subject") == "【NW】A.N")
    # 2) LLMが妥当な担当アドレス → 保持
    res2 = {"candidates": [{"src": 0, "to": "tanaka@intellect.co.jp"}]}
    R.backfill_contacts(res2, kept)
    chk("妥当アドレスは保持", res2["candidates"][0]["to"] == "tanaka@intellect.co.jp")
    # 3) src範囲外＋reorga cur → 要確認に握り潰す（B4：KeyErrorで落ちない）
    res3 = {"candidates": [{"src": 9, "to": "contact@reorga.co.jp"}]}
    R.backfill_contacts(res3, kept)
    chk("src範囲外+reorgaは要確認に握り潰す", res3["candidates"][0]["to"] == "要・宛先確認")
    # 4) 複数宛先（reorga混入・連結）→ 抽出器で単一の担当へ、reorga残さない（B1）
    res4 = {"candidates": [{"src": 0, "to": "contact@reorga.co.jp, tanaka@intellect.co.jp"}]}
    R.backfill_contacts(res4, kept)
    chk("複数宛先(reorga混入)を安全化", res4["candidates"][0]["to"] == "tanaka@intellect.co.jp" and "reorga" not in res4["candidates"][0]["to"])
    print(f"   宛先安全化 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_score_norm():
    """score_with_llm の応答正規化を**モックLLM**で検証（決定論・APIキー不要）。
    文字列score/欠落/非dict候補/文字列src/非dict breakdown を正規化し、後段sortが落ちないこと（H1/A1/A4）。"""
    print("── LLM応答の正規化（score_with_llm・モックLLM・決定論）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    orig = R._call_llm
    R._call_llm = lambda system, user, json_mode=True: (
        '{"candidates":[{"src":"0","score":"65","breakdown":{"必須":"18","鮮度":15}},'
        '"notadict",{"src":1.0,"score":null,"breakdown":[1,2]},{"score":"x"}],'
        '"excluded":["stringnotdict",{"item":"M.R","reason":"両刀足切り"}],"note":"n"}')
    try:
        kept = [{"from_name": "", "from_addr": "", "subject": "s0", "date": "2026-07-12", "body": "b0"},
                {"from_name": "", "from_addr": "", "subject": "s1", "date": "2026-07-12", "body": "b1"}]
        out = R.score_with_llm(kept, [], BASE_DATE)
        cands = out["candidates"]
        chk("非dict候補を除去", all(isinstance(c, dict) for c in cands) and len(cands) == 3)
        chk("全scoreがint", all(isinstance(c["score"], int) for c in cands))
        chk("文字列score '65'→65", cands[0]["score"] == 65)
        chk("null/非数値score→0", cands[1]["score"] == 0 and cands[2]["score"] == 0)
        chk("文字列src '0'→int0", cands[0]["src"] == 0 and isinstance(cands[0]["src"], int))
        chk("float src 1.0→int1", cands[1]["src"] == 1 and isinstance(cands[1]["src"], int))
        chk("dict breakdown値がint", cands[0]["breakdown"]["必須"] == 18)
        chk("非dict breakdown→{}", cands[1]["breakdown"] == {})
        chk("excludedの非dictを除去", all(isinstance(e, dict) for e in out["excluded"]))
        # 後段のsort/内訳整形が例外を出さない
        try:
            sorted(cands, key=lambda c: c["score"], reverse=True)
            for c in cands:
                R._fmt_breakdown(c)
            chk("後段sort/内訳整形が落ちない", True)
        except Exception:
            chk("後段sort/内訳整形が落ちない", False)
        # 解析失敗（非JSON）→ 例外なしで空候補＋raw
        R._call_llm = lambda system, user, json_mode=True: "garbage no json"
        out2 = R.score_with_llm(kept, [], BASE_DATE)
        chk("非JSON応答でも例外なし・空候補", out2["candidates"] == [] and "raw" in out2)
    finally:
        R._call_llm = orig
    print(f"   応答正規化 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


class _FakeM:
    """_detect_drafts_folder 用の最小 IMAP モック。"""
    def __init__(self, list_data=None, ok_names=()):
        self._list_data = list_data
        self._ok = set(ok_names)
    def list(self):
        if self._list_data is None:
            raise RuntimeError("no list")
        return ("OK", self._list_data)
    def select(self, name, readonly=False):
        return ("OK" if name in self._ok else "NO", [b""])


def eval_folder():
    """_detect_drafts_folder のフォルダ判定を検証（決定論・IMAP不要）。"""
    print("── 下書きフォルダ判定（_detect_drafts_folder・モックIMAP）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    # SPECIAL-USE \Drafts フラグから INBOX.Drafts を検出
    m1 = _FakeM(list_data=[b'(\\HasNoChildren \\Drafts) "/" "INBOX.Drafts"'])
    chk("\\Draftsフラグ→INBOX.Drafts", R._detect_drafts_folder(m1) == "INBOX.Drafts")
    # フラグ無し→定番名 select フォールバック
    m2 = _FakeM(list_data=[b'(\\HasNoChildren) "/" "INBOX"'], ok_names=("Drafts",))
    chk("フラグ無し→Drafts(select成功)", R._detect_drafts_folder(m2) == "Drafts")
    # list例外＋全select失敗→既定 Drafts
    m3 = _FakeM(list_data=None, ok_names=())
    chk("list例外→既定Drafts", R._detect_drafts_folder(m3) == "Drafts")
    print(f"   フォルダ判定 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_reconcile():
    """採点の自己整合化（reconcile_scores / band_from_score）を検証（決定論・APIキー不要）。
    ここが精度の核心：score＝内訳合計・帯をscoreから導出・score<60のジャンク候補を除外へ。"""
    print("── 採点の自己整合化（reconcile_scores・band_from_score）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    # 帯の閾値（scoring.md：高80+／中60-79／除外<60）
    chk("band 80→高", R.band_from_score(80) == "高")
    chk("band 79→中", R.band_from_score(79) == "中")
    chk("band 60→中", R.band_from_score(60) == "中")
    chk("band 59→除外", R.band_from_score(59) == "除外")

    # 内訳合計＝score に確定（『内訳≠score』根絶）。各軸は上限クランプ。
    full = {"必須": 28, "鮮度": 15, "単価": 15, "商流": 15, "タイミング": 10, "見せ方": 7, "継続": 2}
    r = R.reconcile_scores({"candidates": [{"engineer": "A", "case": "X", "score": 0,
                                            "likelihood": "低", "breakdown": dict(full)}]})
    c0 = r["candidates"][0]
    chk("score＝内訳合計(92)に確定", c0["score"] == 92)
    chk("帯を高に上書き（自己申告『低』を無視）", c0["likelihood"] == "高")

    # 軸の上限超えはクランプ（必須40→30・見せ方99→10）してから合算
    over = {"必須": 40, "鮮度": 15, "単価": 15, "商流": 15, "タイミング": 10, "見せ方": 99, "継続": 5}
    r = R.reconcile_scores({"candidates": [{"engineer": "B", "case": "X", "score": 200, "breakdown": over}]})
    chk("軸上限クランプ後の合計(100)", r["candidates"][0]["score"] == 30 + 15 + 15 + 15 + 10 + 10 + 5)

    # score<60 のジャンク候補は candidates から除外へ移動（下書き漏れ根絶）
    low = {"必須": 10, "鮮度": 15, "単価": 10, "商流": 8, "タイミング": 5, "見せ方": 2, "継続": 0}  # =50
    res = R.reconcile_scores({"candidates": [
        {"engineer": "C", "case": "X", "score": 88, "likelihood": "高",
         "breakdown": {"必須": 28, "鮮度": 15, "単価": 15, "商流": 12, "タイミング": 10, "見せ方": 6, "継続": 2}},
        {"engineer": "D", "case": "X", "score": 0, "likelihood": "低", "breakdown": dict(low)}],
        "excluded": []})
    chk("候補は高得点1件のみ残る", [c["engineer"] for c in res["candidates"]] == ["C"])
    chk("score<60は excluded へ移動", any("D ×" in e.get("item", "") for e in res["excluded"]))

    # 属性フラグ（代表確認）付きでも score<60 は除外（貴重な両刀は高得点で残る＝別ケース）
    res = R.reconcile_scores({"candidates": [
        {"engineer": "E", "case": "X", "score": 0, "flags": ["年齢上限超・代表確認"],
         "breakdown": {"必須": 12, "鮮度": 15, "単価": 10, "商流": 8, "タイミング": 5, "見せ方": 2, "継続": 0}}],
        "excluded": []})
    chk("flag付きでもscore<60は除外へ", res["candidates"] == []
        and any("代表確認フラグ有" in e.get("reason", "") for e in res["excluded"]))

    # breakdownが不完全（7軸揃わない）なら既存scoreをクランプして帯判定（落とさない）
    res = R.reconcile_scores({"candidates": [{"engineer": "F", "case": "X", "score": 150, "breakdown": {"必須": 30}}]})
    chk("不完全breakdownはscoreクランプ(100)で残す", res["candidates"] and res["candidates"][0]["score"] == 100)

    print(f"   自己整合化 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_watermark():
    """イベント駆動の新着フィルタ（filter_new_by_uid / max_uid）を検証（決定論・IMAP不要）。
    ここが壊れると、ポーリングで①新着を取りこぼす or ②既処理を再採点してコスト暴発、が起きる。"""
    print("── UIDウォーターマーク新着フィルタ（filter_new_by_uid・max_uid）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    def it(uid):
        return {"uid": uid, "body": "x"}

    items = [it("90"), it("100"), it("101"), it("150")]
    # watermark=100 → 100含む以前は除外、101/150だけ新着（厳密に大きいもの）
    new = R.filter_new_by_uid(items, 100)
    chk("watermark=100→新着は101,150", [i["uid"] for i in new] == ["101", "150"])
    # watermark=None（初回）→全件
    chk("watermark=None→全件", len(R.filter_new_by_uid(items, None)) == 4)
    # 最新以上のwatermark→新着ゼロ（＝新着なし→採点スキップ→コスト0の経路）
    chk("watermark=150→新着ゼロ", R.filter_new_by_uid(items, 150) == [])
    # UID欠落は取りこぼし回避で新着側に含める（下流dedupが重複下書きを防ぐ）
    chk("UID欠落は新着側に含める", len(R.filter_new_by_uid([it(None), it("50")], 100)) == 1
        and R.filter_new_by_uid([it(None), it("50")], 100)[0]["uid"] is None)
    # max_uid：数値のみ・非数値/None無視
    chk("max_uid=最大の数値", R.max_uid([it("5"), it("42"), it("7")]) == 42)
    chk("max_uid：非数値/Noneを無視", R.max_uid([it(None), it("abc"), it("9")]) == 9)
    chk("max_uid：数値ゼロ件→None", R.max_uid([it(None), it("abc")]) is None)
    print(f"   新着フィルタ 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage",
                    choices=["prefilter", "draft", "finalize", "drafts", "notion", "contact",
                             "dedup", "robustness", "notiondb", "backfill", "score_norm", "folder",
                             "watermark", "reconcile", "scoring", "all"],
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
    if args.stage in ("robustness", "all"):
        results.append(eval_robustness())
    if args.stage in ("notiondb", "all"):
        results.append(eval_notiondb())
    if args.stage in ("backfill", "all"):
        results.append(eval_backfill())
    if args.stage in ("score_norm", "all"):
        results.append(eval_score_norm())
    if args.stage in ("folder", "all"):
        results.append(eval_folder())
    if args.stage in ("watermark", "all"):
        results.append(eval_watermark())
    if args.stage in ("reconcile", "all"):
        results.append(eval_reconcile())
    if args.stage in ("scoring", "all"):
        results.append(eval_scoring())
    # 決定論部分に失敗があれば非0で返す（CI/反復で退行検知）
    hard_fail = any(r is False for r in results)
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
