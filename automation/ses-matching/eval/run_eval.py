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

# eval のフィクスチャは「サーバ×NW軸・鮮度5日・本命85点」を前提に作られている。
# active-case.json（＝その時アクティブな案件）の軸/鮮度/しきい値に依存せず、エンジンのロジックを
# 安定して回帰検証するため、決定論evalの間は参照値を固定する（intakeで別軸/別しきい値の案件が
# 来ても退行検知が誤検知しない）。年齢ゲートは各ステージが個別に制御する。
R.PREFILTER_GROUPS = R.AXIS_PRESETS["サーバ×NW"]
R.FRESH_DAYS = 5
R.PICKUP_MIN = 85

BASE_DATE = datetime.date(2026, 7, 12)  # fixtures の基準日（決定論のため固定）

# 下書き系テスト（finalize/drafts）が使う案件本文の**固定フィクスチャ**。
# ※アクティブ案件（案件_*.md）は営業状況で入替・アーカイブされるため、eval はそれに依存せず
#   このフィクスチャを load_case_mail_block に注入して回す（＝案件が無い/変わっても決定論で緑）。
TEST_CASE_MAILBLOCK = (
    "大手遊技機メーカー向けに、ネットワーク／セキュリティ領域をご担当いただける技術者を募集しております。\n"
    "■案件概要 … 設計・構築・運用フェーズ。\n"
    "＝＝＝＝＝＝＝＝＝＝＝＝＝＝"
)


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
    # src→候補 の対応表（kept は元 items の部分集合）。帯は 代表確認フラグのみ "flag" 扱い
    # （新設の「両刀根拠の明示要確認」フラグを "flag" 帯と誤認しないため _is_daihyo_flag を使う）。
    band_by_body, pickup_by_body = {}, {}
    for c in result.get("candidates", []):
        src = c.get("src")
        if isinstance(src, int) and 0 <= src < len(kept):
            band = "flag" if R._is_daihyo_flag(c) else c.get("likelihood", "低")
            band_by_body[kept[src]["body"]] = band
            pickup_by_body[kept[src]["body"]] = R.is_pickup(c)
    dropped_bodies = {d["body"] for d in dropped}
    ok = pok = 0
    for row in rows:
        body = row["body"]
        want = row["expect_band"]
        if body in dropped_bodies:
            got = "除外"
        else:
            got = band_by_body.get(body, "除外")  # 候補に出なければ実質除外
        hit = (got == want) or (want == "除外" and got == "除外")
        ok += 1 if hit else 0
        # 本命（85+・両刀根拠）判定の一致も計測（面談依頼が来る母集団の精度）
        want_p = bool(row.get("expect_pickup", False))
        got_p = bool(pickup_by_body.get(body, False))
        phit = want_p == got_p
        pok += 1 if phit else 0
        mark = "✔" if hit else "✗"
        pmark = "✔" if phit else "✗"
        print(f"   帯{mark} 本命{pmark} [{row['id']}] 帯:期待={want}/実際={got}"
              f"　本命:期待={want_p}/実際={got_p}  {row['note']}")
    print(f"── 段階② LLM採点 帯一致率： {ok}/{len(rows)} = {ok/len(rows):.2f}（計測・非ゲート）")
    print(f"── 段階② 本命(85+)一致率： {pok}/{len(rows)} = {pok/len(rows):.2f}（計測・非ゲート）")
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
    _orig_block = R.load_case_mail_block
    R.load_case_mail_block = lambda case_hint="": TEST_CASE_MAILBLOCK  # 案件のアーカイブ状態に依存せず回す
    try:
        d = R.finalize_draft(cand)
        d2 = R.finalize_draft({"case": "遊技機メーカー NW/Sec 支援", "engineer": "K.H"})
    finally:
        R.load_case_mail_block = _orig_block
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
    # 未知の会社/担当はプレースホルダに倒れること（d2 は上の try 内で生成済み）
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

    _orig_block = R.load_case_mail_block
    R.load_case_mail_block = lambda case_hint="": TEST_CASE_MAILBLOCK  # 案件のアーカイブ状態に依存せず回す
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
    R.load_case_mail_block = _orig_block
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


