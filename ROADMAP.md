# Big Movers — Roadmap & Strategic Notes

> Living document. Last updated 2026-04-29.
>
> This is the **strategic** roadmap — vision, web-deployment thinking, and feature
> ambitions beyond the immediate next-step. For session-level work-in-progress
> see `NEXT_STEPS.md` and `SESSION_CONTEXT.md`. For build plans, see
> `~/.claude/plans/`.

## Vision

A **trader's training simulator**, not a toy. The fundamental loop is:

1. **Review** — pick a historical setup; study how the move actually played out.
2. **Simulate** — walk through it day-by-day, real money on the line, real stops, real psychology.
3. **Reflect** — what went right, what went wrong, what character changes did I miss.
4. **Build** — add features that surface insights or remove friction in the loop.

The goal is to make me (and eventually other traders) better at swing trading by repeatedly rehearsing decisions on real historical data — not to be a backtester, an analytics platform, or a research tool. Every feature should either tighten the loop or sharpen the simulation realism.

What this is **not**:
- A backtester (no parameter sweeps, no "find me the best stop %")
- A scanner (no live signal generation)
- A broker integration (no real orders)
- A toy or random walk-through

## Where it stands today (April 2026)

- ~929 tickers in `collected_stocks/`, ~141 MB
- Single-ticker simulator with editable stops, multi-leg re-entry, R-stars, MFE/MAE, P&L curve, CSV export
- Portfolio simulator: 4–10 concurrent positions, cash budget, SPX/NDQ index strip, mid-sim entries, stop-out re-entry, force-close on end date, save/load reviews, view-only saved-review mode, full PDF export with charts as PNG
- Drawing tools, per-move metadata (rating/direction/notes/tags), saved filter views
- AI-generated MA overlays + ML SuperTrend + setup classifier (precomputed)
- Backend: Flask, ~1000 lines, stdlib only, mostly file I/O

The architecture turned out to be sound: **all the heavy compute (sim engine, charts, drawings) is browser-side JavaScript.** Python just serves files and parses CSVs. This shapes most of the decisions below.

---

## Going Web — Cost / Benefit (the question we evaluated)

### Headline finding

This codebase is **architecturally already web-ready**. The simulation isn't Python-bound — it's JS in the browser. The Flask backend is a thin file server (and a Twelve Data API proxy). It would deploy as-is to any Python host with no rewrite.

### What's hard isn't technical, it's running-a-service work

| Bucket | Effort | Cost |
|---|---|---|
| Containerize Flask + push to Fly.io / Railway | <1 day | $5–10 / mo |
| Add basic-auth password (single-user) | 30 min | $0 |
| Persistent volume for `collected_stocks/` | trivial | included |
| Migrate `drawings.json` / `metadata.json` to per-user DB rows (Postgres or SQLite-on-Litestream) | ~2 days | +$10 / mo if managed |
| Real auth + per-user data isolation | ~1 week | included |
| Multi-tenant + monitoring + backups + cert renewal | ~2 weeks + ongoing | $20–50 / mo |

The ongoing costs (monitoring, security patches, "the app is down at 2am" notifications) are usually under-estimated. A local app is "done"; a web service is "ongoing."

### Compute realism

Per request the server does CSV parse + JSON serialize: <100ms typical. Sim runs in browser, so server load is just file I/O. Twelve Data API calls would need rate-limiting at scale but are fine for personal use. **No GPU, no ML in the request path** — the AI features are pre-computed JSON files.

### Recommended phased approach (when the time comes)

1. **Now** — keep local. The double-click `Big Movers.app` already gets close to "real app" feel without any infra cost.
2. **When you want access from iPad / phone / another machine** — install Tailscale on your Mac and devices, hit the local server over Tailscale's network. ~15 min, $0/mo, no code changes. Or use a Cloudflare Tunnel if you want a public HTTPS URL with auth, again no rewrite.
3. **When you want to share specific reviews with peers** — add per-user namespacing to drawings/metadata/saved-reviews (~2 days), deploy to Fly.io, hardcode a small set of accounts. ~$10/mo. Multi-user but manual.
4. **When the system has demonstrated enough value to justify the running-a-service tax** — add real auth, multi-tenant data, public/private setup sharing, possibly community-tagged setup library. This is real ongoing work — only do it when the audience exists.

### Decision rule

Don't go web until there's a concrete user (yourself on iPad counts) demanding it. The Tailscale middle path solves 80% of "I want to access this elsewhere" without taking on service-running responsibility.

