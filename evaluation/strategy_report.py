"""Render strategy_results.json into the strategy playbook HTML + strategy_spec.json.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.strategy_report
"""
from __future__ import annotations

import html
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")

STOP_DESC = {
    "LOD": "low of the entry day (raw — EP style, can be very tight)",
    "LOD_ATR": "low of entry day, but at least 0.5×ATR20 of room",
    "ATR10": "entry − 1.0×ATR20",
    "SW10C": "10-bar swing low, capped at 1.5×ATR20 of risk",
}
EXIT_DESC = {
    "FIX": "fixed stop only; time-based exit at horizon",
    "E10": "exit next open after a close below the 10EMA",
    "E20": "exit next open after a close below the 20EMA",
    "E50": "exit next open after a close below the 50SMA",
    "CH25": "2.5×ATR chandelier from the running high (ratchets up only)",
    "BE_E20": "stop to breakeven once +1R trades; then 20EMA close-below exit",
    "P3_E20": "sell 1/3 at +3R; remaining 2/3 exit on a 20EMA close-below",
}
FILTER_DESC = {
    "ordinal_le3": "1st–3rd entry signal of the move only (no late chasing)",
    "extension_lt50": "stock is <50% above its move low (cold entry, not an add)",
    "cir_gt75_gaps": "gap entries only when the gap day closes >75% of its range",
    "relvol_ge15": "entry-day volume ≥1.5× its 20-day average",
    "tight_lt5": "pre-entry tightness: 10-day close stdev <5% of price",
    "spy_above_50": "SPY above its 50SMA on entry day",
    "near_high_25": "price within 25% of its 52-week high",
    "stack_bull": "full bullish EMA stack (10>20>50, price above 50)",
}


def esc(s):
    return html.escape(str(s))


def stat_row(label, s):
    if not s or s.get("n", 0) == 0:
        return f"<tr><td class='k'>{esc(label)}</td><td colspan='9'>—</td></tr>"
    return (f"<tr><td class='k'>{esc(label)}</td><td>{s['n']:,}</td><td>{s['win_pct']}%</td>"
            f"<td><b>{s['avg_r']}</b></td><td>{s['avg_r_w99']}</td><td>{s['med_r']}</td>"
            f"<td>{s['p90_r']}</td><td>{s['pct_ge_5r']}%</td><td>{s['avg_days']}</td>"
            f"<td>{s['r_per_30d']}</td></tr>")


STAT_HEAD = ("<tr><th></th><th>trades</th><th>win</th><th>avg R</th><th>avg R (w99)</th>"
             "<th>med R</th><th>p90 R</th><th>≥5R</th><th>days</th><th>R/30d</th></tr>")


def superalt_html() -> str:
    path = os.path.join(OUT_DIR, "superalt_results.json")
    if not os.path.exists(path):
        return ""
    with open(path) as fh:
        sa = json.load(fh)
    s1, s2, s3 = (sa["1_systems_unfiltered"], sa["2_systems_freshness_filtered"],
                  sa["3_exit_duel_same_entries_same_stop"])
    return f"""
<h2>Benchmark: ML Adaptive SuperTrend (superalt)</h2>
<p>AlgoAlpha's k-means-adaptive SuperTrend (factor 3), ported line-for-line and run on the same databank,
same universe, same fill conventions. Long on bullish flip, exit on bearish flip, natural stop = the ST line.
All numbers risk-normalized in R (each system sized off its own stop).</p>
<table>{STAT_HEAD}
{stat_row('Ours LOD/E50 — unfiltered', s1['ours_LOD_E50'])}
{stat_row('SuperAlt system — unfiltered', s1['superalt'])}
{stat_row('Ours LOD/E50 — freshness filters', s2['ours_LOD_E50'])}
{stat_row('SuperAlt — freshness filters (no vol gate)', s2['superalt_no_vol_filter'])}
{stat_row(f"Exit duel · E50 (same {s3['n_common_entries']} entries, LOD stop)", s3['E50_exit'])}
{stat_row('Exit duel · SuperAlt flip exit', s3['superalt_flip_exit'])}
</table>
<div class="note"><b>Verdict.</b> As an R-compounding engine, ours is superior: ~2.6× the expectancy and
~3.7× the R per month after filters. The gap is almost entirely the <em>entry + stop</em>: SuperAlt flips in
mid-trend with a ~3-ATR-wide stop (9–30% of price), so each unit of risk buys a small position; our breakout/gap
entry with a day-low stop converts the same moves into far more R. As an <em>exit</em>, SuperAlt is genuinely
good — on identical entries and stops it nearly ties the 50SMA rule (3.92 vs 4.00 winsorized avg R). And as a
<em>system</em> it wins on comfort: ~75% win rate, positive median trade, fewer decisions. Practical synthesis:
trade our entries and stops; keep SuperAlt on the chart as the trend/regime lens and as a fallback trail —
switching to it costs almost nothing if the 50SMA rule ever feels wrong in a name.</div>"""


