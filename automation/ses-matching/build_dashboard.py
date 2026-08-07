#!/usr/bin/env python3
"""台帳（cases.json / talents.json）＋現行案件から、**実データの運用ダッシュボード**（自己完結HTML）を生成する。

モック（ダミー）ではなく、その時点の台帳を正としてレンダリングする「システムの運用画面」。
- 「案件を投入」「人材を投入」ボタンは、実際の GitHub Issue フォームへの**本物の直リンク**。
- 本命/候補は match_core の**決定論マッチ**（両刀・年齢ハード上限・粗利）で算出＝ブレなし・APIキー不要。
- 金額・件数・平均スコアは台帳の実値のみ（根拠のない数値は出さない）。

使い方:
  python build_dashboard.py                 # dashboard.html を生成
  python build_dashboard.py --out /path.html
  python build_dashboard.py --stamp 2026-08-07T07:00  # 生成時刻を明示（省略時は空欄表記）
"""
import argparse
import html
import json
import os
import re
import subprocess

import match_core as MC
import run_ses_matching as R

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_slug():
    """owner/repo を git remote から推定（Issueフォーム直リンク用）。取れなければ既定。"""
    try:
        url = subprocess.check_output(["git", "-C", HERE, "config", "--get", "remote.origin.url"],
                                      text=True, stderr=subprocess.DEVNULL).strip()
        m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "ktakahashi7755-creator/its-company-os"


def _issue_url(slug, template_file):
    from urllib.parse import quote
    return f"https://github.com/{slug}/issues/new?template={quote(template_file)}"


def _active_case():
    """現行案件（active-case.json）を台帳形式で返す。無ければ cases.json の active 先頭。"""
    ac = dict(R.ACTIVE_CASE or {})
    if ac.get("case_id"):
        ac.setdefault("case_title", ac.get("case_id"))
        cases = MC.load_cases()
        for c in cases:                       # cases.json 側に skills があれば拾う（マッチ本文）
            if c.get("case_id") == ac.get("case_id"):
                ac.setdefault("skills", c.get("skills", ""))
        return ac
    cases = [c for c in MC.load_cases() if c.get("status", "active") == "active"]
    return cases[0] if cases else None


def _badge(text, kind):
    return f'<span class="badge b-{kind}">{html.escape(text)}</span>'


def _score_class(v):
    return "st-hi" if v >= 85 else ("st-mid" if v >= 70 else ("st-lo" if v >= 1 else "st-x"))


def _verdict_kind(v):
    return {"本命": "ok", "提案可": "ok", "参考": "hold", "除外": "x"}.get(v, "hold")