---

## Feature Roadmap (training-tool ambitions)

Organized by what would meaningfully improve the **training quality** of the loop — not by technical interest. The user explicitly called out stop strategies + trail strategies as next-up; those lead.

### A. Stop placement strategies (HIGH — user-flagged)

Today: user types a number. The simulator should help choose stops the way a real trader would.

Initial-stop options to surface in the entry modal:
- **% below entry** — the current default (long); add ATR / volatility-adjusted % presets
- **ATR-based** — `entry − k × ATR(14)` for `k ∈ {1, 1.5, 2}`. ATR is computable from the bars we already have.
- **Below recent swing low** — auto-detect the last N-bar low, anchor stop to it. We already detect swings (the AI swing arrows we just removed used this — keep the algorithm, drop the markers). Surface as "below 5-bar low" / "below 10-bar low".
- **Below recent base / pivot** — leverage the existing `pivot_date` and `base_start/end` from `ai_classifications.json`. "Stop at base low − $0.05" is a common Qullamaggie-style choice.
- **Hard-stop equivalent** — the user picks a price; this is what we have.

Implementation: a stop-strategy dropdown in the setup modal that pre-fills the stop value. User can still override.

### B. Trailing stop strategies (HIGH — user-flagged)

Today: stops only move when the user manually moves them. Add automated trail options that the user opts into per-leg.

Trail options:
- **% trail** — stop = `peak × (1 − k%)`, ratchets up only.
- **ATR trail (Chandelier)** — stop = `peak − k × ATR(14)`. Standard, well-tested.
- **MA trail** — stop = current bar's `10MA` (or `21EMA`, `50MA`). Common "ride it until 10MA breaks" exit.
- **Swing-low trail** — every new HH bumps stop to the most recent swing low. Less mechanical, more discretionary.
- **HHV-N trail** — stop = `low of last N bars`. Simple, robust.

Modal addition: "Trail strategy" dropdown on the entry modal + ability to switch strategies mid-trade via a new "Apply Trail" action. Engine-side, the Sim core already has `queueAction({type:'movestop'})` — a trail just queues movestops automatically each tick.

### C. Slippage realism (MEDIUM)

Today's stop fill: `Math.min(bar.open, stop.price)` (long). That's already realistic for gaps. But for **entry fills** we use the user-typed price as if it were guaranteed. Add:

- Configurable slippage % on entries (default 0; user can crank up to 0.25% for less liquid names)
- Volume-aware fill: if order size > 1% of avg daily volume, warn or split fills
- Optional "no fill above HoD" check: if the user wants to enter at $50 but the bar's high never touches $50, the fill should fail or fill at the close.

This dial nudges the simulator toward "what would have actually happened" rather than "ideal execution."

### D. Position sizing rules (MEDIUM)

Today: user picks a share count. Add presets:
- **Fixed risk %** — "risk 1% of equity per trade"; shares = `(equity × 0.01) / |entry − stop|`. The most common rule for swing traders.
- **Fixed dollar** — "always $5k per position"
- **ATR-normalized** — shares = `(equity × risk%) / (k × ATR)`

PortSim already has the cash budget; the position-sizer just needs to read it and propose shares.

### E. Hide-future-bars during sim (HIGH for realism)

This is the single biggest source of training contamination. Today the chart shows the entire window; the sim hand-walks day by day, but the user's eye sees the future. Real trading doesn't have this.

In sim mode, **clip the chart's right edge** to the current `playIdx`. Bars beyond the playhead are hidden. Indicators are computed only on visible history. The chart re-renders on each step.

This converts the experience from "watch the simulation" to "actually trade blind." Massive fidelity upgrade.

### F. Decision log (MEDIUM — fidelity upgrade)

Force a written thesis BEFORE entry. Modal field: "Why are you entering here?" (free text). Saved to the leg metadata. Revealed at exit alongside actual outcome.

After enough trades you build a corpus of your own pre-trade reasoning that you can grep through later. ("Show me every short I took on a high-volume reversal day." "Show me every entry where my thesis mentioned 'tight EMA action'.")

### G. Retrospective scoring (LOW — nice-to-have)

After sim ends, compute the **theoretical max** — buy-at-pivot, sell-at-high — and show user's outcome as a % of that. Quantifies "how much was on the table." Companion stat: **theoretical worst** (buy-at-high, sell-at-low). Position the user's run on that interval.

### H. Pattern library tagging (MEDIUM)

