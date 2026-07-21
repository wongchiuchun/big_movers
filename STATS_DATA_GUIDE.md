# Sim Stats — Data Guide

> Reference for analyzing exported sim performance data. Hand this file (and the exported CSV) to an AI assistant when you want cross-session analysis.

## Two stores, two purposes

There are **two independent stats stores** in the app. They serve different jobs and have different shapes.

| Store | What it captures | When it's written | How to access |
|---|---|---|---|
| **SimStats (lifetime log)** | One record per logged session + one per leg, kept across all sims forever. Designed for cross-session analysis. | Click **📊 Add to Stats** in the sim summary modal at the end of a sim. | Open via the lifetime-stats button (top bar) → **↓ Export CSV** for AI analysis. |
| **PortSim Review (per-run snapshot)** | A single rich snapshot of one portfolio-sim run: full basket, every leg, plus your free-text review notes (per-ticker + portfolio-level + sim-wide trading notes). Designed for "go back and re-read what I learned." | Click **💾 Save** in the Trade Review modal. | Open the **📝 Review** modal → **📂 Load** to pick any saved run. |

If you want statistical analysis across many sims → use SimStats.
If you want to revisit one run with your written notes → use PortSim Review.

---

## Store 1 · SimStats (lifetime log)

Storage is browser localStorage:
- `bm_sim_sessions_v2` — array of session objects
- `bm_sim_trades_v2`   — array of trade objects (each references `sessionId`)
- `bm_sim_stats_v1`    — legacy v1 records (kept untouched as a safety net; auto-migrated into v2 on first load)
- `bm_sim_stats_migrated_v2` — sentinel set after v1→v2 migration runs

Each click of **📊 Add to Stats** writes ONE session and N trades (one per leg). A leg = entry → exit (stop / close / force-close / still-open). A single session can contain many trades.

Caps: 5,000 sessions and 50,000 trades total. When close to full, export the CSV and clear (the app halves the slice on quota errors).

Use the **↓ Export CSV** button in the Sim Stats modal to dump a denormalized CSV: one row per trade, with every relevant session column repeated alongside it. This is the file you paste into an AI conversation.

### CSV columns

#### Trade-level (one row = one leg)

| Column | Type | Notes |
|---|---|---|
| `tradeId` | string | Unique id of the trade row |
| `sessionId` | string | FK to the session this trade belongs to |
| `tradeTs` | ISO datetime | When the parent session was logged (real-world clock, not sim-internal date) |
| `simType` | `individual` \| `portfolio` | Which simulator produced this leg |
| `symbol` | string | Ticker traded |
| `year` | int | Big-mover year tag (sim-internal) |
| `direction` | `long` \| `short` | Per-leg direction. Shorts are first-class — sign of P&L matches the directional bet. |
| `legIndex` | int | 1-based index of this leg within the session for that symbol |
| `entryDate` | ISO date | Sim-internal entry bar date |
| `entryPrice` | float | |
| `qty` | int | Initial shares; later adds aren't tracked here in v1 |
| `stopAtEntry` | float | Initial stop price (NOT the trailed/moved stop). Long: below entry. Short: above entry. |
| `initialRisk` | float | `qty × |entryPrice − stopAtEntry|`. Always positive. |
| `exitDate` | ISO date | Sim-internal exit bar date (or last played bar if `exitReason=open`) |
| `exitPrice` | float | Realized exit fill price; for `open` legs this is mark-to-market close |
| `exitReason` | `stop` \| `close` \| `open` \| `aggregate` | `aggregate` = migrated v1 record (no leg detail) |
| `holdingDays` | int | Bars held (≈ trading days) |
| `realizedPnL` | float | Per-leg P&L (USD), sign already direction-aware. For `open` legs, mark-to-market. |
| `rMultiple` | float | `realizedPnL / initialRisk`. Sign matches P&L. |
| `returnPctOfNotional` | float | `realizedPnL / (entryPrice × qty) × 100` — leg return on capital deployed at entry |
| `mfe` | float | Max favourable excursion ($) during the leg |
| `mae` | float | Max adverse excursion ($) during the leg |