def build_html(stamp=""):
    slug = _repo_slug()
    case = _active_case()
    talents = MC.load_talents()
    cases = MC.load_cases()

    # 現行案件 × 人材台帳 の決定論マッチ（本命→提案可→参考→除外）
    ranked = MC.match_case_to_talents(case, talents) if case else []
    honban = [r for r in ranked if r["match"]["verdict"] == "本命"]
    avail = [t for t in talents if "対象外" not in str(t.get("availability", ""))]
    scores = [r["match"]["score"] for r in ranked] or [0]
    kpi = {
        "cases": len([c for c in cases if c.get("status", "active") == "active"]) or (1 if case else 0),
        "talents": len(talents),
        "avail": len(avail),
        "honban": len(honban),
        "avg": round(sum(scores) / len(scores)) if ranked else 0,
    }

    case_url = _issue_url(slug, "新案件.yml")
    talent_url = _issue_url(slug, "人材.yml")

    # ---- 本命ヒーロー ----
    if honban:
        top = honban[0]
        t, m = top["talent"], top["match"]
        gl = "".join(
            f'<div class="guard-row g-{k}"><span class="g-ico">{"✓" if k=="pass" else "!"}</span>'
            f'<span class="g-label">{html.escape(lbl)}</span><span class="g-val">{html.escape(val)}</span></div>'
            for lbl, val, k in [
                (f"年齢ガード（〜{case.get('age_hard_limit','—')}歳）", f"{t.get('age','—')} 適合", "pass"),
                (f"両刀の軸（{case.get('axis','—')}）", "両軸ヒット", "pass"),
                ("粗利（クライアント − 要員希望）", f"+{m['rate']['margin']}万" if m['rate']['margin'] is not None else "要確認", "pass" if m['rate']['verdict'] in ("ok","thin") else "warn"),
            ])
        hero = f"""
      <div class="card hero">
        <div class="hero-top"><span class="dot"></span><b>{html.escape(case.get('case_title','案件'))}</b>
          <span class="when">スコア {m['score']} / 100</span></div>
        <div class="hero-body">
          <div class="ring"><svg width="104" height="104" viewBox="0 0 104 104" aria-hidden="true">
            <circle cx="52" cy="52" r="44" fill="none" stroke="var(--line)" stroke-width="10"></circle>
            <circle cx="52" cy="52" r="44" fill="none" stroke="var(--good)" stroke-width="10" stroke-linecap="round"
              stroke-dasharray="276" stroke-dashoffset="{round(276*(1-m['score']/100))}" transform="rotate(-90 52 52)"></circle>
          </svg><div class="val"><b>{m['score']}</b><small>SCORE</small></div></div>
          <div class="hero-who"><h3>{html.escape(t.get('name','要員'))} さん</h3>
            <div class="meta"><b>{html.escape(str(t.get('age','—')))}</b> ・ 希望 <b>{html.escape(str(t.get('rate','—')))}</b> ・ 稼働 <b>{html.escape(str(t.get('availability','—')))}</b></div>
            <div class="chips"><span class="chip axis">{html.escape(case.get('axis','—'))} 両刀</span>
              <span class="chip">{html.escape((t.get('bp') or '所属未設定'))}</span></div>
          </div>
        </div>
        <div class="guard">{gl}</div>
        <div class="note"><span>⚠</span><div><b>送信は手動。</b>下書きは sales@ に保存（自動送信なし）。内容・宛先・添付を確認してから代表が送信。</div></div>
      </div>"""
    else:
        empty_msg = ("人材台帳が空です。右上の「人材を投入」からスキルシートを登録すると、この案件に自動マッチします。"
                     if not talents else "現行案件の本命（両刀成立×年齢適合×粗利OK×しきい値以上）はまだありません。")
        hero = f"""
      <div class="card"><div class="empty"><div class="empty-ic">🎯</div>
        <b>本命候補なし</b><p>{html.escape(empty_msg)}</p>
        <a class="btn primary" href="{talent_url}">👤 人材を投入する ▸</a></div></div>"""

    # ---- 候補リスト（本命以外の上位）----
    rest = [r for r in ranked if r is not honban[0]] if honban else ranked
    rows = "".join(
        f"""<div class="row"><div class="score-tag {_score_class(r['match']['score'])}">{r['match']['score']}</div>
          <div class="who"><b>{html.escape(r['talent'].get('name','要員'))} さん</b>
          <div class="sub">{html.escape(str(r['talent'].get('age','—')))} ・ 希望{html.escape(str(r['talent'].get('rate','—')))} ・ {html.escape(r['match']['reason'])}
          {('／⚠ '+html.escape('・'.join(r['match']['flags']))) if r['match']['flags'] else ''}</div></div>
          {_badge(r['match']['verdict'], _verdict_kind(r['match']['verdict']))}</div>"""
        for r in rest[:8]) or '<div class="row"><div class="who"><div class="sub">候補なし（人材を投入してください）</div></div></div>'

    # ---- 案件台帳 ----
    case_rows = "".join(
        f"""<tr><td>{html.escape(c.get('case_title', c.get('case_id','')))}</td>
          <td>{html.escape(str(c.get('axis','—')))}</td><td class="num">{('〜'+str(c.get('age_hard_limit'))) if c.get('age_hard_limit') else '不問'}</td>
          <td class="num">{html.escape(str(c.get('client_rate','—')))}</td>
          <td><span class="tag {'active' if c.get('status','active')=='active' else 'dim'}">{html.escape(c.get('status','active'))}</span></td></tr>"""
        for c in (cases or ([case] if case else []))) or '<tr><td colspan="5">案件台帳は空です</td></tr>'

    # ---- 要員台帳 ----
    talent_rows = "".join(
        f"""<tr><td>{html.escape(t.get('name','要員'))}</td><td>{html.escape(str(t.get('axis_hint') or '—'))}</td>
          <td class="num">{html.escape(str(t.get('age','—')))}</td><td class="num">{html.escape(str(t.get('rate','—')))}</td>
          <td><span class="tag {'on' if '即' in str(t.get('availability','')) else ('dim' if '対象外' in str(t.get('availability','')) else 'wait')}">{html.escape(str(t.get('availability','—')))}</span></td></tr>"""
        for t in talents) or '<tr><td colspan="5">要員台帳は空です。「人材を投入」から登録してください。</td></tr>'

    stamp_txt = f"生成 {html.escape(stamp)}" if stamp else "台帳から生成"
    return _TEMPLATE.format(
        case_url=case_url, talent_url=talent_url, hero=hero, rows=rows,
        case_rows=case_rows, talent_rows=talent_rows, stamp=stamp_txt,
        k_cases=kpi["cases"], k_avail=kpi["avail"], k_honban=kpi["honban"], k_avg=kpi["avg"],
        case_title=html.escape(case.get("case_title", "（現行案件なし）") if case else "（現行案件なし）"),
        axis=html.escape(case.get("axis", "—") if case else "—"),
        pickup=html.escape(str(case.get("pickup_min", 85) if case else 85)),
    )


