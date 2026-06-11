# Big-Mover Momentum — TradingView Pine

Two files, both Pine v6, both verified to compile cleanly (0 errors) in the
TradingView editor:

| File | Type | Use it for |
|------|------|-----------|
| **`big_mover_signals.pine`** | `indicator()` | **Put on a chart. Marks BUY / stop / EXIT so you can trade the ideas live.** ← start here |
| `big_mover_momentum.pine` | `strategy()` | Backtesting in the Strategy Tester (net profit, win %, drawdown). Optional. |

Both came from the data study in `../evaluation/output/strategy_playbook.html`.

---

## The indicator — `big_mover_signals.pine`

This is the simple, on-chart tool you asked for. It tracks **one idea at a
time** (BUY → hold → EXIT, never overlapping) and draws:

- a **trend line** — EMA 50 by default — which is the exit reference;
- a green **BUY** label under the bar when a trigger fires and all filters pass,
  with the **suggested stop price and % risk printed right on the label**;
- a red dashed **stop line** that stays on the chart while the idea is live;
- a red **EXIT** label (or **STOP**) when the idea is closed out;
- a top-right **table** that shows, for the latest bar, whether each condition
  is met — so when no signal fires you can see exactly which filter blocked it.

### The rules it encodes

**Entry (any one trigger = a fresh push to new highs with force):**
- close above the prior 20-day high, **or**
- close above the prior 50-day high, **or**
- a gap up ≥5% on ≥1.5× average volume.

**…but only if all filters pass:** in the momentum universe (ADR 4–8%, ≥$5M
daily $-volume), early in the move (≤3 triggers since the 63-day low, <50%
extended above it), volume ≥1.5×, and SPY above its 50-day MA.

> **The two filters that actually matter** (the only ones that held their edge on
> held-out tickers) are *early* and *not extended*. Both are about **entry timing
> within the move**, not the trigger — see `../evaluation/STRATEGY_FINAL.md`.

**Stop (suggested on the BUY label):**
- *Structural* (default): the 10-bar swing low, but no wider than 1.5×ATR. This
  is the stop your contract calls "structural" — it beat the entry-day-wick stop
  on both win rate and the control group.
- *Core*: the entry-day low (tighter, choose in settings).

**Mode — pick by conviction / tape (this is the new sell logic):**
- **B Consistent (default, free roll):** at **+2R, sell half and move the stop to
  breakeven** (orange TRIM label), trail the rest on the MA. ~60% win and roughly
  **half the year-to-year variance** out-of-sample. Use when the tape is choppy or
  conviction is moderate.
- **A Runner (let it run):** no partial — hold the whole position to the MA break.
  Highest total R, but more give-back and more fragile when the move isn't real.
  Use for A+ setups in strong tape when you want the monster.

**3-bar hold (shakeout guard):** the MA exit cannot fire in the first 3 closes —
a test of the breakout that closes back above is a shakeout to hold, not a sell.

**Continuation (leg 2+) entries — OPTIONAL, off by default.** The base entry only
fires near the base (<50% extended off the 63-day low), so once a move is underway
it goes quiet — and if your first entry shook out, you're locked out of the whole
run (the VSH / RKLB / NOK problem). Toggle **Continuation** on and the indicator
also signals when price **pulls back to the 20-EMA and reclaims it inside an
uptrend** (above a *rising* 50-SMA), at any extension:
- a blue **BUY leg2** when you're flat — a re-entry / later-leg entry;
- a faded **ADD** when you're already in a trade — a pyramid point.

It's off by default because it changes the indicator's character (more signals,
lower R each). The data backing it (held-out tickers + control group):

| Entry | extension off 63-day low | held-out avg R | control avg R |
|---|---|---|---|
| Base breakout | 0–50% | 2.14 | −0.06 (w99) |
| Continuation | 50–100% (leg 2) | 0.99 | **+0.01** |
| Continuation | 100–200% (leg 3) | 1.25 | **+0.02** |

Continuation trades earn less per trade than the first leg **but stay positive
out-of-sample at every extension and behave *better* on the control group** (the
pullback-into-an-uptrend filter is higher quality than a raw breakout). Across the
databank, 90% of winning moves offered a continuation entry, and allowing them
roughly **tripled the R captured per move** (base ~2.5R → ~8R). Trade-off: more
positions / heat (apply your add + heat caps) and lower hit-rate per trade.

**Exit — the whole sell rule, made explicit:**
> Sell when price **closes below the trend line** (EMA 50 by default), but never
> in the first 3 bars. In Mode B you also sell **half at +2R** and ratchet the
> stop to breakeven. The stop exits you if hit first. Whichever comes first ends
> the idea and prints the TRIM / EXIT / STOP label.

> **Read this before trusting any win rate.** The rules were validated on a
> 50/50 train/test split of the tickers AND against a 6,553-signal control group
> (the same triggers firing on charts that did *not* become big movers). The
> honest verdict: **the entry signal has no standalone edge** — in the wild the
> average trade is ≈0R. The strategy makes money only by capping every loser at
> ~1R and letting the rare monster run. Expect a live win rate near **30%**, not
> the 50–60% the winners-database shows. Size accordingly (1R ≈ 0.5–1% of equity).

### SMA vs EMA (you asked — here's the data)

Tested on the strategy's filtered entries, exit on a close below each MA:

| Exit MA | win % | avg R (capped) | R / 30 days |
|---|---|---|---|
| SMA 50 (old default) | 52.0% | 3.65 | 3.25 |
| **EMA 50 (new default)** | 52.8% | 3.40 | 3.20 |
| EMA 20 | 54.5% | 2.40 | 3.93 |
| EMA 10 | 56.9% | 1.71 | 4.71 |

**SMA 50 vs EMA 50 is a statistical wash** — so the indicator now defaults to
**EMA 50** since you prefer reading EMAs; it costs essentially nothing. The real
trade-off is *length*, not type: a shorter EMA (10/20) gives a higher win rate
and faster turnover but **roughly halves the R per trade** because it cuts the
big runners short. Since this strategy lives off its few huge winners, keep the
length at 50 unless you specifically want more, smaller wins. Both **type and
length are settings** — flip them freely.

### Load it (≈1 minute)

1. Sign in to **TradingView** (free is fine — required to add scripts to a chart).
2. Open the **Pine Editor**, paste `big_mover_signals.pine`, click **Save**, then
   **Add to chart**.
3. Use a **daily** chart of a momentum name (e.g. NASDAQ:APP, NVDA, HOOD). The
   BUY/EXIT labels appear on history so you can eyeball how it would have traded.
4. To get pinged live: right-click the chart → **Add alert** → condition
   *BigMover BUY* (and another for *BigMover EXIT*).

---

## The strategy — `big_mover_momentum.pine` (optional, for backtesting)

Same rules wired into a `strategy()` with risk-% position sizing, so the
**Strategy Tester** gives you net profit, win %, profit factor and max drawdown.
Add it to a chart the same way; the metrics appear in the Strategy Tester tab.

> **Honest caveat for both files.** The rules were derived on a *winners-only*
> database, so the playbook's in-sample numbers are an optimistic ceiling. The
> TradingView backtest on ordinary symbols is the unbiased reality check the
> database couldn't give. Expect a lower win rate and flatter equity; what should
> survive is the *shape* — a minority of trades carrying the result, smaller
> drawdowns on the Consistency stop, better behaviour in uptrending tape.
