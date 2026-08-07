#!/usr/bin/env python3
"""案件×人材の**決定論**マッチング中核（投入フローの「自動マッチング」の心臓）。

「案件を投入」「人材を投入」の両方が、台帳（data/cases.json・data/talents.json）に対して
このモジュールで突き合わせる。LLM不使用＝ブレなし・APIキー不要・CIで回帰検証できる。
本番の live 採点（LLMで面談通過可能性を測る）は run_ses_matching / run_ses_crossmatch が担い、
ここは「投入した瞬間に、台帳のどれと噛み合うか」を決定論で即答する層。

再利用（重複を作らない）：両刀語彙・語境界一致・年齢パースは run_ses_matching から import する。
ガードレール（両刀の軸ヒット必須／年齢ハード上限／粗利死守）はスコアと verdict に反映する。
"""
import json
import os
import re

import run_ses_matching as R  # 語彙・_kw_hit・_parse_age・_age_* を再利用（重複定義しない）

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

MARGIN_MIN_MAN = 8   # 粗利死守ライン（万）。client支払上限 − 要員希望 がこれ未満は「薄い/不足」
MATCH_MIN = 70       # 「提案可」の下限（本命=pickup は各案件の pickup_min／既定85）
PICKUP_MIN_DEFAULT = 85


# ---------- 単価パース ----------
# 単価文字列に紛れる「非単価の数値」（時間・％・人数・拠点数等）を除去してから金額を読む。
# 例 '160h/月 90万'・'月160時間 90万' の 160 を単価と誤読しないため。
_NONRATE_UNIT = re.compile(r"\d+\s*(?:h|ｈ|時間|時|％|%|名|人|日|拠点|台|件|ヶ月|か月|箇月)", re.IGNORECASE)


def _rate_numbers(s):
    """単価文字列 → 万単位の数値リスト（円表記 4桁以上は万換算）。非単価の数値は除去。"""
    s = str(s or "").replace(",", "")
    s = _NONRATE_UNIT.sub(" ", s)                       # 時間/％/人数等を落とす（誤読防止）
    nums = [int(x) for x in re.findall(r"\d+", s)]
    return [round(n / 10000) if n >= 1000 else n for n in nums]   # 円(≥1000)→万


def parse_rate_man(s):
    """要員希望単価 '85万'/'80〜90万'/'850000' → 万単位の代表値（レンジは下限＝要員が受ける最低）。
    読めなければ None。時間/％等の非単価数値は無視する。"""
    nums = _rate_numbers(s)
    return min(nums) if nums else None


def client_rate_max_man(s):
    """クライアント支払 '100〜120万' → 上限120（粗利計算の上側）。読めなければ None。"""
    nums = _rate_numbers(s)
    return max(nums) if nums else None


# ---------- 軸（両刀）・年齢・単価 判定 ----------
def _axis_groups(axis_key):
    return [g for g in R.AXIS_PRESETS.get(axis_key or "サーバ×NW", []) if g]


def axis_group_hits(text, axis_key):
    """各群にヒットしたか（両刀なら [server_hit, nw_hit]）。"""
    low = (text or "").lower()
    return [any(R._kw_hit(k, low) for k in g) for g in _axis_groups(axis_key)]


def both_axes_ok(text, axis_key):
    """両刀の軸が全群ヒット（＝両刀成立）。群が無い『指定なし』は常にTrue。"""
    hits = axis_group_hits(text, axis_key)
    return all(hits) if hits else True


def keyword_hit_count(text, axis_key):
    low = (text or "").lower()
    return sum(1 for g in _axis_groups(axis_key) for k in g if R._kw_hit(k, low))


def age_verdict(age, limit):
    """'ok'（上限以下確定）｜'excluded'（上限超確定＝ハード除外）｜'uncertain'（跨ぐ/不明＝保留）。
    limit=None なら常に 'ok'（属性の自動除外はしない一般ガードレール）。"""
    if limit is None:
        return "ok"
    if R._age_over_limit({"age": age}, limit):
        return "excluded"
    if R._age_uncertain({"age": age}, limit):
        return "uncertain"
    return "ok"


def rate_verdict(eng_rate, client_rate):
    """(判定, 粗利万)。'ok'（粗利>=8）｜'thin'（0<=粗利<8）｜'negative'（粗利<0）｜'unknown'（読めず）。"""
    eng = parse_rate_man(eng_rate)
    cmax = client_rate_max_man(client_rate)
    if eng is None or cmax is None:
        return ("unknown", None)
    margin = cmax - eng
    if margin >= MARGIN_MIN_MAN:
        return ("ok", margin)
    if margin >= 0:
        return ("thin", margin)
    return ("negative", margin)


