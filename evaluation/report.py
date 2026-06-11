"""Render the myth-testing study into a standalone light-theme HTML report
plus calibrated_rules.json for the future live setup evaluator.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.report
"""
from __future__ import annotations

import html
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evaluation.rules import run_all

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")

VERDICT_COLORS = {
    "CONFIRMED": ("#0a7a45", "#e6f5ec"),
    "PARTIAL": ("#9a6b00", "#fdf3dd"),
    "BUSTED": ("#b3261e", "#fceeed"),
    "UNTESTABLE": ("#5b5f6b", "#eef0f3"),
    "ERROR": ("#b3261e", "#fceeed"),
}


def esc(s) -> str:
    return html.escape(str(s))


def render_stats(stats: dict) -> str:
    """Generic renderer: dict-of-dicts → table; scalars → key/value rows."""
    parts = []
    scalars = {k: v for k, v in stats.items() if not isinstance(v, dict)}
    if scalars:
        rows = "".join(
            f"<tr><td class='k'>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in scalars.items()
        )
        parts.append(f"<table class='kv'>{rows}</table>")
    for k, v in stats.items():
        if not isinstance(v, dict):
            continue
        inner_dicts = {ik: iv for ik, iv in v.items() if isinstance(iv, dict)}
        inner_scalars = {ik: iv for ik, iv in v.items() if not isinstance(iv, dict)}
        if inner_dicts:
            cols: list[str] = []
            for iv in inner_dicts.values():
                for c in iv:
                    if c not in cols:
                        cols.append(c)
            head = "<tr><th>" + esc(k) + "</th>" + "".join(f"<th>{esc(c)}</th>" for c in cols) + "</tr>"
            body = "".join(
                "<tr><td class='k'>" + esc(b) + "</td>"
                + "".join(f"<td>{esc(iv.get(c, '—') if iv.get(c) is not None else '—')}</td>" for c in cols)
                + "</tr>"
                for b, iv in inner_dicts.items()
            )
            extra = ""
            if inner_scalars:
                extra = "".join(
                    f"<tr><td class='k'>{esc(ik)}</td><td colspan='{len(cols)}'>{esc(iv)}</td></tr>"
                    for ik, iv in inner_scalars.items()
                )
            parts.append(f"<table class='grid'>{head}{body}{extra}</table>")
        else:
            rows = "".join(
                f"<tr><td class='k'>{esc(ik)}</td><td>{esc(iv if iv is not None else '—')}</td></tr>"
                for ik, iv in v.items()
            )
            parts.append(f"<div class='subhead'>{esc(k)}</div><table class='kv'>{rows}</table>")
    return "".join(parts)


def calibrated_rules(results: list[dict], moves: pd.DataFrame) -> dict:
    """Data-backed thresholds for the phase-2 live evaluator."""
    lab = moves[moves["label"].notna()]
    trad = lab[lab["label"] == "tradable"]
    not_ = lab[lab["label"] == "not"]

    def q(df, col, p):
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        return round(float(s.quantile(p)), 2) if len(s) else None

    return {
        "version": 1,
        "generated": time.strftime("%Y-%m-%d"),
        "source": "evaluation myth-testing study v1 — see myth_report.html",
        "caveat": "Calibrated on winners only (n labeled = %d). Holdability thresholds are robust; predictive power vs non-winners is untested." % len(lab),
        "verdicts": {r["id"]: r["verdict"] for r in results},
        "holdability_gates": {
            "ema10_adherence_move": {
                "skip_below": 65, "promising_above": 75,
                "tradable_median": q(trad, "ema10_adh", 0.5),
                "tradable_p25": q(trad, "ema10_adh", 0.25),
                "not_median": q(not_, "ema10_adh", 0.5),
            },
            "sma50_touches_move": {
                "skip_above": 10, "ideal_max": 2,
                "tradable_median": q(trad, "sma50_touches", 0.5),
                "not_median": q(not_, "sma50_touches", 0.5),
            },
            "adr_pct": {
                "comfortable_below": 5.5, "hard_above": 7,
                "tradable_median": q(trad, "adr_mean", 0.5),
                "not_median": q(not_, "adr_mean", 0.5),
            },
        },
        "entry_filters_within_winners": {
            "gap_close_in_range": {"clean_above": 75, "trap_below": 50},
            "ema_stack_bull_required": True,
            "breakout_rel_vol20": {"note": "see Q1 verdict — surge size vs follow-through"},
            "prior_gain_3m": {"note": "see Q2 verdict"},
            "pct_off_52wk_high": {"note": "see M2 verdict"},
        },
    }