def to_fragment(full):
    """自己完結フルHTML → Artifact用フラグメント（doctype/html/head/bodyタグ無し・title/styleは残す）。"""
    title = re.search(r"<title>.*?</title>", full, re.S)
    style = re.search(r"<style>.*?</style>", full, re.S)
    body = re.search(r"<body>(.*)</body>", full, re.S)
    return "\n".join([title.group(0) if title else "", style.group(0) if style else "",
                      body.group(1).strip() if body else full])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "dashboard.html"))
    ap.add_argument("--stamp", default="")
    ap.add_argument("--fragment", action="store_true", help="Artifact用フラグメント（doctype/head/body無し）で出力")
    ap.add_argument("--print", action="store_true", help="標準出力にHTMLを出す（ファイル書き込みしない）")
    args = ap.parse_args()
    htmlout = build_html(args.stamp)
    if args.fragment:
        htmlout = to_fragment(htmlout)
    if args.print:
        print(htmlout)
        return
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    print(f"[dashboard] 生成: {args.out}（{len(htmlout)} bytes・実データ／台帳）")


# ---- 自己完結HTMLテンプレート（明るいテーマ・単一・CSP安全＝インラインhandler無し）----
_TEMPLATE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ITS SESマッチング 運用コンソール</title>
<style>
:root{{color-scheme:light;--bg:#f2f7fa;--bg2:radial-gradient(1100px 560px at 100% -12%,#e1f2f5 0%,#f2f7fa 52%);
--surface:#fff;--surface2:#eef4f7;--line:#e3ebf0;--line2:#ccd8df;--ink:#17262f;--ink2:#4c5b68;--ink3:#7f8e99;
--accent:#0aa0b3;--accent-ink:#067c8c;--accent-wash:#d8f0f3;--violet:#6a66d8;--violet-ink:#4a46bb;
--good:#1f9d5f;--good-wash:#dbf1e5;--warn:#bd7500;--warn-wash:#f8ead0;--crit:#cf4a41;--crit-wash:#f9e0dd;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",Meiryo,sans-serif;}}
*{{box-sizing:border-box}}body{{margin:0;font-family:var(--sans);color:var(--ink);background:var(--bg2),var(--bg);
background-attachment:fixed;line-height:1.5;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:860px;margin:0 auto;padding:0 14px 60px}}
.topbar{{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 86%,transparent);backdrop-filter:blur(10px);
border-bottom:1px solid var(--line);margin:0 -14px 18px;padding:12px 16px;display:flex;align-items:center;gap:12px}}
.logo{{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,var(--accent),var(--accent-ink));
display:grid;place-items:center;color:#fff;font-weight:800;font-size:13px}}
.brand b{{font-size:14px;display:block}}.brand span{{font-size:11px;color:var(--ink3)}}
.spacer{{flex:1}}.phase-pill{{font-size:11px;font-weight:700;color:var(--accent-ink);background:var(--accent-wash);
border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);padding:4px 10px;border-radius:999px;white-space:nowrap}}
.intake{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:22px}}
.intake a{{text-decoration:none;color:#fff;border-radius:16px;padding:16px;position:relative;overflow:hidden;
box-shadow:0 8px 24px -14px rgba(20,60,80,.3);display:block}}
.intake a.case{{background:linear-gradient(135deg,var(--accent),var(--accent-ink))}}
.intake a.talent{{background:linear-gradient(135deg,var(--violet),var(--violet-ink))}}
.intake .ic{{font-size:22px}}.intake .t{{font-size:15px;font-weight:800;margin-top:8px}}
.intake .s{{font-size:11.5px;opacity:.9;margin-top:3px;line-height:1.45}}
.intake .go{{margin-top:12px;font-size:12px;font-weight:700;display:inline-block;background:rgba(255,255,255,.18);padding:6px 11px;border-radius:999px}}
section{{margin-bottom:20px}}.sec{{display:flex;align-items:baseline;gap:10px;margin:0 2px 10px}}
.sec h2{{font-size:12px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--ink3);margin:0}}
.sec .sub{{font-size:12px;color:var(--ink3);margin-left:auto}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:0 1px 2px rgba(20,40,55,.05),0 10px 26px -16px rgba(20,60,80,.2)}}
.hero-top{{display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--accent-wash) 55%,var(--surface))}}
.hero-top .dot{{width:8px;height:8px;border-radius:50%;background:var(--good);box-shadow:0 0 0 4px var(--good-wash)}}
.hero-top b{{font-size:12.5px}}.hero-top .when{{margin-left:auto;font-size:11.5px;color:var(--ink2);font-variant-numeric:tabular-nums}}
.hero-body{{display:flex;gap:18px;padding:18px 16px;align-items:center}}
.ring{{width:104px;height:104px;position:relative;flex:none}}.ring svg{{display:block}}
.ring .val{{position:absolute;inset:0;display:grid;place-content:center;text-align:center}}
.ring .val b{{font-size:28px;font-family:var(--mono);font-weight:700}}.ring .val small{{display:block;font-size:10px;color:var(--ink3);letter-spacing:.12em}}
.hero-who h3{{margin:0 0 3px;font-size:20px}}.hero-who .meta{{font-size:13px;color:var(--ink2);margin-bottom:10px}}
.hero-who .meta b{{color:var(--ink)}}.chips{{display:flex;flex-wrap:wrap;gap:6px}}
.chip{{font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:var(--surface2);border:1px solid var(--line);color:var(--ink2)}}
.chip.axis{{background:var(--accent-wash);border-color:color-mix(in srgb,var(--accent) 28%,transparent);color:var(--accent-ink)}}
.guard{{margin:0 16px 16px;border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.guard-row{{display:flex;align-items:center;gap:10px;padding:9px 12px;font-size:13px;border-top:1px solid var(--line)}}
.guard-row:first-child{{border-top:none}}.guard-row .g-ico{{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-size:12px;font-weight:800;color:#fff}}
.g-pass .g-ico{{background:var(--good)}}.g-warn .g-ico{{background:var(--warn)}}
.guard-row .g-label{{color:var(--ink2)}}.guard-row .g-val{{margin-left:auto;font-weight:600}}
.g-pass .g-val{{color:var(--good)}}.g-warn .g-val{{color:var(--warn)}}
.note{{display:flex;gap:8px;margin:0 16px 16px;padding:10px 12px;border-radius:10px;background:var(--warn-wash);border:1px solid color-mix(in srgb,var(--warn) 30%,transparent);font-size:12.5px;color:var(--ink2)}}
.note b{{color:var(--warn)}}
.empty{{padding:30px 20px;text-align:center}}.empty-ic{{font-size:34px}}.empty b{{display:block;margin:8px 0 4px;font-size:16px}}
.empty p{{font-size:13px;color:var(--ink3);margin:0 0 16px}}
.btn{{display:inline-block;text-align:center;font-size:13.5px;font-weight:700;padding:11px 16px;border-radius:10px;text-decoration:none;border:1px solid var(--line);background:var(--surface2);color:var(--ink)}}
.btn.primary{{background:var(--accent);border-color:var(--accent);color:#fff}}
.rows{{display:flex;flex-direction:column}}.row{{display:flex;align-items:center;gap:12px;padding:13px 16px;border-top:1px solid var(--line)}}
.row:first-child{{border-top:none}}.score-tag{{width:44px;text-align:center;font-family:var(--mono);font-weight:700;font-size:16px;padding:6px 0;border-radius:9px;flex:none}}
.st-hi{{background:var(--good-wash);color:var(--good)}}.st-mid{{background:var(--accent-wash);color:var(--accent-ink)}}
.st-lo{{background:var(--surface2);color:var(--ink3)}}.st-x{{background:var(--crit-wash);color:var(--crit)}}
.row .who{{flex:1;min-width:0}}.row .who b{{font-size:14.5px}}.row .who .sub{{font-size:12px;color:var(--ink3)}}
.badge{{font-size:11px;font-weight:700;padding:4px 8px;border-radius:999px;white-space:nowrap;flex:none}}
.b-ok{{background:var(--good-wash);color:var(--good)}}.b-hold{{background:var(--warn-wash);color:var(--warn)}}.b-x{{background:var(--crit-wash);color:var(--crit)}}
.tscroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px;min-width:440px}}
th,td{{text-align:left;padding:10px 12px;border-top:1px solid var(--line);white-space:nowrap}}
th{{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink3);font-weight:700;border-top:none}}
td.num{{font-variant-numeric:tabular-nums}}tr td:first-child,tr th:first-child{{position:sticky;left:0;background:var(--surface)}}
.tag{{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px}}
.tag.active{{background:var(--accent-wash);color:var(--accent-ink)}}.tag.dim{{background:var(--surface2);color:var(--ink3)}}
.tag.on{{background:var(--good-wash);color:var(--good)}}.tag.wait{{background:var(--warn-wash);color:var(--warn)}}
.kpis{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}
.kpi{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px}}
.kpi .l{{font-size:11px;color:var(--ink3)}}.kpi .v{{font-family:var(--mono);font-size:26px;font-weight:700;margin-top:4px}}
.kpi .v .u{{font-size:13px;color:var(--ink3);margin-left:2px}}
.foot{{margin-top:24px;padding-top:14px;border-top:1px solid var(--line);font-size:11.5px;color:var(--ink3);line-height:1.7}}
.foot b{{color:var(--ink2)}}
@media(min-width:680px){{.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}}.grid2>section{{margin-bottom:0}}}}
</style></head><body><div class="wrap">
<div class="topbar"><div class="logo">ITS</div><div class="brand"><b>SESマッチング 運用コンソール</b><span>ITS合同会社 ・ 社内専用</span></div>
<div class="spacer"></div><div class="phase-pill">実データ ・ {stamp}</div></div>