#### Session-level (denormalized — repeated on every trade row)

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

> **Direction at session level:** for `simType=individual` the session row carries the sim's direction. For `simType=portfolio` the session-level `direction` field is currently hardcoded `long` even when individual legs are shorts — always trust the **trade-level** `direction` over the session-level one for portfolio sims.

### Common analyses

When handing the CSV to an AI, these are reasonable prompts:

- "Compute my per-trade win rate and profit factor across all sessions. Then split by `simType` and by `direction`."
- "Which symbols have the worst R-multiple distribution? Histogram bins of -3R to +5R."
- "How does my `sessionAvgPctDeployed` correlate with `sessionTotalReturnPct`? Plot deployment vs return."
- "Find sessions where I underused capital (`sessionIdlePctOfTime > 50%`) and show their P&L vs alpha vs index."
- "Group trades by `holdingDays` bucket (≤3, 4-10, 11-30, >30) and report avg R per bucket."
- "Look at my last 30 days. Is my expected value per trade trending up or down? Compute a 7-trade rolling EV."
- "For sessions with ≥5 trades, what's my best win-rate session? Which symbol contributed most?"
- "Compare my long vs short performance — win rate, avg R, profit factor, holding days."

### Schema versions

- **v1** (deprecated): single record per session, no per-leg breakdown. Detected at first load and migrated to v2; migrated rows have `exitReason=aggregate` so they're easy to filter out of leg-level analysis. Migration is one-shot, gated by `bm_sim_stats_migrated_v2`.
- **v2**: two-table schema with denormalized summary CSV. Sessions in `bm_sim_sessions_v2`, trades in `bm_sim_trades_v2`. No decision-quality fields.
- **v3** (current): adds `runInstanceId` and a `review` sub-object on every session record. Old v2 sessions remain readable; their review fields export as empty in the deep CSV. New sessions are written as `v: 3` from the next code load. The trade table (`bm_sim_trades_v2`) is unchanged — review tags live on the session, joined to legs by `tradeId`.

### v3 review object

Every session written under v3 carries a `review` object. The object always exists; on save the modal-driven fields stay null until the guided review modal completes.

```js
{
  // ...existing v2 fields (id, ts, simType, symbols, year, sessionPnL, ...)
  v: 3,
  runInstanceId: 'inst_<base36ts>_<rand>',  // per-attempt id, joins to standalone review note
  review: {
    schemaVersion: 2,
    reviewSkipped: true,
    retroactive: false,
    completedAt: null,
    session: null,    // populated when modal completes — see fields below
    legs: null        // populated when modal completes — keyed by tradeId
  }
}
```

#### Top-level `review` fields

| Field | Type | Range / values | Populated when | Source |
|---|---|---|---|---|
| `schemaVersion` | int | `1` \| `2` | Always | `2` is the current simulation-focused form; `1` is retained for legacy reviews. |
| `reviewSkipped` | bool | `true` \| `false` | Always | Auto. Starts `true`; set to `false` when guided modal completes. |
| `retroactive` | bool | `true` \| `false` | Always | Auto. `true` if `completedAt - session.ts > 24h`. |
| `completedAt` | int (ms) \| null | UNIX epoch ms | When modal finalizes | Auto on modal save |
| `session` | object \| null | see below | When Save Review is clicked | Trade Review modal |
| `legs` | object \| null | `{ [tradeId]: legReview }` | When Save Review is clicked | Trade Review modal |

#### `review.session` fields

