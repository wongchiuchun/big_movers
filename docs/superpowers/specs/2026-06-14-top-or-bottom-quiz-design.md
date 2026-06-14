# Top-or-Bottom Quiz — Design Spec

**Date:** 2026-06-14
**Status:** Approved, pending implementation plan
**Location:** New `Quiz` mode inside `Big_movers.html`

## 1. Purpose

An empirical drill that demonstrates the user is bad at calling tops and bottoms
by gut feel — in order to build trust in mechanical EMA-stop exits over discretionary
"I think this is the top" decisions.

The drill shows an extended price move cut at a "decision bar," asks the user how much
of the move is left, reveals what actually happened, and scores the call. After ~10–20
rounds, it shows that the user's accuracy is no better than a dumb "it's still going"
baseline.

The point being proven: much of the extension visible in the early phase of a move is
just the start of a larger rally (or decline). You cannot reliably distinguish "the top
is in" from "this is just getting started" — so trust the EMA stop, not the gut.

## 2. Placement & Reuse

New `Quiz` mode inside `Big_movers.html` (~29k-line single-file webapp), launched via a
button alongside the existing Blind / Individual / Portfolio sim controls.

Reuses existing infrastructure:
- **Chart renderer** (Lightweight Charts) and the `/api/ohlcv?symbol=X` data loader.
- **SimBlind's masking pattern** (`Big_movers.html` ~line 13263): anonymized symbol
  (`🕶 BLIND TICKER`), `Day −N → Day +N` date axis, reveal-on-demand button.
- **localStorage persistence** pattern (as `SimSaved` does) for session history.

New server addition:
- A trivial `/api/stock-list` endpoint in `Big_movers_server.py` that returns
  `os.listdir(collected_stocks)` (the ~984 ticker filenames), so sampling covers the
  full universe, not just the big-mover catalogue (`allRows`).

## 3. Components

New `Quiz.*` namespace, mirroring the structure of `PortSim` / `SimBlind`.

| Component | Kind | Responsibility |
|---|---|---|
| `Quiz.Pool` | pure, unit-tested | Pick a random ticker, scan its full history for qualifying "extended" decision bars, return `{symbol, decisionIdx, direction}`. Retry another ticker if none qualify. |
| `Quiz.Grade` | pure, unit-tested | Map post-decision price action into the true 5-way bucket; score the user's call. |
| `Quiz.Ctrl` | stateful | Round lifecycle and session state (current round index, per-round history array). |
| `Quiz.UI` | DOM | Question panel (5 answer buttons), reveal overlay, end-of-session summary. |
| `Quiz.Stats` | pure, unit-tested | Session aggregation + baseline comparison; persist to localStorage. |

Each pure component must be understandable and testable without the DOM or chart.

## 4. Selection Algorithm (`Quiz.Pool`) — the honesty engine

For a randomly chosen ticker's full daily history, a bar `i` qualifies as a **decision
bar** when ALL of the following hold:

- **Enough context behind:** at least ~120 bars before `i` (so the run is visible on the chart).
- **Enough future to grade:** at least `H` bars after `i` (lookforward window, default 21
  trading days / ~1 month).
- **Currently extended:** over a trailing lookback `L` (default ~63 bars / 3 months),
  price has run at least `RUN_THRESHOLD` (default 35%, configurable) from the swing low → `i`
  close (UP direction) or swing high → `i` close (DOWN direction), AND `i` sits near that
  window's extreme (so the move is genuinely extended *at the decision bar*, not already
  collapsed).
- **Liquidity filter:** skip sub-dollar prices and very thin bars to avoid junk data.

Collect all qualifying `i` for that ticker, then pick one at random. If a chosen ticker
yields no qualifying bars, draw another ticker (bounded retry count).

**Why this is honest:** this surfaces both runs that kept going AND runs that topped out,
because every multi-year history contains many 35% runs, most of which reversed. Drawing
from the full history (not from the curated `low_date → high_date` catalogue entries)
avoids the selection bias that would rig the quiz toward "it kept going."

