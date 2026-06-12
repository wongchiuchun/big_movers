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

## Continuation (leg 2+) entries — answered 2026-06-12

The locked rules above only take the FIRST leg (extension <50% off the 63-day
low). User observed live that this misses the bulk of strong trends and locks you
out after a first-entry shakeout (VSH, RKLB, NOK). Tested a continuation entry —
a pullback that reclaims the 20-EMA inside an uptrend (above a rising 50-SMA), at
any extension — across train/test/control (`run_continuation.py`):

| Entry | extension | held-out test R | control R (w99) |
|---|---|---|---|
| base breakout | 0–50% | 2.14 (61% win) | −0.06 |
| continuation | 50–100% (leg 2) | 0.99 (50%) | **+0.01** |
| continuation | 100–200% (leg 3) | 1.25 (53%) | **+0.02** |
| continuation | 200%+ | 0.69 (46%) | +0.24 (n=39) |

Verdict: **continuation entries are worth it.** Lower R per trade than the first
leg, but positive out-of-sample at every extension AND *better-behaved on control*
than the base breakout (the pullback-into-uptrend gate is a higher-quality filter
than a raw breakout — less chasing, not more). 90.5% of winning moves offered a
continuation entry; allowing them roughly **tripled R captured per move** (base
~2.46R → +5.73R extra). It also re-enters after a shakeout, fixing the lockout.

Shipped as an OPTIONAL, off-by-default toggle in `big_mover_signals.pine`
("Continuation (leg 2+) entries"): blue **BUY leg2** when flat, faded **ADD** when
already in a trade. Off by default because it changes the tool's character (more
signals, lower R each, more heat). User's call whether to run it.

## Base-number decay & the 2023+ regime — answered 2026-06-12

User: the early-only rule sits out the 2nd/3rd bases of the long multi-base
10-baggers since 2023. Tested forward R by base number (bases = new-high breakout
after an ≥8-bar pause, numbered within each move), pre-2023 vs 2023+, Mode A
runner, on held-out winners + control (`run_bases.py`):

| Era | Base | held-out avg R (w99) | control w99 |
|---|---|---|---|
| pre-2023 | 1 / 2 / 3 / 4+ | 4.12 / 2.52 / 2.58 / 1.41 | ~0 |
| 2023+ | 1 / 2 / 3 / 4+ | 4.78 / **3.17** / **3.08** / 2.34 | +0.13 / +0.05 / −0.08 / −0.10 |

Verdict: signal decays after base 1 but stays strongly tradeable through **base
3** (~2.2–3.1R), and later bases pay **more in 2023+** than historically. In
2023+, **80% of moves had a later base and later bases held 62% of the capturable
R** (base-1 ~5.2R/move vs later ~8.7R). The early-only rule captures ~⅜ of recent
opportunity. Caveats: control stays ≈0 (slightly negative at base 3/4+ in 2023+),
so not a free lunch; and later-base consolidations are NOT shorter (~3 weeks at
every base) and ADR stays in-band — it's the extension filter, not tightness/ADR,
that excludes them. Implication: prefer a **base-count rule (take bases 1–3 in a
confirmed uptrend)** over the hard extension cap. Covered today by the optional
continuation toggle; a first-class base-count entry is the clean next build.

## What I would build next (not done yet)
- A true out-of-universe control (random S&P names, not ex-monsters) to pin the
  real false-positive rate — current control is trendier than reality.
- Wire `engine.py` Mode A/B into the app's portfolio sim for equity-curve and
  drawdown visualisation under position sizing.
- Test a market-regime auto-switch (SPY vs 20-EMA per your contract) that flips
  A↔B, rather than choosing the mode by hand.