| Field | Type | Range / enum | Populated when | Source |
|---|---|---|---|---|
| `dominantPattern` | enum | `none` \| `fomo_chasing` \| `loss_avoidance` \| `profit_giveback_fear` \| `stop_avoidance` \| `revenge_reentry` \| `overtrading` \| `freezing` \| `inconsistent_sizing` \| `other` | Save Review | Main discipline pattern observed during the simulation. |
| `outcomeCarryover` | enum | `no` \| `slightly` \| `yes_chased` \| `yes_froze` \| `unclear` | Save Review | Whether the previous result affected the next decision. |
| `executedWell` | string | free text | Save Review | Specific technical or discipline behavior worth repeating. |
| `disciplineChallenge` | string | free text | Save Review | Where discipline weakened or an urge/shortcut appeared. |
| `nextRunRule` | string | free text | Save Review | One concrete rule for the next simulation. |
| `streakBefore` | int | `0..N` | Modal open | Auto — count of immediately preceding losing sessions |
| `portfolioNote` | string | free text | Save Review | General portfolio-level note from the Overview tab. |

#### `review.legs[tradeId]` fields

`legs` is a dict **keyed by `tradeId`** (the unique id from `bm_sim_trades_v2`), not by `legIndex`. Joining is on the trade record id so reviews survive any reordering of legs within a session.

| Field | Type | Range / enum | Populated when | Source |
|---|---|---|---|---|
| `setupType` | enum | `EP` \| `breakout_VCP` \| `pullback_10EMA` \| `pullback_20EMA` \| `continuation` \| `parabolic` \| `other` \| `custom` | Save Review | Technical setup selected from the chart-only information. |
| `setupCustom` | string | free text | Save Review | User-defined setup name when `setupType=custom`. |
| `disciplineResult` | enum | `as_planned` \| `fomo_chased_entry` \| `anticipated_entry` \| `loss_avoidance_exit` \| `profit_protection_exit` \| `panic_sellout` \| `held_past_technical_exit` \| `moved_stop_wider` \| `ignored_stop` \| `unplanned_add` \| `emotional_reentry` \| `overtraded` \| `other_deviation` | Save Review | Primary observable execution or discipline result for the leg. |
| `technicalLesson` | string | free text | Save Review | Technical cue or discipline mistake that mattered. |

#### Example `review` — fully populated

```json
{
  "schemaVersion": 2,
  "reviewSkipped": false,
  "retroactive": false,
  "completedAt": 1714752000000,
  "session": {
    "dominantPattern": "loss_avoidance",
    "outcomeCarryover": "slightly",
    "executedWell": "Entries stayed close to chart structure and stops were defined before advancing.",
    "disciplineChallenge": "After the first loss I wanted to protect every small gain too quickly.",
    "nextRunRule": "Do not exit unless the chart invalidates the position or the planned stop fires.",
    "streakBefore": 2,
    "portfolioNote": "Two of three legs went well. The PLTR add was unplanned and cost me half the day's gain."
  },
  "legs": {
    "trade_sess_1714750000_ab12_1": {
      "setupType": "breakout_VCP",
      "disciplineResult": "as_planned",
      "technicalLesson": "Entry stayed close to the breakout pivot and the stop remained structural."
    },
    "trade_sess_1714750000_ab12_2": {
      "setupType": "custom",
      "setupCustom": "Undercut and reclaim",
      "disciplineResult": "profit_protection_exit",
      "technicalLesson": "Sold on a normal red bar even though the technical exit had not triggered."
    }
  }
}
```

### `runInstanceId` — join key to standalone review notes

Every v3 session has a `runInstanceId` of the form `inst_<base36ts>_<rand>`. This id is the join key between:

- The session record in `bm_sim_sessions_v2`
- The standalone review note record at `bm_sim_review_<runInstanceId>` (individual sims) or `bm_portsim_review_<runInstanceId>` (portfolio sims)

The standalone note record is preserved for backward compatibility with the free-form review modal — it holds the legacy textareas / per-ticker notes / sim-wide diary entries. The structured `session.review` object lives on the session itself; the unstructured note record lives at the `runInstanceId`-keyed entry. Both are present and need not be merged.

Old keys of the form `bm_portsim_review_<startDate>__<endDate>__<sortedSymbols>` are read-only on first encounter and lazily ported into the matching `runInstanceId`-keyed record (see Phase 1 migration).

---

### Deep CSV columns