def consistency_html() -> str:
    path = os.path.join(OUT_DIR, "consistency_results.json")
    if not os.path.exists(path):
        return ""
    with open(path) as fh:
        cons = json.load(fh)
    rows = ""
    for name, d in cons.items():
        s, c = d["stats"], d["consistency"]
        rows += (f"<tr><td class='k'>{esc(name)}</td><td>{s['n']}</td><td>{s['win_pct']}%</td>"
                 f"<td>{s['avg_r_w99']}</td><td>{s['r_per_30d']}</td>"
                 f"<td>{c['yearly_std']}</td><td>{c['yearly_worst']}</td>"
                 f"<td>{c['yearly_neg_share_pct']}%</td><td>{c['max_dd_r']}</td>"
                 f"<td>{c['longest_underwater_days']}</td><td>{c['total_r']}</td></tr>")
    return f"""
<h2>Consistency: which configuration is steadiest?</h2>
<p>All configs sequenced chronologically at 1R per trade. Yearly stats use years with ≥3 trades
(the playbook's negative years, 2005 and 2009, were single-trade years — sampling noise, not strategy
failure). "Underwater" = longest stretch below the cumulative-R high-water mark.</p>
<table><tr><th>config</th><th>n</th><th>win</th><th>avg R w99</th><th>R/30d</th>
<th>yearly std</th><th>worst year</th><th>neg years</th><th>max DD (R)</th><th>underwater (d)</th><th>total R</th></tr>
{rows}</table>
<div class="note"><b>What to take from SuperAlt — and what not to.</b> Its consistency comes from the
<em>wide, volatility-scaled stop</em>, not from its entries or its k-means machinery: give a trade ~1.5 ATR of
room and far more entries resolve positive, which smooths the years. That ingredient is already in our grid as
<span class="mono">SW10C/E50</span> — swing-low stop capped at 1.5×ATR, same 50SMA exit: yearly variance drops
~3.5× vs the headline (std 2.34 vs 8.06), no losing year with n≥3, max drawdown −8.7R vs −11.4R, half the time
underwater — while still earning 2.3× SuperAlt's R per month. The two ideas we tested and rejected: gating
entries on SuperAlt's trend state (cuts trades, no variance benefit) and its flip exit (no consistency edge over
the 50SMA). <b>Recommendation:</b> run <span class="mono">SW10C/E50</span> as the core book if steadiness matters
most; keep <span class="mono">LOD/E50</span> as a half-size satellite for A+ entries where the day low is a true
pivot — or simply split the risk budget 50/50 between the two, which blends the smooth years of one with the
tail capture of the other.</div>"""