Already have user tags on metadata. Add a defined vocabulary aligned with how the user actually classifies setups: EP, U&R, climax-top, character-change, tight-EMA, base-on-base, etc. Then aggregate stats: "you're 11/13 on EPs, 2/8 on climax-tops" → directs future study.

### I. Spaced repetition prompts (LOW)

"You reviewed CLS 2024 6 weeks ago. Want to re-test?" Surfaces forgotten setups that were hard. Avoids the failure mode of "I review the same 5 favorites over and over."

### J. Random entry-day jitter (LOW)

Currently the sim starts at the low_date. To prevent muscle memory ("I know this one starts running on day 3"), add a random offset of ±5 trading days to the start.

---

## Multi-User / Open-System Path

Eventual ambition (no rush): an open system where any trader can input their own tickers, run sims, save reviews, and optionally share setups with the community.

What's needed:

1. **Per-user data isolation** — drawings, metadata, saved reviews keyed by user ID. The schema is already mostly there (`moveKey` is the per-move key); add a `userId` parent.
2. **Public/private setups** — each `result` row can be marked public or private. Public ones go into a community-discoverable feed.
3. **Anonymized aggregate stats** — "across 412 traders, EP setups have a 67% win rate" — a real differentiator vs solo study.
4. **Setup voting / curation** — users upvote setups worth studying. Top-of-the-week feed.
5. **Community-tagged patterns** — let traders agree on shared vocabulary (or fork their own).

The core data is **neutral** (just OHLCV) so there's no licensing hairball with sharing setups. The only sensitive data is trader-private notes / drawings, which stay per-user.

---

## Data Quality

- **Splits/dividends**: currently raw OHLCV from Twelve Data. A 2:1 split mid-window looks like a -50% move. Document this clearly; long-term consider a corporate-action overlay (Twelve Data has a `splits` endpoint).
- **Data redundancy**: single-source today (Twelve Data). For an open system, plan for Polygon or Tiingo as fallback.
- **Coverage gaps**: the random sim caught one — NDQ data wasn't available pre-2024. Solved by backfilling QQQ. Watch for similar gaps as the corpus grows.

---

## Code Health

The single 19k-line `Big_movers.html` works but is increasingly hard to navigate.

When the file hits ~25k lines or you onboard a second developer:
- Split into ES modules (`sim.js`, `portsim.js`, `charts.js`, `ui.js`)
- Add a minimal bundler (esbuild or Vite — single-command build)
- Keep the no-build-step ergonomic for hot iteration with a watcher

Don't do this preemptively. The single-file model has been a productivity multiplier; the cost shows up only when search becomes painful.

The 1035-line `Big_movers_server.py` is fine. Stays.

---

## Distribution — Middle Paths

For "I want this on my iPad too" without becoming a service operator:

1. **Tailscale** — install on Mac + iPad, address the Mac via its Tailscale name. Local server stays local; you reach it from any device on your tailnet.
2. **Cloudflare Tunnel** — exposes `localhost:5051` on a public HTTPS URL with optional access policy. Mac still has to be running.
3. **PWA conversion** — add a service worker + manifest, make the frontend installable. Combined with Tailscale, you'd get an iPad icon that opens the app like a native one.

These solve 80% of the "want it on the go" problem with effectively zero code changes.

---

## Suggestions Beyond What's Been Discussed

In the order I'd actually consider doing them:

1. **Hide future bars during sim (E above)** — single biggest realism fix. Half a day of work.
2. **Stop strategy presets (A above)** — start with ATR + swing-low + base-low, ship those three; add others later. Two days.
3. **Trail strategy presets (B above)** — start with % trail, ATR trail, 10MA trail. Two days.
4. **Position sizing rules (D above)** — a "1% risk" preset would be used immediately. Half a day.
5. **Pattern library tagging (H above)** — leverage existing tag infra; mostly a vocabulary + reporting addition. One day.
6. **Decision log (F above)** — small change; probably the highest training-quality return relative to effort.

Things I would **not** prioritize:
- Going web (not yet — Tailscale is the answer for now)
- Splitting the HTML file (not yet — it works)
- Real-time data (this is a study tool for historical setups; live data is out of scope)
- Backtesting / parameter sweeps (out of scope, by definition)

---

## How to Update This Doc

When something on the roadmap ships, move it to a "Done" section at the bottom (or delete it — git remembers). When something new comes up that's strategic enough to belong here, add it. Keep this doc tight; let `NEXT_STEPS.md` carry the day-to-day.