<div class="intake">
  <a class="case" href="{case_url}"><div class="ic">📥</div><div class="t">案件を投入</div>
    <div class="s">GitHubのフォームにJDを貼るだけ。要員台帳と自動マッチ→提案下書き。</div><span class="go">フォームを開く ▸</span></a>
  <a class="talent" href="{talent_url}"><div class="ic">👤</div><div class="t">人材を投入</div>
    <div class="s">スキルシートを貼るだけ。案件台帳と自動マッチ→提案下書き。</div><span class="go">フォームを開く ▸</span></a>
</div>

<section><div class="sec"><h2>現行案件の本命</h2><span class="sub">{case_title}</span></div>{hero}</section>

<section><div class="sec"><h2>候補（現行案件 × 要員台帳）</h2><span class="sub">しきい値 {pickup}点</span></div>
  <div class="card rows">{rows}</div></section>

<div class="grid2">
<section><div class="sec"><h2>案件台帳</h2></div><div class="card tscroll"><table>
  <thead><tr><th>案件</th><th>両刀の軸</th><th>年齢</th><th class="num">単価</th><th>状態</th></tr></thead>
  <tbody>{case_rows}</tbody></table></div></section>
<section><div class="sec"><h2>要員 / BP台帳</h2></div><div class="card tscroll"><table>
  <thead><tr><th>要員</th><th>軸</th><th>年齢</th><th class="num">希望</th><th>稼働</th></tr></thead>
  <tbody>{talent_rows}</tbody></table></div></section>
</div>

<section><div class="sec"><h2>サマリー</h2></div><div class="kpis">
  <div class="kpi"><div class="l">アクティブ案件</div><div class="v">{k_cases}<span class="u">件</span></div></div>
  <div class="kpi"><div class="l">稼働可 要員</div><div class="v">{k_avail}<span class="u">名</span></div></div>
  <div class="kpi"><div class="l">本命マッチ</div><div class="v">{k_honban}<span class="u">件</span></div></div>
  <div class="kpi"><div class="l">平均マッチ度</div><div class="v">{k_avg}<span class="u">点</span></div></div>
</div></section>

<div class="foot"><b>ガードレール：</b>年齢ハード上限で自動除外 ・ 両刀の軸ヒット必須 ・ 粗利¥8万死守 ・ しきい値未満は本命にしない ・ 自動送信なし（下書きのみ・代表が手動送信）。<br>
<b>この画面は台帳（cases.json / talents.json）の実データから決定論で生成。</b>投入ボタンは実際のGitHub Issueフォームに直結。金額・件数は台帳の実値のみ。</div>
</div></body></html>
"""


if __name__ == "__main__":
    main()