The Sim Stats modal exposes a second export — **deep CSV** — alongside the existing summary CSV. The deep CSV has every column of the summary CSV plus the columns below appended at the end. One row per trade, with both session-level review fields (denormalized — repeated on every leg of the same session) and per-leg review fields (joined by `tradeId`).

For sessions that pre-date v3 or have `reviewSkipped: true`, the appended columns are emitted as empty strings.

#### Session-level review columns (denormalized — repeated on every trade row)

| Column | Type | Source | Notes |
|---|---|---|---|
| `reviewSchemaVersion` | int | `session.review.schemaVersion` | `2` for the current form; `1` for legacy reviews; empty for pre-review sessions. |
| `reviewSkipped` | bool | `session.review.reviewSkipped` | `true` until guided modal completes |
| `reviewRetroactive` | bool | `session.review.retroactive` | `true` if review completed >24h after session save |
| `reviewCompletedAt` | ISO datetime | `session.review.completedAt` | Empty until modal finalizes |
| `sessionEmotionalScore` | int 1-5 | `session.review.session.emotionalScore` | |
| `sessionRegimeFelt` | enum | `session.review.session.regimeFelt` | `trending` \| `choppy` \| `declining` \| `mixed` \| `recovery` |
| `sessionStreakBefore` | int | `session.review.session.streakBefore` | Auto-computed at modal open |
| `sessionGateOverridden` | bool | `session.review.session.gateOverridden` | |
| `sessionPainNext24h` | string | `session.review.session.painCalibration.next24h` | Free text |
| `sessionPainNextDayAction` | enum | `session.review.session.painCalibration.nextDayAction` | `enter_more` \| `hold_steady` \| `step_away` \| `unsure` |
| `sessionPainOutOfHowMany` | string | `session.review.session.painCalibration.outOfHowMany` | Free text |
| `sessionPortfolioNote` | string | `session.review.session.portfolioNote` | Free text |
| `sessionDominantPattern` | enum | `session.review.session.dominantPattern` | Main discipline weakness (or `none`). |
| `sessionOutcomeCarryover` | enum | `session.review.session.outcomeCarryover` | Whether one result affected the next decision. |
| `sessionExecutedWell` | string | `session.review.session.executedWell` | Free text; behavior worth repeating. |
| `sessionDisciplineChallenge` | string | `session.review.session.disciplineChallenge` | Free text; where discipline weakened. |
| `sessionNextRunRule` | string | `session.review.session.nextRunRule` | Free text; one rule for the next run. |

#### Per-leg review columns (joined by `tradeId`)

| Column | Type | Source | Notes |
|---|---|---|---|
| `legSetupType` | enum | `session.review.legs[tradeId].setupType` | `EP` \| `breakout_VCP` \| `pullback_10EMA` \| `pullback_20EMA` \| `continuation` \| `parabolic` \| `other` |
| `legIntendedHold` | enum | `session.review.legs[tradeId].intendedHold` | `scalp_intraday` \| `short_swing_3_10d` \| `core_swing_10_30d` \| `runner_30d_plus` |
| `legConviction` | int 1-5 | `session.review.legs[tradeId].conviction` | Captured at entry-time semantics, populated post-hoc in the modal |
| `legEntryState` | enum | `session.review.legs[tradeId].entryState` | `calm` \| `itchy` \| `fomo` \| `revenge` |
| `legPlanFidelity` | enum | `session.review.legs[tradeId].planFidelity` | `as_planned` \| `cut_early_nervous` \| `held_past_plan` \| `added_unplanned` \| `moved_stop_wider` |
| `legWouldHoldReal` | bool | `session.review.legs[tradeId].wouldHoldReal` | |
| `legAtHeatResponse` | enum | `session.review.legs[tradeId].atHeatResponse` | `held` \| `widened_stop` \| `panic_cut` \| `none_needed` |
| `legThesis` | string | `session.review.legs[tradeId].thesis` | Free text |
| `legNote` | string | `session.review.legs[tradeId].legNote` | Free text |
| `legSetupCustom` | string | `session.review.legs[tradeId].setupCustom` | Custom setup name when `legSetupType=custom`. |
| `legDisciplineResult` | enum | `session.review.legs[tradeId].disciplineResult` | Primary structured execution/discipline result. |
| `legTechnicalLesson` | string | `session.review.legs[tradeId].technicalLesson` | Free-text technical or discipline lesson. |

