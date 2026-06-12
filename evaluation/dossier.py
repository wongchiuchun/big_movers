"""Consolidated read-start-to-end dossier — the single document that ties every
phase of the big_movers strategy work together.

Pulls live numbers from the result JSONs where possible and weaves them into a
narrative: the goal, the journey (what we tried / found / verdict per phase),
what works vs what doesn't, the current locked strategy, honest limits, and the
review checklist the user needs to action next. Sticky sidebar = contents +
glossary so nothing has to be scrolled back to.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.dossier
"""
from __future__ import annotations

import json
import os

from evaluation.honest_report import GLOSSARY, build_glossary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evaluation", "output")


def load(f):
    try:
        return json.load(open(os.path.join(OUT, f)))
    except Exception:
        return {}


# ---------------- the journey: one card per phase ----------------
# status: done | superseded | pivot
PHASES = [
    {"n": 1, "title": "Myth-testing study", "status": "done",
     "tried": "Validated textbook momentum principles (Qullamaggie / Minervini / O'Neil) across all 1,529 winner moves — 24,580 point-in-time events, each anchored to a deterministic event + fixed window (the fix for the old 'fuzzy setup boundary' problem).",
     "found": "Your <i>holdability</i> gates held up (winners spend ~82% of days above the 10-EMA vs 64% for laggards; ~3 vs ~15 touches of the 50-SMA). But many famous rules <b>busted</b> on this data: volume-surge-as-prerequisite (only ~26% of winner breakouts were ≥2× volume), the Minervini trend template / 52-week-high / RS as <i>return</i> edges, and the SPY&gt;50SMA tape filter.",
     "verdict": "Most 'rules' are descriptions of winners, not predictors. Kept the holdability gates; discarded the rest as return edges. <span class='code'>myth_report.html</span>"},
    {"n": 2, "title": "Strategy v1 — the policy grid", "status": "superseded",
     "tried": "Simulated 396,732 trades: 4 stops × 7 exits × 14,185 deduped entries, gap-aware fills, no lookahead. Searched for the best entry/stop/exit on the ADR 4–8% momentum universe.",
     "found": "Headline LOD/E50 (stop at entry-day low, exit on close below the 50-SMA) — in-sample ~44% win, ~4R winsorized, positive every year. Trailing the 50-SMA beat shorter EMAs; freshness filters (early + not-extended) dwarfed everything else.",
     "verdict": "Good <i>relative</i> rankings, but every absolute number was in-sample and winners-only — an optimistic ceiling. Superseded by the overfit-proofing in Phase 6. <span class='code'>strategy_playbook.html</span>"},
    {"n": 3, "title": "Consistency analysis", "status": "done",
     "tried": "You prioritise steadiness over peak R, so we compared 10 stop/exit books on year-to-year variance, worst year, drawdown and time-underwater.",
     "found": "The wide vol-scaled stop (swing-low capped at 1.5×ATR, 'SW10C') paired with the 50-SMA exit was the steadiest — yearly std ~2.3 vs ~8.1 for the raw headline, no losing year. The wide structural stop is the consistency ingredient.",
     "verdict": "Confirmed the structural stop as the consistency lever — carried straight into the final strategy. <span class='code'>consistency_results.json</span>"},
    {"n": 4, "title": "SuperAlt benchmark", "status": "done",
     "tried": "You asked whether our work beats AlgoAlpha's ML Adaptive SuperTrend (superalt.md). Ported it faithfully to Python and compared risk-normalised on the same data.",
     "found": "Ours ran ~2.6× the expectancy and ~3.7× the R/month; but on identical entries+stops the exit duel was a near-tie (our 50-SMA trail vs SuperAlt's flip). The whole gap is entry+stop — SuperAlt enters mid-trend with a wide ~3-ATR stop. Its genuine value is comfort (high win rate, positive median) and a regime/trail lens.",
     "verdict": "Ours is superior on expectancy; borrowed SuperAlt's lesson that a wide stop = comfort. <span class='code'>superalt_results.json</span>"},
    {"n": 5, "title": "PineScript indicator", "status": "done",
     "tried": "Turned the strategy into an on-chart TradingView indicator: BUY label with suggested stop, trend line, stop line, TRIM/EXIT labels, a live filter table, and alerts. Compiles clean (Pine v6).",
     "found": "It works on your charts and has reference value. You observed two real limits live: it can sit idle for a long time in a strong trend (the anti-chasing filter), and a first-entry shakeout can lock you out — which led to Phase 7.",
     "verdict": "Shipped and in use. <span class='code'>pinescript/big_mover_signals.pine</span>"},
    {"n": 6, "title": "Overfit-proofing — train/test + control group", "status": "pivot",
     "tried": "The big methodological reset. (a) Split the 949 tickers 50/50 by symbol; select on train, read the held-out test once. (b) Built a CONTROL group — the same signals firing on charts that did NOT become recorded movers (6,571 signals) — to expose survivorship.",
     "found": "The old 4-filter stack carried a <b>−36% overfit tax</b> (two of its four filters were noise that flip sign out-of-sample). Only TWO filters generalise — <b>enter early</b> and <b>not extended</b>, both about entry <i>timing</i>. And the punchline: <b>the entry signal has ≈0 standalone edge</b> — in the wild the average trade is roughly breakeven. The winners-set profit is survivorship.",
     "verdict": "Reframed the whole thing: this is a risk-management + right-tail machine, not a high-edge signal. The honest, locked strategy comes from here. <span class='code'>honest_findings.html</span>"},
    {"n": 7, "title": "Continuation (leg 2+) entries", "status": "done",
     "tried": "You flagged that the base-only entry misses the bulk of strong trends. Tested a continuation entry — a pullback that reclaims the 20-EMA inside an uptrend — at every extension band, on train / test / control.",
     "found": "Continuation entries stay positive out-of-sample at <i>every</i> extension (~1.0–1.3R), and their control behaviour is slightly <b>positive</b> — better than the base breakout. 90.5% of winning moves offered one; allowing them roughly <b>triples the R captured per move</b> and re-enters after a shakeout.",
     "verdict": "Worth it. Shipped as an OPTIONAL, off-by-default toggle in the indicator — your call whether to run it. <span class='code'>continuation_results.json</span>"},
]

