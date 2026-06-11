# Reflection: is the current strategy the best we can do?

> Written 2026-06-12, in response to the goal: *"recursively reflect on whether
> this is the best we could do… go beyond the references… take care of entry,
> stop, and trail… split the data so we don't overfit."*

Short answer: **no, and the old numbers were optimistic.** Here is the honest
accounting, what I changed, and what the data actually supports.

---

## 1. What was wrong with the old pipeline

The playbook reported a single in-sample strategy (`LOD/E50` + a 4-filter stack)
selected on the **entire** winners databank. Three structural problems:

### a) No held-out test set (the cardinal sin)
`strategy_opt.py` chose the policy and the filters by scanning all 1,530 moves,
then reported odd/even-year and early/late splits *after* the choice. Those
"robustness" splits were contaminated — they validated a decision that had
already seen them. **Every published number was an in-sample ceiling.**

### b) Winners-only survivorship
The databank contains *only* stocks that went on to gain 100%+. So a measured
"52% win rate" is conditional on *already knowing the stock became a monster*.
It says nothing about how often the same entry signal fires on a chart that then
fails — because those charts aren't in the set. **You cannot measure a false-
positive rate from winners alone**, which caps what any in-sample number means.

### c) The funnel was statistically fragile
ADR 4–8% **and** 4 stacked hard filters cut 396k simulated trades down to
**~120 entries per policy**. We were selecting a "best strategy" on ~120
examples. That is noise-fitting, not edge-finding.

---

## 2. The new protocol

1. **Deterministic split, chosen once** (`evaluation/split.py`):
   - **Primary — by symbol, 50/50** (crc32-hashed). A ticker is wholly in train
     or test, so a stock's idiosyncratic behaviour can't leak across the line.
     Answers the overfit question: *does the rule generalise to unseen tickers?*
   - **Secondary — by time** (≤2019 train, ≥2020 test). The stricter check:
     *does a rule fit on the past survive forward through unseen regimes?*
2. **Select on train, touch test once.** `evaluation/honest_eval.py` re-runs the
   whole selection on train only, then reports the locked choice on the held-out
   test and time splits.
3. **Add a control group** (`evaluation/control.py`): fire the same signals on
   the 984 `collected_stocks` tickers *outside* their recorded winning windows.
   These are "looked like a setup, wasn't a recorded monster" samples — the
   closest thing to false positives we can build without new data. This is the
   single biggest honesty upgrade: it lets the regime / trend / quality filters
   finally prove (or disprove) their worth, which winners-only data cannot.

---

## 3. What the honest re-run actually shows

Re-selecting on train and reading the held-out test (symbol split):

| filter | what it asks | edge train | edge test | verdict |
|---|---|---|---|---|
| `ordinal_le3` | enter early (≤3 triggers off the low) | **+2.32** | **+1.82** | **holds — strong** |
| `extension_lt50` | not >50% extended off the low | **+2.11** | **+2.19** | **holds — strong** |
| `relvol_ge15` | volume ≥1.5× | +0.38 | +0.43 | holds — weak |
| `cir_gt75_gaps` | gap closes in upper range | +0.34 | −0.11 | **flips — noise** |
| `tight_lt5` | tight 10-day range | +0.01 | +0.07 | inert |
| `spy_above_50` | SPY > 50SMA | −0.09 | +0.35 | flips (see below) |
| `stack_bull` | bullish EMA stack | −0.72 | −1.17 | **harmful within winners** |
| `near_high_25` | within 25% of 52wk high | −0.99 | −1.56 | **harmful within winners** |

Two conclusions fall straight out:

- **Only entry-*timing* edges generalise.** Enter *early* and *not extended*.
  Everything else is weak, noise, or — within winners — actively harmful. This is
  exactly your thesis that *the entry point matters more than the trigger*.
- **The old 4-filter stack carried a −36% overfit tax** (train w99-R 4.77 →
  test 3.05) precisely because two of its four filters (`cir_gt75_gaps`,
  `tight_lt5`) were noise. Strip to the two robust filters and the edge stabilises.
- **`spy_above_50`, `stack_bull`, `near_high` look useless/harmful here _only
  because the sample is all winners_.** A stock that became a monster did so
  regardless of whether SPY was above its 50-day at the entry bar. These filters
  are about *avoiding losers*, so they can only be judged against the control
  group — not the winners set. That's the next build, and it's the point.

---

## 4. Where the real improvement comes from (beyond the references)

The current engine only ever tested **breakout-close entries** with **immediate
MA-close exits**. Your own vault (mined into this work) points at levers we never
simulated — these are the "go beyond" candidates, each testable on daily bars:

- **Episodic-pivot pullback entry** — don't buy the gap/breakout bar; buy the
  *first pullback 2–10 days later* that holds. Tighter, structural risk. (Your
  preferred entry; never tested here.)
- **3-bar minimum hold + Thursday-squat** — never let a trailing exit fire in the
  first 3 closes; a test of the pivot that closes back above is a *shakeout to
  hold*. My trails exit instantly and eat that shakeout tax.
- **Structural stop, not the entry-day wick** — your contract says explicitly
  *don't* stop below today's low. That is exactly what the `LOD` stop does. The
  swing-low stop (`SW`) is the structural version and is the one to keep.
- **Free Roll** — trim half at +2R, stop to breakeven, trail the rest on 10EMA.
- **10EMA trail** (your actual default) and **SPY 20EMA** regime — both worth a
  head-to-head against the 50-period versions.

These are simulated in `evaluation/engine.py`, searched on **train**, then locked
and read once on **test + control**. The trail and the stop are treated as first-
class parts of the strategy, not afterthoughts — because, as you said, the same
setup traded with a different stop and trail is a different strategy.

---

## 5. Honest limits that remain

- The control group is built from tickers that *were* monsters at some other
  time, so it is trendier than a random universe — it understates the real false-
  positive rate. It is directionally right, not a substitute for live forward
  testing.
- Even 50/50 by symbol leaves the filtered tails small. Where n is tiny I say so;
  small-sample test "wins" (e.g. the old LOD/E50 looking *better* on test) are
  noise, not vindication.
- Daily bars only — intraday fills, the 2.5% hard cap, and the portfolio-level
  circuit breakers from your contract are sizing/risk overlays, not signal edges,
  and are out of scope for the signal engine.