# ---------- スコアリング（決定論 0-100）----------
def score_match(case, talent):
    """案件(dict)×人材(dict) を決定論採点。
    返り値：score / breakdown / axis_ok / age / rate / pickup / verdict / flags / reason。
    ガードレール：両刀不成立は上限を割る／年齢ハード超は verdict='除外'・pickup不可／粗利不足はflag。"""
    axis = case.get("axis") or "サーバ×NW"
    text = " ".join(str(talent.get(k, "")) for k in ("skills", "summary", "title", "name"))
    hits = axis_group_hits(text, axis)
    ngroups = len(_axis_groups(axis))
    nhit = sum(1 for h in hits if h)
    axis_ok = (nhit == ngroups) if ngroups else True
    axis_ratio = (nhit / ngroups) if ngroups else 1.0
    axis_score = round(50 * axis_ratio)                  # 両刀成立=50・片刀=25（両刀×NWの場合）

    depth = min(20, keyword_hit_count(text, axis) * 3)   # スキル深度（ヒット語数）最大20

    av = age_verdict(talent.get("age"), case.get("age_hard_limit"))
    rv, margin = rate_verdict(talent.get("rate"), case.get("client_rate"))
    rate_score = {"ok": 20, "thin": 10, "negative": 0, "unknown": 8}[rv]

    avail = str(talent.get("availability", ""))
    avail_score = 10 if ("即" in avail) else (6 if avail.strip() else 4)

    score = axis_score + depth + rate_score + avail_score  # 上限100（50+20+20+10）

    flags, reasons = [], []
    if ngroups and not axis_ok:
        flags.append("片刀（両刀不成立）")
        reasons.append(f"軸{axis}の{ngroups}群中{nhit}群のみヒット")
    else:
        reasons.append(f"両刀（{axis}）成立")
    if av == "excluded":
        flags.append(f"年齢ハード超（上限{case.get('age_hard_limit')}歳）")
    elif av == "uncertain":
        flags.append("年齢要確認")
    if rv == "negative":
        flags.append("粗利不足（要員希望>クライアント上限）")
    elif rv == "thin":
        flags.append(f"粗利薄（+{margin}万<{MARGIN_MIN_MAN}万）")
    if rv == "ok":
        reasons.append(f"粗利+{margin}万")

    pickup_min = case.get("pickup_min") or PICKUP_MIN_DEFAULT
    pickup = bool(axis_ok and av == "ok" and rv in ("ok", "thin") and score >= pickup_min)

    if av == "excluded":
        verdict = "除外"
        pickup = False
    elif pickup:
        verdict = "本命"
    elif axis_ok and av != "excluded" and rv != "negative" and score >= MATCH_MIN:
        verdict = "提案可"
    else:
        verdict = "参考"

    return {
        "score": int(score),
        "breakdown": {"両刀": axis_score, "スキル深度": depth, "単価": rate_score, "稼働": avail_score},
        "axis_ok": axis_ok,
        "age": av,
        "rate": {"verdict": rv, "margin": margin},
        "pickup": pickup,
        "verdict": verdict,
        "flags": flags,
        "reason": "／".join(reasons),
    }


# ---------- 台帳（ledger）読み書き ----------
def _read_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, list) else default
    except Exception:  # noqa  壊れた台帳で本体を止めない
        pass
    return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_cases():
    """data/cases.json（案件台帳）。空/無ければ active-case.json から1件合成（＝常に現行案件と噛む）。"""
    cases = _read_json(os.path.join(DATA_DIR, "cases.json"), [])
    if cases:
        return cases
    ac = R.ACTIVE_CASE or {}
    if ac.get("case_id"):
        return [{
            "case_id": ac.get("case_id"),
            "case_title": ac.get("case_title") or ac.get("case_id"),
            "axis": ac.get("axis"),
            "age_hard_limit": ac.get("age_hard_limit"),
            "client_rate": ac.get("client_rate"),
            "engineer_rate_pref": ac.get("engineer_rate_pref"),
            "pickup_min": ac.get("pickup_min"),
            "status": "active",
            "skills": "",
        }]
    return []


def load_talents():
    return _read_json(os.path.join(DATA_DIR, "talents.json"), [])


def upsert(records, rec, key):
    """key（case_id / talent_id）で upsert。既存は更新、無ければ追記。新しいlistを返す。"""
    kid = rec.get(key)
    out, replaced = [], False
    for r in records:
        if kid and r.get(key) == kid:
            out.append(rec)
            replaced = True
        else:
            out.append(r)
    if not replaced:
        out.append(rec)
    return out


def save_cases(cases):
    _write_json(os.path.join(DATA_DIR, "cases.json"), cases)


def save_talents(talents):
    _write_json(os.path.join(DATA_DIR, "talents.json"), talents)


# ---------- 突き合わせ（片側→反対側の台帳）----------
def _rank_key(m):
    # 本命→提案可→参考→除外 の順、同帯内はスコア降順
    order = {"本命": 0, "提案可": 1, "参考": 2, "除外": 3}
    return (order.get(m["match"]["verdict"], 9), -m["match"]["score"])


def match_talent_to_cases(talent, cases):
    """投入した人材 × 案件台帳。各案件のスコア付きリスト（本命→…→除外の順）。"""
    out = [{"case": c, "match": score_match(c, talent)} for c in cases]
    return sorted(out, key=_rank_key)


def match_case_to_talents(case, talents):
    """投入した案件 × 人材台帳。各人材のスコア付きリスト（本命→…→除外の順）。"""
    out = [{"talent": t, "match": score_match(case, t)} for t in talents]
    return sorted(out, key=_rank_key)