WORKS = [
    ("Enter early + not extended", "The only two filters that survive out-of-sample. Both about entry timing. Edge +1.8 to +2.2R, holds train→test."),
    ("Structural swing-low stop", "Beats the entry-day-wick stop on win rate AND control behaviour. The consistency lever (Phase 3) and your contract's 'structural stop'."),
    ("3-bar shakeout hold", "Free improvement everywhere — stops a normal pullback knocking you out in the first 3 days."),
    ("Free roll (trim ½ at +2R → BE)", "Nearly halves yearly variance (0.49→0.29) for the same median return. The 'more consistent' you asked for."),
    ("50-MA trail for the runner", "Highest total R on real movers — lets the rare monster run."),
    ("Continuation (leg 2+) entries", "Positive at every extension, better-behaved on control than base breakouts; ~3× the R captured per move."),
]
FAILS = [
    ("Treating the signal as high-edge", "It isn't. Control expectancy ≈0. The edge is survivorship; profit comes from risk control + the right tail."),
    ("The old 4-filter stack", "−36% overfit tax; cir_gt75_gaps and tight_lt5 are noise that flip sign on test."),
    ("Regime / EMA-stack / near-high filters (as return edges)", "Can't be judged on winners-only data — they're about avoiding losers, so they only matter against the control group."),
    ("Entry-day-wick stop (LOD)", "More stop-outs, worse control behaviour. Your contract already says not to use it; the data agrees."),
    ("Volume-surge as a prerequisite", "Only ~26% of winner breakouts were ≥2× volume. Useful as a weak tilt, not a gate."),
    ("Expecting the database win rates live", "50–60% on winners-only ≈ ~30% in the wild. Plan for that."),
]

# Concrete decisions the user needs to make to advance — the review checklist.
CHECKLIST = [
    ("Pick your default mode", "Mode B (free roll, consistent, ~60% win, half the variance) vs Mode A (runner, max R, more give-back). Recommendation: B as default, A for A+ setups in strong tape. <b>Your call.</b>"),
    ("Decide on continuation entries", "Eyeball the optional 'Continuation (leg 2+)' toggle on VSH / RKLB / your own charts. If the leg-2/leg-3 signals look tradeable to you, we make them first-class (sizing, alerts, app integration). If they add too much noise/heat, we leave them off."),
    ("Sanity-check against your live trading", "Does the ~30% wild win-rate and 'right tail pays' framing match your actual results? If your real win rate is much higher, your discretion is adding edge the backtest can't see — worth quantifying."),
    ("Approve the control-group method", "The control is built from ex-monster tickers (trendier than reality), so it understates the true false-positive rate. Decide if that's good enough, or if we should build a random-S&P control for a stricter read."),
    ("Choose the next build", "Options: (a) random-universe control; (b) wire the two modes + continuation into the portfolio sim for real equity curves & drawdowns under position sizing; (c) a SPY-regime auto-switch between Mode A and B. Pick one and I'll do it."),
]