The older schema-v1 review columns remain in the CSV so historical reviews are not lost. New schema-v2 reviews leave those legacy columns empty and populate the new columns above.

### Common analyses (deep CSV)

When handing the deep CSV to an AI, these are reasonable prompts that exploit the review fields:

- "For deep CSV, compute average R-multiple grouped by `legSetupType`. Rank by mean R and report n, mean, median, std for each."
- "Filter on `reviewSkipped == false`. Compare R-multiple and MFE for `legDisciplineResult == 'as_planned'` versus each deviation."
- "How often do `loss_avoidance_exit` and `profit_protection_exit` appear, and how much MFE remained after those exits?"
- "Across sessions where `sessionStreakBefore >= 3`, what was the median R of the next session's first leg? Did the user trade better or worse after losing streaks?"
- "Group `sessionDominantPattern` by month. Which weakness is becoming more or less frequent?"
- "Find sessions where `sessionOutcomeCarryover` is `yes_chased` or `yes_froze`; compare the next leg's R-multiple with independent decisions."
- "Summarize recurring themes in `sessionDisciplineChallenge`, `sessionNextRunRule`, and `legTechnicalLesson`, citing the relevant session IDs."
- "Cross-tab `legSetupType` (using `legSetupCustom` for custom setups) × `legDisciplineResult`. Which setup/weakness combinations recur?"

---

## Store 2 · PortSim Review (per-run snapshot)

One localStorage entry per saved review. Used for the **Trade Review** modal (the screen with overview / index / per-ticker tabs and the textareas for notes).

### Key format

```
bm_portsim_review_<startDate>__<endDate>__<symbol1-symbol2-...sorted>
```

Built by `_computeRunId(st)`: prefix + sim window + every basket symbol joined by `-` (alphabetically sorted). This means saving the same basket over the same window updates in place; changing dates or basket creates a new key.

> **v3 note:** new saves write under `bm_portsim_review_<runInstanceId>` instead, joining the standalone review note to the matching session via the session's `runInstanceId`. Old setup-keyed entries are still loaded for backward compatibility and lazily ported on first encounter.

The `📂 Load` picker lists every key under the prefix, regardless of whether the matching sim is currently active. If you load a review whose basket+window match the live sim → editable mode. Otherwise → view-only (notes still editable; stats are a snapshot).

### Payload shape (top level)

| Field | Type | Notes |
|---|---|---|
| `notes` | object | Per-ticker review notes: `{ AAPL: "...", TSLA: "..." }`. Free text the user types in each per-ticker tab. |
| `portfolio` | string | Free-text portfolio-level review note from the Overview tab. |
| `savedAt` | ISO datetime | Real-world timestamp of the most recent save. |
| `meta` | object | Full snapshot of the run — see below. Preserved verbatim on save when the modal is in view-only mode (so reloading + saving never zeroes out historical stats). |

### `meta` object

Snapshotted by `_buildMeta()` at the moment of save. Contains everything needed to re-render every review tab without an active sim. Charts are NOT included (storage cost) — they're refetched from `/api/ohlcv` on demand and the new **↻ Extend to today** button on each chart pulls fresh bars.

| Field | Type | Notes |
|---|---|---|
| `startDate` / `endDate` | ISO date | Sim window |
| `index` | string | Benchmark name (`SPX` → fetched as `SPY` data, `NDQ`, etc.) |
| `initialEquity` | float | Starting equity |
| `cash` / `equity` | float | End-of-run cash and total equity |
| `realized` / `unreal` | float | Realized vs unrealized P&L at end-of-run |
| `totalPnL` | float | `equity - initialEquity` |
| `peak` | float | Equity peak (used for max-DD %) |
| `maxDDDol` | float | Max drawdown ($) |
| `openCount` | int | Tickers still holding shares at end-of-run |
| `shortLocks` | object | Per-leg short-proceeds escrow (P0 short fence). Empty when no shorts. |
| `notes` | array | Sim-wide trading notes — the diary entries written via the live-sim 📝 Notes button (NOT the per-ticker review notes above). Each: `{ id, date, text }`. Rendered on the index tab in the review modal. |
| `basket` | array | One entry per ticker (live + retired). See below. |

