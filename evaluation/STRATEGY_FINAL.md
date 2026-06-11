# The strategy, locked and validated out-of-sample

> 2026-06-12. Selected on TRAIN (50% of tickers), read once on held-out TEST,
> and stress-tested against a 6,553-signal CONTROL group (the same triggers
> firing OUTSIDE recorded winning windows). Full method in `REFLECTION.md`;
> numbers from `evaluation/run_engine.py` → `output/engine_results.json`.

## The one thing to internalise first

**The entry signal has no standalone edge.** When the exact same trigger
(early, non-extended breakout/gap, ADR 4–8%, volume ≥1.5×) fires on a chart that
did *not* go on to become a recorded 100%+ mover, the average outcome is ≈0R and
slightly negative on winsorized R — in every single configuration tested.

So this is not a "high-edge signal." It is a **risk-management + right-tail-
capture machine**:
- every non-monster is capped at ~1R by a structural stop, and
- the rare monster is held by a trailing exit that lets the right tail run.

Profit comes from the *asymmetry*, not from being right often. That is exactly
the expectancy thesis in your own vault (Jeff Sun: 25% WR × 4:1 still wins). It
also means **position sizing and stop discipline are not secondary to the signal
— they ARE the strategy.**

## What generalises (and what was overfit)

Only two filters keep their edge from train to held-out test, and both are about
*entry timing within the move*, not the trigger:

| filter | edge train → test | keep? |
|---|---|---|
| enter early (≤3 triggers off the 63-day low) | +2.32 → +1.82 | **yes** |
| not extended (<50% above the 63-day low) | +2.11 → +2.19 | **yes** |
| volume ≥1.5× | +0.38 → +0.43 | yes (weak) |
| gap closes upper-range | +0.34 → −0.11 | no — noise |
| SPY>50SMA, EMA-stack, near-52wk-high | ≤0 within winners | judge on control only |

The old playbook's 4-filter stack carried a **−36% overfit tax** because two of
its filters were noise. The locked strategy uses only the robust ones.

## The locked rules

Common to all modes:
- **Universe:** ADR 4–8%, ≥$5M/day 20-day dollar volume.
- **Entry filters:** early (≤3 triggers off the 63-day low), not extended
  (<50% above it), volume ≥1.5× the 20-day average.
- **Stop:** **structural swing low** — the lowest low of the last 10 bars, but no
  wider than 1.5×ATR(20). This is your contract's *structural* stop. It beat the
  entry-day-wick stop (`LOD`) on both win rate and control behaviour — the wick
  stop is exactly what your contract says not to use, and the data agrees.
- **3-bar hold (Thursday-squat guard):** a trailing-MA exit cannot fire in the
  first 3 closes. Free improvement everywhere (e.g. E10: win 53.5%→56.4%, R up,
  no control cost).

Then pick a **mode by conviction / tape** — this is the regime combination you
asked for, and the control group is what justifies it (the let-it-run trail is
the most control-fragile, so you only earn the right to use it when you are
confident you are in a real move):

### Mode A — RUNNER (strong tape, A+ setup, you want the monster)
- **Trail:** close below the **50-MA** (EMA50 ≈ SMA50; use EMA, you prefer it).
- **No partial.** Hold the whole position to the 50-MA break.
- Out-of-sample: **win 51%, avg R +3.48 (test), w99 +3.12.** Highest total R.
- Cost: yearly std 0.49, worst blended year −0.41. It gives back open profit and
  is the most fragile when the move turns out not to be real.

### Mode B — CONSISTENT (default; choppy tape, lower conviction, drawdown repair)
- **Free Roll:** at **+2R, sell half and move the stop to breakeven**; trail the
  rest on the 50-MA (or 10-EMA for faster turnover).
- Out-of-sample: **win 60% (test), avg R +1.99, w99 +1.81.**
- Payoff: yearly std **0.29** (≈half of Mode A) for the *same* median year. Worst
  blended year −0.28. Fewer, shallower drawdowns — your "able to come back over
  time." This is the recommended default.

### Entry style — your choice, small cost either way
- **Breakout-close** (enter the trigger bar): more entries (346 vs 224 train),
  marginally higher R.
- **Pullback** (Episodic-Pivot: buy the first tag of the 10-EMA within 10 bars):
  fewer trades, slightly cleaner on control, tighter structural risk — it misses
  the names that run away without a pullback. Roughly R-neutral vs breakout. A
  legitimate stylistic preference, not a free lunch. Use it if it keeps you
  disciplined; don't expect it to add edge.

## Honest expectancy for live trading

Blend the rare monster with the common non-monster and the per-trade expectancy
is **small and positive (~0.1R blended), 9–10 of 27 years negative** — but Mode
B's negative years are shallow (worst −0.28R). Translation: trade it sized so a
−1R loss is ~0.5–1% of equity (your contract's 1R rule), expect to be right
~30–40% of the time in the wild, and let the math — not the hit rate — do the
work. Do **not** expect the winners-database win rates (50–60%) live; those are
survivorship. The control group says the wild win rate is ~30%.

## What I would build next (not done yet)
- A true out-of-universe control (random S&P names, not ex-monsters) to pin the
  real false-positive rate — current control is trendier than reality.
- Wire `engine.py` Mode A/B into the app's portfolio sim for equity-curve and
  drawdown visualisation under position sizing.
- Test a market-regime auto-switch (SPY vs 20-EMA per your contract) that flips
  A↔B, rather than choosing the mode by hand.