FILE_MAP = [
    ("THIS DOC", "BIG_MOVER_DOSSIER.html", "The consolidated read-through. Start here."),
    ("Findings (visual)", "honest_findings.html", "The out-of-sample + control results with the glossary sidebar. The data behind this dossier."),
    ("Reflection", "REFLECTION.md", "Why the old work was optimistic and the new protocol (train/test + control)."),
    ("Locked spec", "STRATEGY_FINAL.md", "The final entry/stop/trail/mode rules + the continuation verdict, in prose."),
    ("Chart tool", "pinescript/big_mover_signals.pine", "The TradingView indicator (Mode A/B, 3-bar hold, free roll, optional continuation). Compiles clean."),
    ("Pine guide", "pinescript/README.md", "How to load and use the indicator; SMA vs EMA; the honest caveat."),
    ("Earlier: myth study", "myth_report.html", "Phase 1 — which textbook rules are real vs descriptive."),
    ("Earlier: strategy v1", "strategy_playbook.html", "Phase 2 — the in-sample policy grid (superseded by the honest findings)."),
    ("Engines", "engine.py · run_engine.py · run_continuation.py · honest_eval.py · split.py", "The reproducible code: point-in-time engine, train/test split, control group, continuation test."),
]

STATUS_BADGE = {
    "done": ('done', '#1b7a35', '#e3f3e6'),
    "superseded": ('superseded', '#8a6d3b', '#f6edda'),
    "pivot": ('turning point', '#1c4f8a', '#e2ecf8'),
}

CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  background: #f7f6f3; color: #1c1c1e; margin: 0; padding: 32px 24px; line-height: 1.55; }
.wrap { max-width: 1200px; margin: 0 auto; }
.layout { display: grid; grid-template-columns: minmax(0,1fr) 320px; gap: 36px; align-items: start; }
h1 { font-size: 28px; margin: 0 0 4px; }
.sub { color: #6b6b70; margin: 0 0 20px; font-size: 14px; }
h2 { font-size: 19px; margin: 36px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #e2e0da; scroll-margin-top: 16px; }
p { margin: 10px 0; }
.card { background: #fff; border: 1px solid #e6e4de; border-radius: 10px; padding: 16px 18px; margin: 12px 0;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.big { font-size: 15px; }
.tldr { background: #eef6ee; border-left: 4px solid #2e7d32; border-radius: 6px; padding: 14px 18px; margin: 14px 0; font-size: 15px; }
.warn { background: #fdf3e7; border-left: 4px solid #c77700; border-radius: 6px; padding: 12px 16px; margin: 14px 0; font-size: 14px; }
.phase { background:#fff; border:1px solid #e6e4de; border-radius:10px; padding:14px 18px; margin:12px 0; box-shadow:0 1px 2px rgba(0,0,0,.03); }
.phase h3 { margin:0 0 8px; font-size:16px; display:flex; align-items:center; gap:10px; }
.phase .pn { background:#1c1c1e; color:#fff; font-size:12px; border-radius:50%; width:22px; height:22px; display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; }
.phase .line { margin:5px 0; font-size:13.5px; }
.phase .k { display:inline-block; min-width:62px; font-weight:700; color:#555; }
.badge { font-size:11px; font-weight:700; padding:1px 8px; border-radius:10px; margin-left:auto; }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.cols .card h4 { margin:0 0 6px; font-size:14px; }
.cols ul { margin:0; padding-left:18px; font-size:13px; } .cols li { margin:6px 0; }
.chk { counter-reset: c; list-style:none; padding:0; }
.chk li { background:#fff; border:1px solid #e6e4de; border-radius:8px; padding:12px 14px 12px 46px; margin:10px 0; position:relative; font-size:14px; }
.chk li::before { counter-increment:c; content:counter(c); position:absolute; left:12px; top:12px; background:#1c4f8a; color:#fff; width:24px; height:24px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; }
.chk b { color:#1c1c1e; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }
th, td { text-align: left; padding: 7px 9px; border-bottom: 1px solid #ececec; vertical-align: top; }
th { background: #f0efea; font-weight: 600; }
.mono, .code { font-family: 'SF Mono', Menlo, Consolas, monospace; }
.code { font-size: 11px; background:#eef0f3; color:#566; padding:1px 5px; border-radius:4px; }
small { color:#6b6b70; }
a { color:#1c4f8a; }
/* sticky sidebar: contents + glossary */
.aside { position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow-y:auto;
  background:#fff; border:1px solid #e6e4de; border-radius:10px; padding: 12px 14px 16px; box-shadow:0 1px 2px rgba(0,0,0,.03); }
.aside .gtitle { font-size:15px; font-weight:700; margin: 4px 0 6px; }
.toc { list-style:none; padding:0; margin:0 0 6px; font-size:13px; }
.toc li { margin:5px 0; } .toc a { text-decoration:none; }
.aside h3 { font-size: 11px; text-transform: uppercase; letter-spacing:.05em; color:#8a6d3b; margin:16px 0 4px; border-bottom:1px solid #efece4; padding-bottom:3px; }
.aside dl { margin:0; } .aside dt { font-weight:600; font-size:12.5px; margin-top:8px; }
.aside dd { margin:1px 0 0; font-size:12px; color:#4a4a4f; }
@media (max-width: 940px) { .layout { grid-template-columns:1fr; } .aside { position:static; max-height:none; } .cols { grid-template-columns:1fr; } }
"""


def main():
    he = load("honest_eval.json")
    en = load("engine_results.json")
    co = load("continuation_results.json")
    ns = en.get("n_signals", {})
    pm = co.get("per_move", {})

    # phase cards
    phase_html = ""
    for p in PHASES:
        lbl, fg, bg = STATUS_BADGE[p["status"]]
        phase_html += (
            f'<div class="phase" id="phase{p["n"]}"><h3><span class="pn">{p["n"]}</span>{p["title"]}'
            f'<span class="badge" style="color:{fg};background:{bg}">{lbl}</span></h3>'
            f'<div class="line"><span class="k">Tried</span>{p["tried"]}</div>'
            f'<div class="line"><span class="k">Found</span>{p["found"]}</div>'
            f'<div class="line"><span class="k">Verdict</span>{p["verdict"]}</div></div>')

    works = "".join(f"<li><b>{t}</b> — {d}</li>" for t, d in WORKS)
    fails = "".join(f"<li><b>{t}</b> — {d}</li>" for t, d in FAILS)
    chk = "".join(f"<li>{t}: {d}</li>" for t, d in CHECKLIST)
    files = "".join(f"<tr><td>{role}</td><td><span class='code'>{f}</span></td><td>{d}</td></tr>"
                    for role, f, d in FILE_MAP)

    toc = "".join(f'<li><a href="#phase{p["n"]}">{p["n"]}. {p["title"]}</a></li>' for p in PHASES)
    toc_full = (
        '<div class="gtitle">Contents</div><ul class="toc">'
        '<li><a href="#now">★ Where we are now</a></li>'
        '<li><a href="#goal">The goal</a></li>'
        '<li style="margin-top:6px;color:#8a6d3b;font-size:11px;text-transform:uppercase;letter-spacing:.05em">The journey</li>'
        f'{toc}'
        '<li style="margin-top:6px"><a href="#works">What works / what doesn\'t</a></li>'
        '<li><a href="#strategy">The locked strategy</a></li>'
        '<li><a href="#limits">Honest limits</a></li>'
        '<li><a href="#review">★ Your review checklist</a></li>'
        '<li><a href="#files">File map</a></li>'
        '</ul>')
    glossary = build_glossary()

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Big-Mover Momentum — Project Dossier</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>Big-Mover Momentum — Project Dossier</h1>
<p class="sub">Everything we've done, tried, kept and dropped — in one read. Built from the winners
databank ({1529:,} moves, 949 tickers). The sidebar holds the contents and a glossary that stays in view
as you scroll. Last updated this session.</p>

<div class="layout">
<div class="main">

<h2 id="now">★ Where we are now</h2>
<div class="tldr big"><b>One honest sentence:</b> we have a validated momentum framework whose entry signal
has <b>no standalone edge</b> (in the wild it's ~breakeven) — it makes money as a <b>risk-management +
right-tail machine</b>: cap every loser at ~1R, hold the rare monster, and (optionally) ride the later legs.
The rules survive a 50/50 train/test split and a {ns.get('control', 6571):,}-signal control group.</div>
<div class="card big">
<b>The locked strategy:</b> momentum universe (ADR 4–8%, liquid) · enter <b>early &amp; not extended</b> ·
<b>structural swing-low stop</b> · <b>3-bar shakeout hold</b> · then either <b>Mode B</b> (free roll —
trim ½ at +2R, steadier, default) or <b>Mode A</b> (hold to the 50-MA — max R). An <b>optional
continuation toggle</b> adds leg-2/leg-3 entries. Shipped as a clean-compiling TradingView indicator.<br><br>
<b>Expect live:</b> ~30% win rate (not the database's 50–60%), small positive per-trade expectancy carried
by the right tail. Size so a −1R loss ≈ 0.5–1% of equity.</div>

<h2 id="goal">The goal</h2>
<p>Build a momentum strategy from the big-winner databank that maximises return (not win rate; target a
high-20s–40% win band), with a defined entry, a portfolio-risk-based stop (1R), and a trail rule — possibly
regime-dependent. Critically: <b>robust, not overfit</b> — usable in real trading, not a hindsight curve-fit.
Take care of <i>every</i> part (entry, stop, trail), because the same setup traded with a different stop and
trail is a different strategy.</p>

<h2>The journey — what we tried, found, and decided</h2>
<p><small>Seven phases, in order. Each: what we <b>tried</b>, what we <b>found</b>, the <b>verdict</b>.</small></p>
{phase_html}

<h2 id="works">What works · what doesn't</h2>
<div class="cols">
<div class="card"><h4 style="color:#1b7a35">✓ What works (kept)</h4><ul>{works}</ul></div>
<div class="card"><h4 style="color:#b3261e">✗ What doesn't (dropped / corrected)</h4><ul>{fails}</ul></div>
</div>

<h2 id="strategy">The locked strategy, in full</h2>
<div class="card big">
<b>Universe</b> — ADR 4–8%, ≥$5M/day dollar volume.<br>
<b>Entry</b> — breakout (20/50-day high) or gap ≥5% on ≥1.5× volume, only if <b>early</b> (≤3 triggers off
the 63-day low) and <b>not extended</b> (&lt;50% above it).<br>
<b>Stop</b> — structural swing low (10-bar low, capped 1.5×ATR). This defines 1R.<br>
<b>Hold</b> — 3-bar shakeout guard: no trailing-MA exit in the first 3 closes.<br>
<b>Exit — Mode B (default, consistent)</b> — trim ½ at +2R, move stop to breakeven, trail the rest on the
50-MA. ~60% win, ~half the yearly variance.<br>
<b>Exit — Mode A (high conviction)</b> — no trim, hold to a close below the 50-MA. Highest total R.<br>
<b>Continuation (optional)</b> — also enter on a pullback that reclaims the 20-EMA inside an uptrend, at any
extension. Catches later legs and re-enters after a shakeout. Off by default.</div>

<h2 id="limits">Honest limits</h2>
<div class="warn"><ul style="margin:0;padding-left:18px">
<li>The control group is built from ex-monster tickers, so it's trendier than a random universe — it
<b>understates</b> the true false-positive rate. Directionally right, not a substitute for live forward testing.</li>
<li>Winners-only selection still inflates the absolute winner-side numbers; trust the <i>relative</i> rankings
and the control column, not the headline win rates.</li>
<li>Daily bars only. The portfolio-level risk overlays from your contract (2.5% cap, heat caps, circuit
breakers) are sizing rules layered on top — out of scope for the signal engine.</li>
<li>My backtest data ends ~Mar–Apr 2026, staler than your live TradingView charts, so a few of the explosive
legs you've seen are partly beyond the tested data (but structurally identical to tested moves).</li>
</ul></div>

<h2 id="review">★ Your review checklist — what I need from you to go to the next step</h2>
<ol class="chk">{chk}</ol>

<h2 id="files">File map — what each piece is</h2>
<table><tr><th>Role</th><th>File</th><th>What it is</th></tr>{files}</table>
<p class="sub">All committed to git. The two HTML reports and the Pine file are the user-facing pieces; the
Python modules reproduce every number.</p>

</div>
<aside class="aside">{toc_full}{glossary}</aside>
</div>
</div></body></html>"""

    path = os.path.join(OUT, "BIG_MOVER_DOSSIER.html")
    with open(path, "w") as fh:
        fh.write(html)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