def eval_pickup():
    """本命ピックアップ判定（is_pickup / _text_has_two_sided / reconcile の pickup 付与）を検証。
    ここが今回の精度強化の核心：**score>=85 かつ 両刀根拠が文面で裏取れる**時だけ本命（自動下書き・トラッカー対象）。
    決定論・APIキー不要。"""
    print("── 本命ピックアップ判定（is_pickup・両刀根拠ゲート・決定論）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    two_sided = "Windows Server/ADとCisco/F5多拠点NWをサーバ×NW両面で設計運用、情シスでPL"  # サーバ語×NW語あり
    nw_only = "Cisco/F5・ルーティング・スイッチング・多拠点NWの設計構築に長ける"      # NW語のみ（サーバ語なし）
    # 閾値：85でON・84でOFF（85+が本命の下限）
    chk("score85＋両刀根拠→本命", R.is_pickup({"score": 85, "reason": two_sided}) is True)
    chk("score84→本命でない（閾値未満）", R.is_pickup({"score": 84, "reason": two_sided}) is False)
    chk("score92＋両刀根拠→本命", R.is_pickup({"score": 92, "reason": two_sided}) is True)
    # 二重ガード：高得点でも根拠が片刀寄りなら本命に載せない
    chk("score90だが片刀根拠→本命でない", R.is_pickup({"score": 90, "reason": nw_only}) is False)
    chk("summary側に両刀語があれば拾う", R.is_pickup({"score": 88, "reason": "強い", "summary": two_sided}) is True)
    chk("85+でも代表確認フラグは本命でない",
        R.is_pickup({"score": 90, "reason": two_sided, "flags": ["年齢上限超・代表確認"]}) is False)
    chk("既提案・重複フラグは本命判定に影響しない",
        R.is_pickup({"score": 90, "reason": two_sided, "flags": ["既提案・重複"]}) is True)
    chk("非dict/非数値scoreでも落ちない", R.is_pickup("x") is False and R.is_pickup({"score": "88"}) is False)
    # _text_has_two_sided 単体
    chk("両刀テキスト→True", R._text_has_two_sided(two_sided) is True)
    chk("NWのみ→False", R._text_has_two_sided(nw_only) is False)
    chk("サーバのみ→False", R._text_has_two_sided("Windows Server/AD/VMware専任で仮想基盤を構築") is False)

    # reconcile_scores が pickup を付与し、85+×片刀根拠には保留フラグを立てる
    # age は年齢ゲートと独立に pickup を見るため ≤上限 の確定値（30歳）を付す（年齢ゲートは eval_agegate で別途検証）
    res = R.reconcile_scores({"candidates": [
        {"engineer": "A", "case": "X", "reason": two_sided, "age": "30歳",   # 92・両刀 → 本命
         "breakdown": {"必須": 28, "鮮度": 15, "単価": 15, "商流": 15, "タイミング": 10, "見せ方": 7, "継続": 2}},
        {"engineer": "B", "case": "X", "reason": nw_only, "age": "30歳",      # 90だが片刀 → 本命でない＋保留フラグ
         "breakdown": {"必須": 30, "鮮度": 15, "単価": 15, "商流": 15, "タイミング": 10, "見せ方": 5, "継続": 0}},
        {"engineer": "C", "case": "X", "reason": two_sided, "age": "30歳",    # 70 → 中・参考（本命でない）
         "breakdown": {"必須": 22, "鮮度": 13, "単価": 12, "商流": 8, "タイミング": 10, "見せ方": 4, "継続": 1}}],
        "excluded": []})
    cA, cB, cC = res["candidates"]
    chk("A(92両刀)=pickup", cA.get("pickup") is True)
    chk("B(90片刀)=pickup無し", cB.get("pickup") is False)
    chk("B に保留フラグ", any("自動下書き保留" in f for f in cB.get("flags", [])))
    chk("C(70)=pickup無し", cC.get("pickup") is False)

    # render_digest：本命は◎章＋返信下書きあり、参考は○章＋自動下書きなし注記
    dig = R.render_digest(res, __import__("datetime").date(2026, 7, 12), [1, 2, 3], [])
    chk("digestに◎本命章", "◎ 本命" in dig)
    chk("digestに○参考章", "○ 参考" in dig)
    chk("参考に自動下書きなし注記", "自動下書きは作成していません" in dig)

    # Notion簡潔ブロック：本命/参考を見出しで分ける
    blocks = R._notion_blocks_from_result(res)
    allc = " ".join(b[b["type"]]["rich_text"][0]["text"]["content"]
                    for b in blocks if b["type"] != "divider")
    chk("Notionに本命/参考の見出し", "◎ 本命" in allc and "○ 参考" in allc)
    chk("本命は下書き保存済み・参考は自動下書きなし", "下書きフォルダに保存済み" in allc and "自動下書きなし" in allc)
    print(f"   本命ピックアップ判定 正解率： {ok}/{tot} = {ok/tot:.2f}")
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


def eval_agegate():
    """年齢ハード上限ゲート（AGE_HARD_LIMIT=35）を検証：36歳以上は除外、跨ぐ/不明は本命保留。決定論・APIキー不要。"""
    print("── 年齢ハード上限ゲート（reconcile_scores・AGE_HARD_LIMIT=35・決定論）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    def cand(eng, age, score=95):
        return {"case": "C", "engineer": eng, "age": age, "score": score,
                "breakdown": {"必須": 30, "鮮度": 15, "単価": 15, "商流": 15, "タイミング": 10, "見せ方": 10, "継続": 5},
                "reason": "サーバWindows Server/AD と ネットワークCisco/多拠点 の両刀・情シス・PL進捗管理", "summary": "両刀"}

    saved = R.AGE_HARD_LIMIT
    R.AGE_HARD_LIMIT = 35
    try:
        res = {"candidates": [cand("A", "28歳"), cand("B", "36歳"), cand("C", "40代"), cand("D", "50代"),
                              cand("E", "30代"), cand("F", "不明"), cand("G", "35歳")]}
        R.reconcile_scores(res)
        engs = {c["engineer"] for c in res["candidates"]}
        excl = " ".join(e.get("item", "") for e in res.get("excluded", []))
        by = {c["engineer"]: c for c in res["candidates"]}
        chk("28歳は残る", "A" in engs)
        chk("35歳(境界)は残る", "G" in engs)
        chk("36歳は除外", "B" not in engs and "B ×" in excl)
        chk("40代は除外", "C" not in engs and "C ×" in excl)
        chk("50代は除外", "D" not in engs and "D ×" in excl)
        chk("30代(跨ぐ)は残るが本命保留", "E" in engs and by.get("E", {}).get("pickup") is False)
        chk("不明は残るが本命保留", "F" in engs and by.get("F", {}).get("pickup") is False)
        chk("30代/不明に年齢要確認フラグ", all("年齢要確認" in " ".join(by[e].get("flags", [])) for e in ("E", "F")))
        chk("28歳/35歳は本命(pickup)可", by.get("A", {}).get("pickup") is True and by.get("G", {}).get("pickup") is True)
        # ゲート無効（None）時は従来どおり除外しない（一般ガードレール維持）
        R.AGE_HARD_LIMIT = None
        res2 = {"candidates": [cand("H", "50代")]}
        R.reconcile_scores(res2)
        chk("AGE_HARD_LIMIT無効時は50代も残る", any(c["engineer"] == "H" for c in res2["candidates"]))
    finally:
        R.AGE_HARD_LIMIT = saved
    print(f"   年齢ゲート 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_intake():
    """新案件受付（intake_case）の決定論生成を検証：フォーム解析・年齢行除去・単価正規化・軸プリセット・
    active-case.json の値。ここが壊れると『Issue貼るだけ』の自動設定が誤る。決定論・APIキー不要。"""
    import intake_case as IC
    print("── 新案件受付 intake（フォーム→設定・決定論）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    body = (
        "### 案件名（短い識別名）\n\nテスト案件\n\n"
        "### 案件JD（全文貼り付け）\n\n■必須\n・サーバとNW両方\n・35歳まで\n■単価\n・80〜90万円前後\n\n"
        "### 両刀の軸\n\nNW×セキュリティ（ネットワーク と セキュリティ）\n\n"
        "### 年齢方針\n\n35歳・ハード除外（36歳以上は選定しない）\n\n"
        "### クライアント支払単価\n\n100〜120万\n\n"
        "### 要員希望単価（優先したいレンジ）\n\n80〜90万\n\n"
        "### 鮮度（配信何日以内を対象にするか）\n\n7\n\n"
        "### 本命しきい値（点）\n\n80\n")
    active, case_md, case_id = IC.run(body, "2026-07-29")
    chk("軸→NW×セキュリティ", active["axis"] == "NW×セキュリティ")
    chk("年齢ハード上限=35", active["age_hard_limit"] == 35)
    chk("鮮度=7", active["fresh_days"] == 7)
    chk("本命しきい値=80", active["pickup_min"] == 80)
    chk("クライアント単価を保持", active["client_rate"] == "100〜120万")
    chk("案件ID=日付+slug", case_id == "20260729_テスト案件")
    # MAIL-BLOCK：年齢行が除去され、単価は要員向けに正規化される
    mb = case_md.split("MAIL-BLOCK-START -->")[1]
    chk("MAIL-BLOCKに年齢が出ない", "35歳" not in mb and "年齢" not in mb)
    chk("MAIL-BLOCKの単価は要員向け", "80〜90万" in mb and "100〜120万" not in mb)
    # フラグのみ→age_hard_limit None
    body2 = body.replace("35歳・ハード除外（36歳以上は選定しない）", "フラグのみ（除外しない・代表確認）")
    active2, _, _ = IC.run(body2, "2026-07-29")
    chk("フラグのみ→age_hard_limit=None", active2["age_hard_limit"] is None)
    # 軸プリセットが engine と一致（NW×セキュリティはセキュリティ語を含む）
    groups = R.AXIS_PRESETS.get(active["axis"])
    chk("軸プリセットにセキュリティ語(edr)", any("edr" in g for g in groups[1]))
    print(f"   新案件受付 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_matchcore():
    """案件×人材の決定論マッチ（match_core.score_match・両刀/年齢/粗利ガード）を検証。
    「投入→自動マッチング」の心臓部。決定論・APIキー不要。active-case.json に非依存（軸は明示引数）。"""
    import match_core as MC
    print("── 案件×人材 決定論マッチ（match_core・両刀/年齢/粗利）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    # 単価パース
    chk("希望単価レンジ→下限(80)", MC.parse_rate_man("80〜90万") == 80)
    chk("円表記→万(85)", MC.parse_rate_man("850000") == 85)
    chk("クライアント上限(120)", MC.client_rate_max_man("100〜120万") == 120)
    # 非単価の数値（時間・％・人数）を単価と誤読しない（'160h/月 90万'の160を拾わない）
    chk("時間混入→90万のみ", MC.client_rate_max_man("160h/月 90万") == 90 and MC.parse_rate_man("160h/月 90万") == 90)
    chk("全角時間混入→90万のみ", MC.client_rate_max_man("月160時間 90万") == 90)
    chk("読めない単価→None", MC.parse_rate_man("応相談") is None and MC.client_rate_max_man("") is None)

    case = {"axis": "サーバ×NW", "age_hard_limit": 35, "client_rate": "100〜120万",
            "engineer_rate_pref": "80〜90万", "pickup_min": 85}
    good = {"name": "T.K", "age": "32歳", "rate": "85万", "availability": "即日",
            "skills": "Linux/RHEL/VMware でサーバ構築、Cisco L2/L3 でネットワーク設計。情シス常駐。"}
    m = MC.score_match(case, good)
    chk("両刀成立→axis_ok", m["axis_ok"] is True)
    chk("年齢32→ok", m["age"] == "ok")
    chk("粗利ok(35万)", m["rate"]["verdict"] == "ok" and m["rate"]["margin"] == 35)
    chk("本命判定(pickup)", m["pickup"] is True and m["verdict"] == "本命")
    chk("スコア>=85", m["score"] >= 85)

    server_only = {"name": "S.O", "age": "30歳", "rate": "80万", "availability": "即日",
                   "skills": "Windows Server/AD/VMware 仮想基盤専任。サーバ運用のみ。"}
    m2 = MC.score_match(case, server_only)
    chk("片刀→axis_ok False", m2["axis_ok"] is False)
    chk("片刀→本命でない＋片刀フラグ", m2["pickup"] is False and any("片刀" in f for f in m2["flags"]))

    old = {"name": "R.T", "age": "38歳", "rate": "85万", "availability": "即日", "skills": good["skills"]}
    m3 = MC.score_match(case, old)
    chk("38歳→除外・本命不可", m3["verdict"] == "除外" and m3["pickup"] is False)
    chk("38歳→年齢ハード超フラグ", any("年齢ハード超" in f for f in m3["flags"]))

    uncertain = {"name": "U.N", "age": "30代", "rate": "85万", "availability": "即日", "skills": good["skills"]}
    m4 = MC.score_match(case, uncertain)
    chk("30代(跨ぐ)→年齢要確認・本命保留", m4["pickup"] is False and any("年齢要確認" in f for f in m4["flags"]))

    neg = {"name": "H.R", "age": "30歳", "rate": "130万", "availability": "即日", "skills": good["skills"]}
    m5 = MC.score_match(case, neg)
    chk("希望>上限→粗利不足フラグ・本命不可", m5["pickup"] is False and any("粗利不足" in f for f in m5["flags"]))

    ranked = MC.match_talent_to_cases(good, [case])
    chk("突き合わせ先頭が本命", ranked and ranked[0]["match"]["verdict"] == "本命")

    # 上限無効(None)なら年齢で除外しない（一般ガードレール維持）
    case_noage = dict(case); case_noage["age_hard_limit"] = None
    chk("上限None→38歳も除外しない", MC.score_match(case_noage, old)["verdict"] != "除外")
    print(f"   決定論マッチ 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def eval_talent_intake():
    """人材受付（intake_talent）の決定論生成を検証：フォーム解析・年齢除去・案件マッチ・提案下書き。
    「人材を投入→自動マッチ→下書き」の対称フロー。決定論・APIキー不要。"""
    import intake_talent as IT
    import match_core as MC
    print("── 人材受付 intake_talent（フォーム→台帳→マッチ→下書き・決定論）")
    ok = tot = 0

    def chk(label, cond):
        nonlocal ok, tot
        tot += 1; ok += 1 if cond else 0
        print(f"   {'✔' if cond else '✗'} [{label}]")

    body = (
        "### 識別名（イニシャル）\n\nT.K\n\n"
        "### スキルシート（本文貼り付け）\n\n35歳 / インフラ8年\n"
        "Linux(RHEL)/VMware でサーバ、Cisco L2・L3 でネットワーク。情シス常駐。\n希望85万 即日\n\n"
        "### 両刀の軸ヒント\n\nサーバ×NW\n\n"
        "### 年齢\n\n32歳\n\n"
        "### 希望単価\n\n85万\n\n"
        "### 稼働時期\n\n即日\n\n"
        "### 所属BP/配信元\n\nサンプルBP\n")
    talent = IT.build_talent(IT.parse_issue_form(body), "2026-08-06")
    chk("氏名=T.K", talent["name"] == "T.K")
    chk("年齢=32歳", talent["age"] == "32歳")
    chk("希望単価=85万", talent["rate"] == "85万")
    chk("稼働=即日", talent["availability"] == "即日")
    chk("人材ID=日付+slug", talent["talent_id"] == "20260806_T.K")
    chk("サマリーに年齢(歳)が出ない", "歳" not in talent["summary"])

    case = {"case_id": "C1", "case_title": "遊技機 情シスPL", "axis": "サーバ×NW", "age_hard_limit": 35,
            "client_rate": "100〜120万", "engineer_rate_pref": "80〜90万", "pickup_min": 85, "skills": ""}
    matches = MC.match_talent_to_cases(talent, [case])
    chk("投入人材が案件に本命マッチ", matches[0]["match"]["verdict"] == "本命")

    draft = IT.build_proposal_draft(talent, matches[0])
    chk("下書きFrom=sales@", "From: sales@its-tokyo.com" in draft)
    chk("下書きに案件名", "遊技機 情シスPL" in draft)
    chk("下書きに年齢を出さない", "歳" not in draft)
    chk("下書きにREOorGA不在", "reorga" not in draft.lower())
    chk("提案単価は要員向け(80〜90万)", "80〜90万" in draft and "100〜120万" not in draft)

    # プロフィールMD：客先貼付サマリーに年齢が出ない
    profile = IT.build_profile_md(talent, matches, "2026-08-06")
    mb = profile.split("MAIL-BLOCK-START -->")[1]
    chk("プロフィールMAIL-BLOCKに年齢が出ない", "歳" not in mb)
    print(f"   人材受付 正解率： {ok}/{tot} = {ok/tot:.2f}")
    return ok == tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage",
                    choices=["prefilter", "draft", "finalize", "drafts", "notion", "contact",
                             "dedup", "robustness", "notiondb", "backfill", "score_norm", "folder",
                             "watermark", "reconcile", "pickup", "agegate", "intake",
                             "matchcore", "talent_intake", "scoring", "all"],
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
    if args.stage in ("pickup", "all"):
        results.append(eval_pickup())
    if args.stage in ("agegate", "all"):
        results.append(eval_agegate())
    if args.stage in ("intake", "all"):
        results.append(eval_intake())
    if args.stage in ("matchcore", "all"):
        results.append(eval_matchcore())
    if args.stage in ("talent_intake", "all"):
        results.append(eval_talent_intake())
    if args.stage in ("scoring", "all"):
        results.append(eval_scoring())
    # 決定論部分に失敗があれば非0で返す（CI/反復で退行検知）
    hard_fail = any(r is False for r in results)
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