def build_html(results: list[dict], moves: pd.DataFrame, events: pd.DataFrame, log: dict) -> str:
    n_lab = int(moves["label"].notna().sum())
    lab_counts = moves[moves["label"].notna()]["label"].value_counts().to_dict()
    ev_counts = events["event_type"].value_counts().to_dict()

    summary_rows = "".join(
        f"<tr><td class='mono'>{esc(r['id'])}</td><td>{esc(r['claim'])}</td>"
        f"<td>{esc(r['source'])}</td><td>{esc(r['class'])}</td>"
        f"<td><span class='badge' style='color:{VERDICT_COLORS[r['verdict']][0]};background:{VERDICT_COLORS[r['verdict']][1]}'>"
        f"{esc(r['verdict'])}</span></td></tr>"
        for r in results
    )

    cards = []
    for r in results:
        fg, bg = VERDICT_COLORS[r["verdict"]]
        cards.append(f"""
<section class="card" id="{esc(r['id'])}">
  <div class="card-head">
    <span class="rule-id mono">{esc(r['id'])}</span>
    <span class="badge" style="color:{fg};background:{bg}">{esc(r['verdict'])}</span>
    <span class="klass">{esc(r['class'])}</span>
  </div>
  <h3>{esc(r['claim'])}</h3>
  <div class="source">{esc(r['source'])}</div>
  <p class="finding">{esc(r['finding'])}</p>
  <details><summary>Underlying numbers</summary>{render_stats(r['stats'])}</details>
</section>""")

    confirmed = [r["id"] for r in results if r["verdict"] == "CONFIRMED"]
    busted = [r["id"] for r in results if r["verdict"] == "BUSTED"]
    partial = [r["id"] for r in results if r["verdict"] == "PARTIAL"]

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Big Movers — Myth-Testing Study</title>
<style>
  :root {{
    --ink:#1a1c20; --ink2:#4a4e58; --muted:#7a7e8a; --line:#e4e2dc;
    --paper:#fbfaf7; --card:#ffffff; --accent:#8a6d3b;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
        font:15px/1.55 "Plus Jakarta Sans","Segoe UI",system-ui,sans-serif; }}
  .wrap {{ max-width:980px; margin:0 auto; padding:48px 28px 80px; }}
  h1 {{ font-family:Fraunces,Georgia,serif; font-weight:600; font-size:34px; margin:0 0 6px; }}
  h2 {{ font-family:Fraunces,Georgia,serif; font-weight:600; font-size:23px; margin:42px 0 12px; }}
  h3 {{ font-size:17px; margin:10px 0 2px; }}
  .sub {{ color:var(--muted); margin-bottom:28px; }}
  .mono {{ font-family:"JetBrains Mono",ui-monospace,monospace; }}
  .meta-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:20px 0; }}
  .meta {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .meta .v {{ font-size:22px; font-weight:700; font-family:"JetBrains Mono",monospace; }}
  .meta .l {{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }}
  .note {{ background:#fdf6e8; border:1px solid #ecdcb8; border-radius:10px; padding:14px 18px; margin:18px 0; font-size:14px; }}
  table {{ border-collapse:collapse; width:100%; margin:10px 0 18px; font-size:13.5px; }}
  th,td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ font-size:12px; text-transform:uppercase; letter-spacing:.03em; color:var(--muted); }}
  td.k {{ color:var(--ink2); font-weight:600; white-space:nowrap; }}
  .badge {{ display:inline-block; padding:3px 10px; border-radius:99px; font-size:12px; font-weight:700;
           letter-spacing:.04em; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:22px 26px; margin:18px 0; }}
  .card-head {{ display:flex; gap:10px; align-items:center; }}
  .rule-id {{ font-weight:700; color:var(--accent); }}
  .klass {{ margin-left:auto; font-size:12px; color:var(--muted); }}
  .source {{ font-size:13px; color:var(--muted); margin-bottom:8px; }}
  .finding {{ margin:10px 0 8px; }}
  details summary {{ cursor:pointer; color:var(--accent); font-size:13.5px; margin:6px 0; }}
  .grid td, .grid th {{ font-family:"JetBrains Mono",ui-monospace,monospace; font-size:12.5px; }}
  .grid td.k {{ font-family:"Plus Jakarta Sans",sans-serif; }}
  .subhead {{ font-size:13px; font-weight:700; color:var(--ink2); margin-top:12px; }}
  ul {{ padding-left:22px; }}
  li {{ margin:6px 0; }}
  @media print {{ .card {{ break-inside:avoid; }} }}
</style></head><body><div class="wrap">

<h1>Big Movers — Myth-Testing Study</h1>
<div class="sub">Claimed trading principles, cross-referenced against {len(moves):,} historical big-mover moves
(2000–2026) · generated {esc(log.get('generated', ''))}</div>

<div class="meta-grid">
  <div class="meta"><div class="v">{len(moves):,}</div><div class="l">moves analyzed</div></div>
  <div class="meta"><div class="v">{len(events):,}</div><div class="l">entry events</div></div>
  <div class="meta"><div class="v">{n_lab}</div><div class="l">human-labeled moves</div></div>
  <div class="meta"><div class="v">{len(confirmed)} / {len(partial)} / {len(busted)}</div><div class="l">confirmed / partial / busted</div></div>
</div>

<div class="note"><strong>How to read this.</strong> Events are deterministic — move starts, 20d/50d-high
breakout crosses, and ≥5% gaps on ≥1.5× volume — so every number is reproducible; there is no fuzzy
"base detection" anywhere. Trailing features use only data available at the event close. Forward windows
measure what happened next. <strong>Lateness control:</strong> in a winners-only bank, conditions that only exist
early in a move (weak RS, broken EMA stack, far from highs) mechanically inherit the huge remaining upside of early
entries — naive comparisons make textbook filters look terrible. Every entry-filter rule is therefore tested twice:
on all events AND on the early third of each move, and risk (2R-before-stop rate, adverse excursion) is weighed
separately from raw return. <strong>One honest limit:</strong> this bank contains only winners. It can tell you
what big winners look like, and which entry conditions led to better follow-through <em>within</em> winners — it
cannot yet tell you whether a condition separates winners from losers (that needs a control group; see X1).
Label counts: {esc(lab_counts)}. Events: {esc(ev_counts)}.</div>

<h2>Verdict summary</h2>
<table>
<tr><th>ID</th><th>Claim</th><th>Source</th><th>Test class</th><th>Verdict</th></tr>
{summary_rows}
</table>

<h2>Rule-by-rule findings</h2>
{''.join(cards)}

<h2>What to do with this</h2>
<ul>
  <li><strong>In the study tool:</strong> when reviewing a chart, score it against the holdability gates
      (10EMA adherence, 50SMA touches, ADR band) — the labeled-subset medians above are your calibration anchors.</li>
  <li><strong>In the simulator:</strong> before entering, check the within-winner entry filters that survived
      testing (close-in-range on gaps, EMA stack, distance from 52wk high, prior 3m trend). The busted rules are
      permission to stop worrying about those criteria.</li>
  <li><strong>Phase 2 — control group:</strong> sample breakout events from random non-mover ticker-dates (or failed
      breakouts in these same tickers outside move windows) to upgrade the within-winner findings to true
      predictive tests. This is the single biggest upgrade available.</li>
  <li><strong>Phase 3 — live evaluator:</strong> wire <span class="mono">calibrated_rules.json</span> into the app so any
      ticker+date gets a point-in-time gate score at sim entry, then compare scores to your sim outcomes.</li>
</ul>

<div class="sub">Files: <span class="mono">evaluation/output/moves.csv</span> (per-move metrics + labels),
<span class="mono">events.csv</span> (per-event features + outcomes),
<span class="mono">calibrated_rules.json</span> (machine-readable thresholds).
Reproduce: <span class="mono">python3 -m evaluation.run_study && python3 -m evaluation.report</span></div>

</div></body></html>"""


def main() -> None:
    moves = pd.read_csv(os.path.join(OUT_DIR, "moves.csv"))
    events = pd.read_csv(os.path.join(OUT_DIR, "events.csv"))
    with open(os.path.join(OUT_DIR, "run_log.json")) as fh:
        log = json.load(fh)

    results = run_all(moves, events)
    html_doc = build_html(results, moves, events, log)
    out_html = os.path.join(OUT_DIR, "myth_report.html")
    with open(out_html, "w") as fh:
        fh.write(html_doc)

    cal = calibrated_rules(results, moves)
    with open(os.path.join(OUT_DIR, "calibrated_rules.json"), "w") as fh:
        json.dump(cal, fh, indent=2)

    with open(os.path.join(OUT_DIR, "rule_results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=str)

    print(f"wrote {out_html}")
    for r in results:
        print(f"  {r['id']:>3} {r['verdict']:<11} {r['claim'][:70]}")


if __name__ == "__main__":
    main()
