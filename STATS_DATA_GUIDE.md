# Sim Stats — Data Guide

> Reference for analyzing exported sim performance data. Hand this file (and the exported CSV) to an AI assistant when you want cross-session analysis.

## What gets logged

Each click of **📊 Add to Stats** at the end of a sim creates one **session** record and one or more **trade** records (one per leg). A leg = entry → exit (stop / close / force-close / open). A single session can contain many trades.

Storage is browser localStorage:
- `bm_sim_sessions_v2` — array of session objects
- `bm_sim_trades_v2` — array of trade objects (each references `sessionId`)

Use the **↓ Export CSV** button in the Sim Stats modal to dump a denormalized CSV: one row per trade, with every relevant session column repeated alongside it. This is the file you paste into an AI conversation.

## CSV columns

### Trade-level (one row = one leg)

| Column | Type | Notes |
|---|---|---|
| `tradeId` | string | Unique id of the trade row |
| `sessionId` | string | FK to the session this trade belongs to |
| `tradeTs` | ISO datetime | When the parent session was logged (real-world clock, not sim-internal date) |
| `simType` | `individual` \| `portfolio` | Which simulator produced this leg |
| `symbol` | string | Ticker traded |
| `year` | int | Big-mover year tag (sim-internal) |
| `direction` | `long` (only direction supported today) | |
| `legIndex` | int | 1-based index of this leg within the session for that symbol |
| `entryDate` | ISO date | Sim-internal entry bar date |
| `entryPrice` | float | |
| `qty` | int | Initial shares; later adds aren't tracked here in v1 |
| `stopAtEntry` | float | Initial stop price (NOT the trailed/moved stop) |
| `initialRisk` | float | `qty × (entryPrice − stopAtEntry)` |
| `exitDate` | ISO date | Sim-internal exit bar date (or last played bar if `exitReason=open`) |
| `exitPrice` | float | Realized exit fill price; for `open` legs this is mark-to-market close |
| `exitReason` | `stop` \| `close` \| `open` \| `aggregate` | `aggregate` = migrated v1 record (no leg detail) |
| `holdingDays` | int | Bars held (≈ trading days) |
| `realizedPnL` | float | Per-leg P&L (USD). For `open` legs, mark-to-market. |
| `rMultiple` | float | `realizedPnL / initialRisk`. Sign matches P&L. |
| `returnPctOfNotional` | float | `realizedPnL / (entryPrice × qty) × 100` — leg return on capital deployed at entry |
| `mfe` | float | Max favourable excursion ($) during the leg |
| `mae` | float | Max adverse excursion ($) during the leg |

### Session-level (denormalized — repeated on every trade row)

| Column | Type | Notes |
|---|---|---|
| `sessionTs` | ISO datetime | When you clicked Add to Stats |
| `sessionInitialEquity` | float | Starting equity at sim setup (or null if not configured) |
| `sessionFinalEquity` | float | Equity at end of sim |
| `sessionPnL` | float | Sum of all trades in the session |
| `sessionTotalReturnPct` | float | `sessionPnL / sessionInitialEquity × 100` |
| `sessionAvgPctDeployed` | float % | **Time-weighted average of (position notional / equity) across every played bar.** Headline metric for "how effectively did I use capital?" |
| `sessionPeakPctDeployed` | float % | Highest single-bar deployment in the session |
| `sessionIdlePctOfTime` | float % | Fraction of bars with no open position |
| `sessionTradeCount` | int | Number of legs in the session |
| `sessionWinCount` / `sessionLossCount` | int | Per-trade wins/losses inside the session |
| `sessionWinRate` | float % | Per-trade win rate inside the session |
| `sessionProfitFactor` | float | `sum(winning P&L) / |sum(losing P&L)|` for the session |
| `sessionSymbols` | pipe-delimited | Symbols traded; for portfolio sims this is the basket |
| `sessionSimStartDate` / `sessionSimEndDate` | ISO date | Sim window (internal, not real-world) |
| `sessionIndexReturnPct` / `sessionIndexName` | float / string | Benchmark return over the sim window (portfolio sims) |
| `sessionTickerBhPct` | float | Ticker buy-and-hold return over the played window (individual sims) |

## Common analyses

When handing the CSV to an AI, these are reasonable prompts:

- "Compute my per-trade win rate and profit factor across all sessions. Then split by `simType`."
- "Which symbols have the worst R-multiple distribution? Histogram bins of -3R to +5R."
- "How does my `sessionAvgPctDeployed` correlate with `sessionTotalReturnPct`? Plot deployment vs return."
- "Find sessions where I underused capital (`sessionIdlePctOfTime > 50%`) and show their P&L vs alpha vs index."
- "Group trades by `holdingDays` bucket (≤3, 4-10, 11-30, >30) and report avg R per bucket."
- "Look at my last 30 days. Is my expected value per trade trending up or down? Compute a 7-trade rolling EV."
- "For sessions with ≥5 trades, what's my best win-rate session? Which symbol contributed most?"

## Linking to underlying ticker data

The sim data alone tells you *what you did*. To compare against *what could have been*:

- The raw OHLCV CSV for any ticker lives at `collected_stocks/<SYMBOL>.csv` (date, open, high, low, close, volume).
- The big-mover catalogue is `big_movers_result.csv` (year, symbol, gain_pct, low_date, high_date, low_price, high_price, avg_vol_b).
- For any trade row, the relevant bars are between `entryDate` and `exitDate` of the symbol.

When asking an AI to do cross-source analysis, say: *"For these trade rows, also load the OHLCV CSV at `collected_stocks/<symbol>.csv` and compare my entry timing vs the move's high."*

## Schema versions

- v1 (deprecated): single record per session, no per-leg breakdown. Detected at first load and migrated to v2; migrated rows have `exitReason=aggregate` so they're easy to filter out of leg-level analysis.
- v2 (current): two-table schema described above. Stable.
