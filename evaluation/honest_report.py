"""Render the out-of-sample + control findings as a clean light-theme one-pager.

Reads honest_eval.json (filter generalization) and engine_results.json (config
table + per-year consistency) and writes output/honest_findings.html.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.honest_report
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evaluation", "output")

CONFIG_DESC = {
    "BO_E10_h0_SW": "Breakout · 10-EMA trail · no hold · structural stop",
    "BO_E10_h3_SW": "Breakout · 10-EMA trail · 3-bar hold · structural stop",
    "BO_E20_h3_SW": "Breakout · 20-EMA trail · 3-bar hold · structural stop",
    "BO_E50_h0_SW": "Breakout · 50-MA trail · no hold · structural stop",
    "BO_E50_h3_SW": "Mode A RUNNER — Breakout · 50-MA trail · 3-bar hold · structural stop",
    "BO_E50_h0_LOD": "Breakout · 50-MA trail · entry-day-wick stop (the one to avoid)",
    "BO_E10_h3_SW_FR": "Breakout · 10-EMA trail · 3-bar hold · structural stop · FREE ROLL",
    "BO_E50_h3_SW_FR": "Mode B CONSISTENT — Breakout · 50-MA trail · 3-bar hold · structural · FREE ROLL",
    "PB_E10_h3_SW": "Pullback (Episodic Pivot) · 10-EMA trail · 3-bar hold · structural",
    "PB_E20_h3_SW": "Pullback · 20-EMA trail · 3-bar hold · structural",
    "PB_E50_h3_SW": "Pullback · 50-MA trail · 3-bar hold · structural",
    "BO_E50_h3_ATR": "Breakout · 50-MA trail · 3-bar hold · 1×ATR stop",
}
HIGHLIGHT = {"BO_E50_h3_SW", "BO_E50_h3_SW_FR"}

CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  background: #f7f6f3; color: #1c1c1e; margin: 0; padding: 40px 24px; line-height: 1.5; }
.wrap { max-width: 980px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; }
.sub { color: #6b6b70; margin: 0 0 28px; font-size: 14px; }
h2 { font-size: 18px; margin: 34px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #e2e0da; }
.card { background: #fff; border: 1px solid #e6e4de; border-radius: 10px; padding: 18px 20px; margin: 14px 0;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.big { font-size: 15px; }
.tldr { background: #eef6ee; border-left: 4px solid #2e7d32; border-radius: 6px; padding: 12px 16px; margin: 14px 0; font-size: 14px; }
.warn { background: #fdf3e7; border-left: 4px solid #c77700; border-radius: 6px; padding: 12px 16px; margin: 14px 0; font-size: 14px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }
th, td { text-align: right; padding: 7px 9px; border-bottom: 1px solid #ececec; }
th:first-child, td:first-child { text-align: left; }
th { background: #f0efea; font-weight: 600; }
tr.hl { background: #fff7e8; }
tr.hl td { font-weight: 600; }
.mono { font-family: 'SF Mono', Menlo, Consolas, monospace; }
.pos { color: #1b7a35; } .neg { color: #b3261e; }
.tag { display: inline-block; font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 10px; }
.tg-hold { background: #e3f3e6; color: #1b7a35; } .tg-flip { background: #fbe3e1; color: #b3261e; }
small { color: #6b6b70; }
"""


def num(v, pos_color=True):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return f'<span class="mono">{v}</span>'
    cls = ""
    if pos_color:
        cls = "pos" if f > 0 else ("neg" if f < 0 else "")
    return f'<span class="mono {cls}">{f:+.2f}</span>' if pos_color else f'<span class="mono">{f:g}</span>'