Tunable constants (single config object):
- `LOOKFORWARD_H = 21`
- `LOOKBACK_L = 63`
- `RUN_THRESHOLD = 0.35`
- `MIN_CONTEXT_BARS = 120`
- `MIN_PRICE = 1.0` (liquidity floor; exact rule TBD-free — see plan)

## 5. The Question (5-way, direction told)

The user is told the current move direction and asked **how much of the move is left**,
on one scale (direction-agnostic phrasing, since direction is given):

1. **It's over** — the high/low is in now (reverses from here)
2. **Almost over** — one more small leg
3. **Roughly halfway**
4. **Early** — most of the move is still ahead
5. **Just getting started**

## 6. Grading (`Quiz.Grade`, fixed-window)

Over the lookforward window `H`, find the extreme in the move's direction (e.g. `FwdMax`
for an UP move; `FwdMin` for DOWN). Compute the fraction of the move still ahead at the
decision bar:

```
priorRun        = |decisionClose - swingStartPrice|     // run already completed at decision bar
futureExtension = |forwardExtreme - decisionClose|      // further extension within window H
remaining       = futureExtension / (priorRun + futureExtension)
```

Bucket `remaining` into the same 5 labels (illustrative thresholds, all tunable):

| `remaining` | True bucket |
|---|---|
| ~0–5% | It's over |
| 5–20% | Almost over |
| 20–45% | Roughly halfway |
| 45–65% | Early |
| >65% | Just getting started |

**Scoring:** exact bucket = full credit; adjacent bucket = half credit; otherwise zero.

EMA lines (already part of the chart) stay visible so on reveal the user *sees* where the
trend actually broke — reinforcing the EMA-stop lesson without complicating the numeric score.

## 7. Reveal

After the user answers:
- Unmask the next `H` bars on the chart.
- Mark the actual forward extreme.
- Show the true bucket vs. the user's call and the credit earned.
- A "Reveal ticker" button unmasks the identity (symbol / year / dates), as in SimBlind.

## 8. Session & Payoff (`Quiz.Stats`)

- Configurable round count: default 10, option for 20.
- Per round, record: `{symbol, decisionDate, direction, predictedBucket, trueBucket, credit}`.
- End-of-session summary headline:
  - **User accuracy** (exact-match rate AND within-1 rate) shown next to two baselines
    computed on the *same* set of questions:
    - **"always say 'just getting started'"** (most-remaining)
    - **random** (uniform 1/5)
  - The punchline lands when the user sees they are no better than (or worse than) always
    assuming the move continues.
  - A one-line bias readout, e.g. *"You called 'it's over' 7×; it was actually over 1×.
    You call tops ~6× too early."*
- Session saved to localStorage (keyed history) so the user can track improvement over time.

## 9. Testing

- `Quiz.Pool`, `Quiz.Grade`, `Quiz.Stats` are pure functions → unit tests in `tests/`,
  following the existing `tests/sim_shorts.test.cjs` pattern (Node `.cjs` harness).
- Pool tests: synthetic bar series with a known 35% run that (a) continues and (b) reverses,
  assert qualification and direction.
- Grade tests: known forward windows map to the expected bucket; scoring (exact/adjacent/zero)
  is correct.
- Stats tests: baseline computation and accuracy aggregation on a fixed round set.
- UI verified via the `verify-ui` skill (Playwright) after `npm run build` / load, driving a
  full round (question → answer → reveal → summary) and reading the browser console.

## 10. Decisions Locked During Brainstorm

- Placement: new mode in `Big_movers.html` (reuse chart + masking).
- Sampling: algorithmic scan of all ~984 stocks (honest, unbiased) — NOT the curated catalogue.
- Answer schema: 5-way "how much is left" scale, direction told.
- Grading: fixed lookforward window, measure forward extreme.
- Payoff: accuracy vs. dumb baselines (always-continue, random).
- Defaults: `LOOKFORWARD_H = 21`, `LOOKBACK_L = 63`, `RUN_THRESHOLD = 0.35` (all tunable).
