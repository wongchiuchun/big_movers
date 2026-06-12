"""Render the out-of-sample + control findings as a clean light-theme one-pager
with a sticky scroll-along glossary so every term is defined alongside the data.

Reads honest_eval.json (filter generalization), engine_results.json (config table
+ per-year consistency) and continuation_results.json, writes
output/honest_findings.html.

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

# Friendly name + one-line tooltip for each raw filter code.
FILTER_FRIENDLY = {
    "ordinal_le3":    ("Enter early (≤3rd push off the low)", "One of the first three breakouts since the 63-day low — early in the move."),
    "extension_lt50": ("Not extended (&lt;50% above the low)", "Price is less than 50% above its 63-day low — still near the base."),
    "relvol_ge15":    ("Volume ≥ 1.5× average", "Today's volume at least 50% above the 20-day average."),
    "cir_gt75_gaps":  ("Gap closes strong (top 25%)", "On gap days, the close lands in the top quarter of the day's range."),
    "tight_lt5":      ("Tight base (&lt;5% wiggle)", "Last 10 closes vary by under 5% — a calm, coiled base."),
    "spy_above_50":   ("Market uptrend (SPY &gt; 50-day)", "The S&amp;P 500 ETF is above its 50-day average at entry."),
    "stack_bull":     ("Bullish EMA stack", "10-EMA &gt; 20-EMA &gt; 50-SMA with price on top."),
    "near_high_25":   ("Within 25% of 52-wk high", "Price is no more than 25% below its one-year high."),
}

# The scroll-along glossary: (group title, [(term, definition)])
GLOSSARY = [
    ("How the test works", [
        ("R — the risk unit", "Everything is measured in R. <b>R = entry price − stop price</b> — what you lose if stopped out. A +3R trade made 3× what you risked; −1R is a full stop-out. R makes a $5 stock and a $500 stock directly comparable."),
        ("Train / test split", "The 949 tickers are split 50/50 by symbol. The strategy is <b>chosen on the train half</b>, then measured untouched on the <b>held-out test half</b>. Survives test → it generalises. Collapses → it was overfit (fitted to noise)."),
        ("Control group", "Signals that fired on charts that did <b>not</b> become recorded big movers (any date outside a winning window, across 984 tickers). This is the false-positive population — what the same trigger does in the wild. Winners-only data can't show it."),
        ("Survivorship", "The trap of studying only winners. A 60% win rate on winners-only data does NOT mean 60% live — the losers were never in the dataset. The control group is the antidote."),
    ]),
    ("The numbers in the tables", [
        ("avg R", "Average R per trade in that bucket — the raw expectancy."),
        ("w99 R (capped)", "Average R after capping the top 1% of winners (99th percentile). One 80R freak can flatter an average; this shows the edge without leaning on a single trade. <b>We rank by this.</b>"),
        ("win", "Win rate — % of trades that closed positive."),
        ("med R", "The middle trade. Often negative here — the strategy wins through a minority of big trades, not by being right often."),
        ("R/30d", "R earned per 30 days held — return per unit of time, so fast and slow strategies compare fairly."),
        ("edge", "For a filter: w99-R of trades that PASS it minus those that FAIL it. Positive = the filter helps; the number is how much. <b>Holds</b> = same sign on train and test; <b>flips</b> = noise."),
        ("year std / worst year", "Spread of yearly average-R (lower = steadier) and the single worst year. Consistency measures."),
    ]),
    ("Entry filters (the codes)", [
        ("Enter early <span class='code'>ordinal_le3</span>", "The 'ordinal' is which numbered breakout this is, counting from the most recent 63-day low. ≤3 = one of the first three pushes off the base — early, not chasing a stock that already ran."),
        ("Not extended <span class='code'>extension_lt50</span>", "How far price has stretched above its 63-day low, in %. &lt;50% = still within 50% of the recent floor."),
        ("Volume ≥1.5× <span class='code'>relvol_ge15</span>", "Today's volume vs the 20-day average. ≥1.5× = at least 50% heavier than normal (institutional participation)."),
        ("Strong gap close <span class='code'>cir_gt75_gaps</span>", "'Close-in-range' = where the close sits in the day's high–low bar. &gt;75% = top quarter. Applied only to gap-up entries."),
        ("Tight base <span class='code'>tight_lt5</span>", "Std-dev of the last 10 closes as a % of price. &lt;5% = calm, coiled base."),
        ("Market uptrend <span class='code'>spy_above_50</span>", "Is SPY above its 50-day average at the entry bar — a market-regime gauge."),
        ("EMA stack <span class='code'>stack_bull</span>", "10-EMA &gt; 20-EMA &gt; 50-SMA with price on top — an aligned uptrend."),
        ("Near highs <span class='code'>near_high_25</span>", "Price within 25% of its 52-week high."),
    ]),
    ("Stop, exit & strategy terms", [
        ("ATR", "Average True Range — average daily price travel over 20 days. A volatility unit."),
        ("Structural / swing-low stop", "Stop under the lowest low of the last 10 bars (capped at 1.5×ATR) — under the chart structure, not under today's candle wick."),
        ("3-bar hold", "The trailing exit can't fire in the first 3 days after entry, so a normal shakeout doesn't knock you out early."),
        ("50-MA trail (E50)", "Exit when price closes below its 50-period moving average — the default 'let it run' exit."),
        ("Free roll", "At +2R, sell half and move the stop to breakeven. The remaining half is now 'free' (can't lose). Raises win rate and cuts variance."),
        ("Mode A / Mode B", "<b>A Runner</b> = hold the whole position to the 50-MA break (max R). <b>B Consistent</b> = free roll (steadier). Same entry and stop."),
        ("Continuation / leg 2", "A later entry: a pullback that reclaims the 20-EMA inside an established uptrend, taken after the move is already underway."),
        ("Extension band", "Grouping entries by how far above the 63-day low they fired: 0–50%, 50–100%, etc."),
    ]),
]

CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  background: #f7f6f3; color: #1c1c1e; margin: 0; padding: 32px 24px; line-height: 1.5; }
.wrap { max-width: 1180px; margin: 0 auto; }
.layout { display: grid; grid-template-columns: minmax(0,1fr) 340px; gap: 34px; align-items: start; }
h1 { font-size: 26px; margin: 0 0 4px; }
.sub { color: #6b6b70; margin: 0 0 22px; font-size: 14px; }
h2 { font-size: 18px; margin: 32px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #e2e0da; }
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
.code { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 11px; background:#eef0f3; color:#566; padding:1px 5px; border-radius:4px; margin-left:4px; }
.pos { color: #1b7a35; } .neg { color: #b3261e; }
.tag { display: inline-block; font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 10px; }
.tg-hold { background: #e3f3e6; color: #1b7a35; } .tg-flip { background: #fbe3e1; color: #b3261e; }
small { color: #6b6b70; }
.hint { border-bottom: 1px dotted #b9a06a; cursor: help; }
/* sticky scroll-along glossary */
.glossary { position: sticky; top: 20px; max-height: calc(100vh - 40px); overflow-y: auto;
  background:#fff; border:1px solid #e6e4de; border-radius:10px; padding: 14px 16px 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.glossary .gtitle { font-size: 16px; font-weight: 700; margin: 0 0 2px; }
.glossary .gintro { font-size: 12px; color:#6b6b70; margin: 0 0 8px; }
.glossary h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color:#8a6d3b;
  margin: 16px 0 4px; border-bottom: 1px solid #efece4; padding-bottom: 3px; }
.glossary dl { margin: 0; }
.glossary dt { font-weight: 600; font-size: 13px; margin-top: 9px; color:#222; }
.glossary dd { margin: 1px 0 0; font-size: 12.5px; color:#4a4a4f; }
@media (max-width: 920px) {
  .layout { grid-template-columns: 1fr; }
  .glossary { position: static; max-height: none; margin-top: 24px; }
}
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


def build_glossary() -> str:
    parts = ['<div class="gtitle">Glossary</div>',
             '<p class="gintro">Plain-English definitions — stays in view as you scroll.</p>']
    for group, items in GLOSSARY:
        parts.append(f"<h3>{group}</h3><dl>")
        for term, dfn in items:
            parts.append(f"<dt>{term}</dt><dd>{dfn}</dd>")
        parts.append("</dl>")
    return "".join(parts)


def main():
    he = json.load(open(os.path.join(OUT, "honest_eval.json")))
    en = json.load(open(os.path.join(OUT, "engine_results.json")))
    co = json.load(open(os.path.join(OUT, "continuation_results.json")))

    # filter generalization rows — friendly name + raw code + hover tooltip
    gen_rows = ""
    for g in he["filter_generalization"]:
        code = g["filter"]
        friendly, tip = FILTER_FRIENDLY.get(code, (code, ""))
        tag = '<span class="tag tg-hold">holds</span>' if g["holds"] else '<span class="tag tg-flip">flips</span>'
        gen_rows += (f'<tr><td><span class="hint" title="{tip}">{friendly}</span>'
                     f'<br><small class="mono">{code}</small></td>'
                     f"<td>{num(g['edge_train'])}</td><td>{num(g['edge_test'])}</td><td>{tag}</td></tr>")

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

    # continuation
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
    glossary = build_glossary()
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Big-Mover Momentum — Honest Findings</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>Big-Mover Momentum — the honest, out-of-sample picture</h1>
<p class="sub">Selected on a 50/50 train/test split of the tickers · validated on held-out test ·
stress-tested against a control group of {ns['control']:,} signals that fired outside any winning window.
<b>New to the jargon?</b> The glossary on the right defines every term and stays in view as you scroll.</p>

<div class="layout">
<div class="main">

<div class="tldr big"><b>The one thing to know.</b> The entry signal has <b>no standalone edge</b>.
When the same trigger fires on a chart that did not become a recorded big mover, the average trade is
≈0R (slightly negative on capped R) in <i>every</i> configuration. This is a
<b>risk-management + right-tail-capture</b> machine, not a high-edge signal: it wins by capping every
non-monster at ~1R and letting the rare monster run. Profit comes from asymmetry, not from being right often.</div>

<h2>1 · What generalises — only entry timing</h2>
<p>Re-running the old filter selection on train and reading the held-out test: only two filters keep their
<span class="hint" title="w99-R of trades that pass the filter minus those that fail it">edge</span>,
and both are about <b>when</b> you enter, not the trigger. (Hover any filter name for a one-line definition;
full definitions are in the glossary.)</p>
<table><tr><th>Filter — what it requires</th><th>edge · train</th><th>edge · test</th><th>verdict</th></tr>{gen_rows}</table>
<div class="warn">The old published 4-filter stack carried a <b>−36% overfit tax</b> because two of its four
filters were noise (<span class="mono">cir_gt75_gaps</span>, <span class="mono">tight_lt5</span> — they
<b>flip</b> sign out-of-sample). <span class="mono">spy_above_50</span>, the EMA stack and near-52wk-high
look useless here <i>only because the sample is all winners</i> — they are about avoiding losers, which is
why the control group exists.</div>

<h2>2 · Every strategy, on held-out tickers vs the control group</h2>
<p><small>Win % · <span class="hint" title="average R per trade">avg R</span> ·
<span class="hint" title="average R with the top 1% of winners capped — what we rank by">capped avg R (w99)</span>.
Left block = held-out winner tickers ({ns['winner_test']:,} signals). Right block = control
({ns['control']:,} signals — the wild). Highlighted rows are the two recommended modes.</small></p>
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
actually experience it). Lower <span class="hint" title="spread of yearly average-R; lower = steadier">year std</span>
and shallower worst-year = steadier equity.</small></p>
<table><tr><th>Strategy</th><th>year std</th><th>median year</th><th>worst year</th><th>neg years</th></tr>{cons_rows}</table>
<div class="tldr"><b>Free roll (trim ½ at +2R → breakeven) nearly halves year-to-year variance
(0.49 → 0.29) for the same median return.</b> That is the "more consistent, able to come back over time"
you asked for. Mode B is the recommended default; Mode A is the high-conviction option.</div>

<h2>4 · Continuation (leg 2+) entries — should you ride the later legs?</h2>
<p>The locked rules above only take the <b>first leg</b> (extension &lt;50% off the 63-day low), so once a
move is underway the indicator goes quiet — and a first-entry shakeout locks you out of the whole run.
This tests an optional <span class="hint" title="a pullback that reclaims the 20-EMA inside an uptrend, taken after the move is underway">continuation</span>
entry: a pullback that <b>reclaims the 20-EMA inside an uptrend</b> (above a rising 50-SMA), allowed at
<i>any</i> extension. Every entry is bucketed by how far it is off the 63-day low.</p>
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

</div>
<aside class="glossary">{glossary}</aside>
</div>
</div></body></html>"""

    path = os.path.join(OUT, "honest_findings.html")
    with open(path, "w") as fh:
        fh.write(html)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