def main():
    he = json.load(open(os.path.join(OUT, "honest_eval.json")))
    en = json.load(open(os.path.join(OUT, "engine_results.json")))
    co = json.load(open(os.path.join(OUT, "continuation_results.json")))

    # filter generalization rows
    gen_rows = ""
    for g in he["filter_generalization"]:
        tag = '<span class="tag tg-hold">holds</span>' if g["holds"] else '<span class="tag tg-flip">flips</span>'
        gen_rows += (f"<tr><td>{g['filter']}</td><td>{num(g['edge_train'])}</td>"
                     f"<td>{num(g['edge_test'])}</td><td>{tag}</td></tr>")

    # engine config table
    cfg_rows = ""
    for name, row in en["table"].items():
        hl = ' class="hl"' if name in HIGHLIGHT else ""
        def cell(b, key, color=True):
            s = row.get(b, {})
            return num(s.get(key), color) if s.get("n") else '<span class="mono">–</span>'
        cfg_rows += (
            f"<tr{hl}><td>{CONFIG_DESC.get(name, name)}<br><small class='mono'>{name}</small></td>"
            f"<td>{cell('winner_test','win',False)}</td><td>{cell('winner_test','avgR')}</td>"
            f"<td>{cell('winner_test','avgRw99')}</td>"
            f"<td>{cell('control','win',False)}</td><td>{cell('control','avgR')}</td>"
            f"<td>{cell('control','avgRw99')}</td></tr>")

    # consistency rows
    cons_rows = ""
    for name, c in en.get("consistency_finalists", {}).items():
        hl = ' class="hl"' if name in HIGHLIGHT else ""
        cons_rows += (f"<tr{hl}><td>{CONFIG_DESC.get(name, name)}<br><small class='mono'>{name}</small></td>"
                      f"<td>{num(c['yr_std'], False)}</td><td>{num(c['median_year'])}</td>"
                      f"<td>{num(c['worst_year'])}</td><td class='mono'>{c['neg_years']}/{c['years']}</td></tr>")

    # continuation: base + cont rows by extension band
    BAND_LABEL = {"0-50% (base)": "0–50% (base)", "50-100%": "50–100% (leg 2)",
                  "100-200%": "100–200% (leg 3)", "200%+": "200%+ (leg 4+)"}
    cont_rows = ""
    order = [("base", "0-50% (base)"), ("cont", "0-50% (base)"), ("cont", "50-100%"),
             ("cont", "100-200%"), ("cont", "200%+")]
    for kind, band in order:
        d = co["by_band"].get(kind, {}).get(band, {})
        te, ct = d.get("winner_test", {}), d.get("control", {})
        if not te.get("n"):
            continue
        kind_lbl = "Base breakout" if kind == "base" else "Continuation"
        hl = ' class="hl"' if kind == "cont" and band in ("50-100%", "100-200%") else ""
        cont_rows += (
            f"<tr{hl}><td>{kind_lbl}</td><td>{BAND_LABEL.get(band, band)}</td>"
            f"<td>{te.get('n')}</td><td>{num(te.get('win'), False)}</td><td>{num(te.get('avgR'))}</td>"
            f"<td>{ct.get('n')}</td><td>{num(ct.get('win'), False)}</td><td>{num(ct.get('avgRw99'))}</td></tr>")
    pm = co["per_move"]

    ns = en["n_signals"]
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Big-Mover Momentum — Honest Findings</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>Big-Mover Momentum — the honest, out-of-sample picture</h1>
<p class="sub">Selected on a 50/50 train/test split of the tickers · validated on held-out test ·
stress-tested against a control group of {ns['control']:,} signals that fired outside any winning window.
Generated from <span class="mono">engine_results.json</span> + <span class="mono">honest_eval.json</span>.</p>

<div class="tldr big"><b>The one thing to know.</b> The entry signal has <b>no standalone edge</b>.
When the same trigger fires on a chart that did not become a recorded big mover, the average trade is
≈0R (slightly negative on capped R) in <i>every</i> configuration. This is a
<b>risk-management + right-tail-capture</b> machine, not a high-edge signal: it wins by capping every
non-monster at ~1R and letting the rare monster run. Profit comes from asymmetry, not from being right often.</div>

<h2>1 · What generalises — only entry timing</h2>
<p>Re-running the old filter selection on train and reading the held-out test: only two filters keep their
edge, and both are about <b>when</b> you enter, not the trigger. Edge = winsorized-R difference (pass − fail).</p>
<table><tr><th>Filter</th><th>edge · train</th><th>edge · test</th><th></th></tr>{gen_rows}</table>
<div class="warn">The old published 4-filter stack carried a <b>−36% overfit tax</b> because two of its four
filters were noise (<span class="mono">cir_gt75_gaps</span>, <span class="mono">tight_lt5</span>).
<span class="mono">spy&gt;50</span>, EMA-stack and near-52wk-high look useless here <i>only because the
sample is all winners</i> — they are about avoiding losers, which is why the control group exists.</div>

<h2>2 · Every strategy, on held-out tickers vs the control group</h2>
<p><small>Win % · avg R · capped avg R. Left block = held-out winner tickers ({ns['winner_test']:,} signals).
Right block = control ({ns['control']:,} signals). Highlighted rows are the two recommended modes.</small></p>
<table>
<tr><th>Strategy</th><th colspan="3" style="text-align:center">HELD-OUT WINNERS</th>
<th colspan="3" style="text-align:center">CONTROL (the wild)</th></tr>
<tr><th></th><th>win</th><th>avg R</th><th>w99 R</th><th>win</th><th>avg R</th><th>w99 R</th></tr>
{cfg_rows}</table>
<div class="tldr">Read across any row: a strong winner column collapses to ≈0 / negative on control.
The let-it-run 50-MA trail (Mode A) earns the most on real movers but is the most control-fragile —
which is exactly why you only use it when conviction is high.</div>

