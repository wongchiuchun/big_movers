# Big-Mover Momentum — Pine Script strategy

`big_mover_momentum.pine` is the data-derived strategy from
`../evaluation/output/strategy_playbook.html` translated into a TradingView
Pine v6 `strategy()` that plots **BUY** / **SELL** signals and backtests.

**Compile status:** verified clean (`//@version=6`, 0 errors) in the TradingView
Pine editor on 2026-06-11.

## What it does

| Piece | Rule |
|-------|------|
| Universe | 20-day ADR 4–8%, ≥ $5M avg daily $-volume (momentum sweet spot) |
| Entry signal | close crosses prior 20d **or** 50d high, **or** ≥5% gap on ≥1.5× volume |
| Freshness filters | ≤3 signals since the 63-day low · <50% extended off that low · ≥1.5× rel vol · SPY > 50SMA |
| Initial stop | **Consistency** (default): 10-bar swing low capped at 1.5×ATR20 · or **Core**: entry-day low |
| Exit | close below the 50SMA (next bar) — also the SELL signal |
| Sizing | risk % of equity ÷ stop distance; half size when SPY < 50SMA (if regime gate off) |

Inputs let you flip stop mode, risk %, the regime gate, universe bands, and each
filter threshold from the strategy settings dialog.

## How to load and test it (≈1 minute)

1. Open **TradingView** (desktop app or tradingview.com) and **sign in**
   — a free account is enough; the Strategy Tester is gated behind login.
2. Open the **Pine Editor** (bottom panel).
3. **Open** menu → paste the full contents of `big_mover_momentum.pine`
   (or copy from this repo). Click **Save**.
4. Click **Add to chart**. BUY/SELL labels appear and the **Strategy Tester**
   tab fills with the backtest (net profit, win %, profit factor, max drawdown,
   trade list).
5. Put it on a **daily** chart of a liquid momentum name (e.g. NASDAQ:APP,
   NVDA, HOOD). The top-right table shows whether the current bar passes each
   filter, so you can see why a signal did or didn't fire.

## Reading the results honestly

The strategy was derived on a **winners-only databank**, so its in-sample
expectancy is an upper bound — TradingView's backtest on an arbitrary symbol is
the *unbiased* check the databank can't give you. Expect a lower win rate and
flatter equity than the playbook's in-sample numbers; what should survive is the
*shape*: a minority of trades carrying the result, controlled drawdowns on the
Consistency stop, and better behaviour in uptrending tape.

Differences vs the Python study to keep in mind:
- TradingView applies its own slippage/commission settings (set them in the
  Strategy Tester → Properties to match your costs).
- The Python sim deduped multiple same-day signals and used a 250-bar horizon;
  here the position simply runs until the 50SMA exit or stop, one position at a
  time (`pyramiding = 0`).
- "Signals since the 63-day low" is the live-tradable proxy for the study's
  "entry ordinal within the move" — same idea, computable without hindsight.