def main() -> None:
    with open(os.path.join(OUT_DIR, "strategy_results.json")) as fh:
        res = json.load(fh)

    uni = res["universe"]
    league = res["policy_league"]
    top = res["top_policies"][0]
    alts = res["top_policies"][1:]

    league_rows = "".join(
        f"<tr class={'hl' if p['in_band'] else 'dim'}><td class='mono'>{p['stop']}</td>"
        f"<td class='mono'>{p['exit']}</td><td>{p['n']:,}</td><td>{p['win_pct']}%</td>"
        f"<td><b>{p['avg_r']}</b></td><td>{p['avg_r_w99']}</td><td>{p['med_r']}</td>"
        f"<td>{p['p90_r']}</td><td>{p['pct_ge_5r']}%</td><td>{p['avg_days']}</td>"
        f"<td>{p['r_per_30d']}</td><td>{'✓' if p['in_band'] else ''}</td></tr>"
        for p in league
    )

    marg_rows = ""
    for name, m in top["filter_marginals"].items():
        p_, f_ = m["pass"], m["fail"]
        edge = round((p_.get("avg_r_w99") or 0) - (f_.get("avg_r_w99") or 0), 2)
        kept = "✓ kept" if name in top["kept_filters"] else ""
        marg_rows += (f"<tr><td class='k'>{esc(FILTER_DESC.get(name, name))}</td>"
                      f"<td>{p_.get('n', 0):,}</td><td>{p_.get('win_pct')}%</td><td>{p_.get('avg_r_w99')}</td>"
                      f"<td>{f_.get('n', 0):,}</td><td>{f_.get('avg_r_w99')}</td>"
                      f"<td><b>{edge:+}</b></td><td>{kept}</td></tr>")

    yr_rows = "".join(
        f"<tr><td class='k'>{y}</td><td>{v['n']}</td><td>{v['win_pct']}%</td><td>{v['avg_r']}</td></tr>"
        for y, v in sorted(top["filtered_per_year"].items(), key=lambda kv: int(kv[0]))
    )
    split = top["filtered_year_split"]
    regime = top["filtered_regime"]

    exit_regime_rows = ""
    for ek, rg in top["exit_by_regime"].items():
        up, dn = rg["spy_above_50sma"], rg["spy_below_50sma"]
        exit_regime_rows += (f"<tr><td class='k mono'>{ek}</td>"
                             f"<td>{up.get('n', 0):,}</td><td>{up.get('win_pct')}%</td><td>{up.get('avg_r_w99')}</td>"
                             f"<td>{dn.get('n', 0):,}</td><td>{dn.get('win_pct')}%</td><td>{dn.get('avg_r_w99')}</td></tr>")

    alt_rows = "".join(stat_row(f"{a['stop']}/{a['exit']} (filtered)", a["filtered"]) for a in alts)
    superalt_section = superalt_html()
    consistency_section = consistency_html()

    fstats = top["filtered"]
    spec = {
        "version": 1,
        "generated": time.strftime("%Y-%m-%d"),
        "name": "Big-Mover Momentum Strategy v1 (data-derived)",
        "caveat": "Derived on a winners-only databank: absolute expectancies are inflated by selection bias; "
                  "relative policy/filter rankings are the robust output. Validate forward in sim before sizing up.",
        "universe": {"adr_pct_20": uni["adr"], "min_dollar_vol_20d_musd": uni["min_dollar_vol_m"],
                     "note": "momentum names; ADR sweet spot per trader preference"},
        "entry": {
            "signals": ["close crosses above prior 20d high", "close crosses above prior 50d high",
                        "gap ≥5% on ≥1.5x 20d volume"],
            "entry_price": "close of signal day",
            "filters": top["kept_filters"],
            "filter_descriptions": {k: FILTER_DESC[k] for k in top["kept_filters"]},
        },
        "initial_stop": {"type": top["stop"], "description": STOP_DESC[top["stop"]]},
        "exit": {"type": top["exit"], "description": EXIT_DESC[top["exit"]]},
        "expected_stats_in_sample": fstats,
        "position_sizing": {
            "risk_per_trade_pct_equity": [0.5, 1.0],
            "size_formula": "shares = (equity * risk_pct) / (entry - stop)",
            "max_portfolio_heat_r": 6,
            "note": "matches the 1R / 6R-heat caps in the Behavior Contract",
        },
    }
    with open(os.path.join(OUT_DIR, "strategy_spec.json"), "w") as fh:
        json.dump(spec, fh, indent=2)

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Big-Mover Momentum Strategy — Playbook v1</title>
<style>
  :root {{ --ink:#1a1c20; --ink2:#4a4e58; --muted:#7a7e8a; --line:#e4e2dc;
          --paper:#fbfaf7; --card:#ffffff; --accent:#8a6d3b; --green:#0a7a45; --red:#b3261e; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
        font:15px/1.55 "Plus Jakarta Sans","Segoe UI",system-ui,sans-serif; }}
  .wrap {{ max-width:1020px; margin:0 auto; padding:48px 28px 80px; }}
  h1 {{ font-family:Fraunces,Georgia,serif; font-weight:600; font-size:33px; margin:0 0 6px; }}
  h2 {{ font-family:Fraunces,Georgia,serif; font-weight:600; font-size:23px; margin:42px 0 12px; }}
  h3 {{ font-size:16px; margin:18px 0 6px; }}
  .sub {{ color:var(--muted); margin-bottom:24px; }}
  .mono {{ font-family:"JetBrains Mono",ui-monospace,monospace; }}
  table {{ border-collapse:collapse; width:100%; margin:10px 0 20px; font-size:13px; }}
  th,td {{ text-align:left; padding:6px 9px; border-bottom:1px solid var(--line); }}
  th {{ font-size:11.5px; text-transform:uppercase; letter-spacing:.03em; color:var(--muted); }}
  td.k {{ color:var(--ink2); font-weight:600; }}
  tr.hl td {{ background:#f3efe2; }}
  tr.dim td {{ color:var(--muted); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:22px 26px; margin:16px 0; }}
  .rule {{ font-size:16px; padding:14px 18px; border-left:4px solid var(--accent); background:#fdf9ee; margin:12px 0; }}
  .note {{ background:#fdf6e8; border:1px solid #ecdcb8; border-radius:10px; padding:14px 18px; margin:16px 0; font-size:14px; }}
  .warn {{ background:#fceeed; border:1px solid #e8c7c5; border-radius:10px; padding:14px 18px; margin:16px 0; font-size:14px; }}
  ul {{ padding-left:22px; }} li {{ margin:5px 0; }}
  @media print {{ .card {{ break-inside:avoid; }} }}
</style></head><body><div class="wrap">

<h1>Big-Mover Momentum Strategy — Playbook v1</h1>
<div class="sub">Derived from {uni['base_stats']['n']:,} simulated trades on the big-movers databank ·
generated {time.strftime('%Y-%m-%d')} · companion: <span class="mono">strategy_spec.json</span></div>

<div class="warn"><strong>Read this first.</strong> This databank contains only stocks that eventually made big moves,
so the absolute numbers below are optimistic — in live trading some entries will be in stocks that never go anywhere.
What IS robust: the <em>relative</em> ranking of stops, trails and filters, the shape of the R distribution, and the
win-rate / payoff structure. Treat the absolute expectancy as an upper bound; validate forward in the simulator.</div>

<h2>The strategy in one box</h2>
<div class="card">
  <div class="rule"><b>Universe.</b> Momentum names: 20-day ADR between {uni['adr'][0]}% and {uni['adr'][1]}%,
  ≥${uni['min_dollar_vol_m']}M average daily dollar volume.</div>
  <div class="rule"><b>Entry.</b> Buy the close of a signal day: a close above the prior 20d/50d high, or a ≥5% gap
  on ≥1.5× volume — subject to the filters below.</div>
  <div class="rule"><b>Filters.</b><ul>{''.join(f'<li>{esc(FILTER_DESC[k])}</li>' for k in top['kept_filters'])}</ul></div>
  <div class="rule"><b>Initial stop.</b> {esc(STOP_DESC[top['stop']])} (<span class="mono">{top['stop']}</span>).</div>
  <div class="rule"><b>Exit / trail.</b> {esc(EXIT_DESC[top['exit']])} (<span class="mono">{top['exit']}</span>).</div>
  <div class="rule"><b>Sizing.</b> Risk 0.5–1.0% of equity per trade: shares = (equity × risk%) ÷ (entry − stop).
  Max total open risk 6R (Behavior Contract heat cap). When SPY is below its 50SMA, valid signals still get taken —
  the data says they perform — but at half size: a weak tape produces fewer real signals and the winners-only bank
  cannot price that scarcity.</div>
</div>

<div class="note"><b>Live translation of the two "freshness" filters.</b> In this study, "<i>&lt;50% above the move low</i>"
and "<i>1st–3rd signal of the move</i>" are measured from the move's actual low — hindsight a live trader doesn't have.
The live-tradable proxies: measure extension from the <b>13-week (63-day) low</b> (price less than ~50% above it), and
count <b>breakout signals since that low</b> (skip the 4th+). Both are computable on any chart on any day, and both
encode the same idea the data rewarded: trade the move while it's young; late signals are adds on existing positions,
never cold entries — exactly your ADD-vs-cold-entry rule.</div>

<h3>The three flavors (same entries, different temperament)</h3>
<ul>
  <li><b>Core swing (headline):</b> stop at the entry-day low, exit on a 50SMA close-below. Tightest risk per share,
      best R per month. The median trade is still a loss — the tail pays.</li>
  <li><b>Wider stop:</b> 1×ATR initial stop for gappy/extended names where the day low is too tight to be real.
      Lower R per trade but fewer gap-through stop fills.</li>
  <li><b>Position trade:</b> capped swing-low stop (≤1.5×ATR) with the same 50SMA exit. Win rate rises above 50%
      and the ride is calmer; R efficiency is lower. Use for highest-conviction, earliest entries.</li>
</ul>

<table>{STAT_HEAD}
{stat_row('Strategy (filtered, in-sample)', fstats)}
{stat_row('Same policy, no filters', top['base'])}
{alt_rows}
</table>

<h2>How the policy grid ranked</h2>
<p>Every entry event was simulated under 4 initial stops × 7 exit rules. Highlighted rows fall inside your
25–45% win-rate band; ranking is by winsorized expectancy (avg R with the top 1% of outliers capped) so a few
moonshots can't carry a bad rule.</p>
<table><tr><th>stop</th><th>exit</th><th>trades</th><th>win</th><th>avg R</th><th>avg R (w99)</th>
<th>med R</th><th>p90 R</th><th>≥5R</th><th>days</th><th>R/30d</th><th>band</th></tr>
{league_rows}</table>

<h2>What each filter is worth</h2>
<p>Marginal effect of each pre-registered filter on the chosen policy
(<span class="mono">{top['stop']}/{top['exit']}</span>). Edge = winsorized avg R (pass) − (fail).</p>
<table><tr><th>filter</th><th>n pass</th><th>win</th><th>avg R w99</th><th>n fail</th><th>avg R w99 (fail)</th>
<th>edge</th><th></th></tr>
{marg_rows}</table>

<h2>Robustness</h2>
<table>{STAT_HEAD}
{stat_row('Odd years', split['odd_years'])}
{stat_row('Even years', split['even_years'])}
{stat_row('2000–2012', split['2000-2012'])}
{stat_row('2013–2026', split['2013-2026'])}
{stat_row('SPY > 50SMA', regime['spy_above_50sma'])}
{stat_row('SPY < 50SMA', regime['spy_below_50sma'])}
</table>
<h3>Per-year (filtered strategy)</h3>
<table><tr><th>year</th><th>trades</th><th>win</th><th>avg R</th></tr>{yr_rows}</table>

<h2>Exit rule by market regime</h2>
<p>Same filtered entries, different exits, split by tape:</p>
<table><tr><th>exit</th><th colspan="3">SPY &gt; 50SMA (n / win / avg R w99)</th>
<th colspan="3">SPY &lt; 50SMA</th></tr>
{exit_regime_rows}</table>

{superalt_section}
{consistency_section}

<h2>Operating manual</h2>
<ul>
  <li><b>Scan:</b> universe filter daily; flag 20d/50d-high crosses and qualifying gaps at the close.</li>
  <li><b>Decide:</b> apply the entry filters; if it passes, the trade is taken at/near the close. No filter, no trade —
      discretion only gets a veto, never an un-veto.</li>
  <li><b>Size:</b> from the stop distance, not conviction. 0.5R while validating, 1R once forward results match.</li>
  <li><b>Manage:</b> nothing until the exit rule fires. The win rate is supposed to be ~1-in-3 —
      four stops in a row is arithmetic, not failure.</li>
  <li><b>Review:</b> log every trade in the PortSim review flywheel; compare your realized R distribution to the tables
      above. Divergence = execution leak or regime shift, in that order of likelihood.</li>
</ul>

<div class="note"><b>Next upgrades.</b> (1) Control-group validation — simulate the same signals on non-mover
ticker-dates to price in the false-positive rate the winners-only bank hides. (2) Wire
<span class="mono">strategy_spec.json</span> into the app's sim entry flow as a live gate score.
(3) Pullback-entry variant (first 10/20EMA touch after a confirmed breakout) — not in this event set yet.</div>

<div class="sub">Reproduce: <span class="mono">python3 -m evaluation.run_trade_sim && python3 -m evaluation.strategy_opt
&& python3 -m evaluation.strategy_report</span></div>
</div></body></html>"""

    out = os.path.join(OUT_DIR, "strategy_playbook.html")
    with open(out, "w") as fh:
        fh.write(html_doc)
    print(f"wrote {out}")
    print(f"wrote {os.path.join(OUT_DIR, 'strategy_spec.json')}")


if __name__ == "__main__":
    main()