<h2>3 · Consistency — why free roll is the default</h2>
<p><small>Per-year average R on the realistic blended stream (all winners + control together, as you'd
actually experience it). Lower year-std and shallower worst-year = steadier equity.</small></p>
<table><tr><th>Strategy</th><th>year std</th><th>median year</th><th>worst year</th><th>neg years</th></tr>{cons_rows}</table>
<div class="tldr"><b>Free roll (trim ½ at +2R → breakeven) nearly halves year-to-year variance
(0.49 → 0.29) for the same median return.</b> That is the "more consistent, able to come back over time"
you asked for. Mode B is the recommended default; Mode A is the high-conviction option.</div>

<h2>4 · Continuation (leg 2+) entries — should you ride the later legs?</h2>
<p>The locked rules above only take the <b>first leg</b> (extension &lt;50% off the 63-day low), so once a
move is underway the indicator goes quiet — and a first-entry shakeout locks you out of the whole run.
This tests an optional continuation entry: a pullback that <b>reclaims the 20-EMA inside an uptrend</b>
(above a rising 50-SMA), allowed at <i>any</i> extension. Every entry is bucketed by how far it is off the
63-day low.</p>
<table>
<tr><th>Entry</th><th>extension off low</th><th colspan="2" style="text-align:center">HELD-OUT WINNERS</th>
<th></th><th colspan="2" style="text-align:center">CONTROL (the wild)</th></tr>
<tr><th></th><th></th><th>n</th><th>win</th><th>avg R</th><th>n</th><th>win</th><th>w99 R</th></tr>
{cont_rows}</table>
<div class="tldr"><b>Continuation entries are worth it.</b> They earn less per trade than the first leg
(~1.0–1.3R vs 2.1R) but stay positive out-of-sample at <i>every</i> extension — and their control R is
slightly <b>positive</b>, i.e. <b>better-behaved than the base breakout</b>. The pullback-into-an-uptrend
gate is a higher-quality filter than a raw new-high breakout: less chasing, not more.</div>
<div class="card big"><b>Per-move capture (winning moves).</b>
{pm['pct_moves_with_continuation']}% of winning moves ({pm['moves_with_a_continuation_entry']:,} of
{pm['winning_moves_seen']:,}) offered at least one continuation entry. The base entry captures
~<b>{pm['avg_base_R_per_move']}R</b> per move; continuation adds
<b>+{pm['avg_extra_R_from_continuation_when_present']}R</b> on average (median
+{pm['median_extra_R']}R) — roughly <b>tripling the R captured per move</b>, and re-entering after a
shakeout. Cost: more positions / heat and a lower hit-rate per trade. Shipped as an <b>optional,
off-by-default</b> toggle in the Pine indicator (blue "BUY leg2" when flat, faded "ADD" when in a trade).</div>

<h2>5 · The locked strategy</h2>
<div class="card big">
<b>Universe</b> ADR 4–8%, ≥$5M/day dollar volume.<br>
<b>Entry</b> breakout (20/50-day high) or gap ≥5% on ≥1.5× volume — only if <b>early</b>
(≤3 triggers off the 63-day low) and <b>not extended</b> (&lt;50% above it).<br>
<b>Stop</b> structural swing low (10-bar low, capped 1.5×ATR). Fixed 1R risk unit.<br>
<b>Hold</b> 3-bar shakeout guard — no MA exit in the first 3 closes.<br>
<b>Mode B (default)</b> trim ½ at +2R, stop to breakeven, trail the rest on the 50-MA.<br>
<b>Mode A (high conviction)</b> no trim, hold to the 50-MA close-below.<br>
<b>Expectation</b> ~30% live win rate (not the database's 50–60%); small positive per-trade
expectancy carried by the right tail. Size so −1R ≈ 0.5–1% of equity.
</div>
<p class="sub">Full method: <span class="mono">evaluation/REFLECTION.md</span> ·
locked spec: <span class="mono">evaluation/STRATEGY_FINAL.md</span> ·
chart tool: <span class="mono">pinescript/big_mover_signals.pine</span></p>
</div></body></html>"""

    path = os.path.join(OUT, "honest_findings.html")
    with open(path, "w") as fh:
        fh.write(html)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