#### `meta.basket[i]`

| Field | Type | Notes |
|---|---|---|
| `symbol` | string | Ticker |
| `legs` | array | One per leg, including the active leg if open. See below. |
| `totalRealized` | float | Sum of `legs[*].rPnL` |
| `stops` | int | Count of legs with `exitReason='stop'` |
| `status` | string | Last leg's `exitReason`, or `idle` if no legs |

#### `meta.basket[i].legs[j]`

| Field | Type | Notes |
|---|---|---|
| `idx` | int | 1-based leg index |
| `direction` | `long` \| `short` | Per-leg |
| `legId` | string \| null | Stable id (P7 short-locks) |
| `entryDate` / `entryPrice` | date / float | |
| `shares` | int | Initial shares for the leg |
| `stop0` | float | Entry stop price |
| `risk0` | float | `shares × |entryPrice − stop0|` |
| `exitDate` | date \| null | Null for active leg |
| `exitReason` | `stop` \| `close` \| `open` \| `closed` \| `idle` \| `—` | Wider vocabulary than SimStats — `open` and `idle` distinguish "still holding" vs "between trades" within an active sim |
| `rPnL` / `rMult` | float | Realized P&L and R-multiple (or unrealized for active leg) |
| `mfe` / `mae` | float | Excursions |
| `eventsLog` | array | Raw event stream the chart markers are drawn from (entries, adds, sells, stops, closes) |
| `active` | bool | True for the still-open leg |

### View-only behavior (relevant if you load a saved review without an active sim)

- The textareas remain **editable** — type to add or revise notes; saving writes back without touching `meta`.
- Pressing **💾 Save** updates `notes`, `portfolio`, and `savedAt`. It does NOT rebuild `meta` (would otherwise read from a missing live state and zero everything out — that was the prior bug).
- Each chart has an **↻ Extend to today** button that hits `/api/fetch-ticker?extend=true`, refetches `/api/ohlcv`, and redraws — useful when a ticker's CSV ended mid-sim.

---

## Linking to underlying ticker data

Stats data alone tells you *what you did*. To compare against *what could have been*:

- The raw OHLCV CSV for any ticker lives at `collected_stocks/<SYMBOL>.csv` (date, open, high, low, close, volume).
- The big-mover catalogue is `big_movers_result.csv` (year, symbol, gain_pct, low_date, high_date, low_price, high_price, avg_vol_b).
- For any trade row, the relevant bars are between `entryDate` and `exitDate` of the symbol.

When asking an AI to do cross-source analysis, say: *"For these trade rows, also load the OHLCV CSV at `collected_stocks/<symbol>.csv` and compare my entry timing vs the move's high."*

---

## Quick reference — where things live

| You want… | Look at |
|---|---|
| Lifetime stats CSV for cross-sim analysis | localStorage `bm_sim_sessions_v2` + `bm_sim_trades_v2`; export via Sim Stats → ↓ Export CSV |
| Lifetime stats CSV with review fields | localStorage same as above; export via Sim Stats → deep CSV button |
| One run's full snapshot + your notes | localStorage `bm_portsim_review_*` (legacy setup-keyed) or `bm_portsim_review_<runInstanceId>` (v3); load via Review modal → 📂 Load |
| Raw price bars | `collected_stocks/<SYMBOL>.csv` on disk; `/api/ohlcv?symbol=X` over HTTP |
| The big-mover catalogue | `big_movers_result.csv` on disk; `/api/results` over HTTP |
| Per-move tags / rating / direction / chart drawings | `metadata.json` (study) + `drawings.json` on disk |
