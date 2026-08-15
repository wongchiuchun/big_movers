# Entry R:R Trainer Design

## Summary

Add a first-class **Entry Trainer** mode to the historical chart application. The trainer will select three point-in-time candidates per batch from the full local stock universe. Each candidate must have gained at least 50% over the preceding 63 trading sessions and must close above both its 10 EMA and 20 EMA on the qualification date.

The user will play each chart forward one daily bar at a time, decide whether to wait, enter, or skip, define an initial fixed stop, and manage the trade until a full exit or stop-out. Entries may execute at the paused candle close or through a persistent exact-price limit order. After becoming flat, the user may make another attempt, up to three filled attempts per ticker. A batch concludes with an entry-focused manual review.

The primary outcome is R return. Dollar return and bars held are secondary. The report will separate entry quality, management quality, and outcome so a profitable chase is not automatically treated as a good entry and a well-structured stopped trade is not automatically treated as a bad one.

## Goals

- Train the user to wait for favorable entry geometry in stocks already exhibiting strong momentum.
- Require a defined entry and structural risk boundary before a position exists.
- Make `Wait` and `Skip` valid decisions rather than forcing a trade in every candidate.
- Reuse the proven individual `Sim` engine, chart playback, stop strategies, and portfolio pending-order model.
- Support three-ticker batches and no more than three filled attempts per ticker.
- Review realized R, dollar P&L, bars held, MFE, MAE, entry location, stop quality, trail behavior, and possible secondary opportunities.
- Keep Entry Trainer sessions distinct from normal individual and portfolio simulations.

## Non-goals

- Automatically identify one objectively perfect hindsight entry.
- Use intraday sequencing that cannot be known from daily OHLC data.
- Score entries solely by whether the trade made money.
- Optimize exits, pyramiding, or portfolio exposure in the first version.
- Add short training; the initial condition and workflow are long-only.
- Change existing individual, blind, or portfolio simulation behavior.
- Download missing market data during training.

## Terminology

- **Qualification date:** the first historical daily bar on which a ticker has gained at least 50% over the preceding 63 sessions and closes above EMA10 and EMA20, with enough local context and forward bars for the exercise.
- **Attempt:** one filled position from entry through full manual exit or stop-out. An unfilled or cancelled limit order is not an attempt.
- **Initial R:** the absolute dollar risk defined by filled quantity multiplied by the distance from actual fill to the initial stop.
- **Realized R:** realized P&L divided by that attempt's initial R.
- **Comparison point:** a rule-described historical location surfaced during review, such as a 10 EMA or 20 EMA pullback. It is diagnostic evidence, not a declaration of the perfect entry.

## User Workflow

### Start a batch

The top bar gains an **Entry Trainer** action. Starting it creates a batch containing three unique symbols. The setup explains the fixed rules:

- 50% or greater gain over 63 sessions.
- Close above EMA10 and EMA20 on the qualification date.
- Long-only.
- Ninety forward daily bars per ticker.
- Maximum three filled attempts per ticker.
- Persistent limit orders remain working until filled, cancelled, or the ticker exercise ends.

The candidate symbol and absolute dates are masked during playback, following the existing Blind Replay convention. They are revealed in batch review. The chart shows enough preceding daily bars to assess momentum, pullbacks, support, and extension. No future drawing, annotation, metadata, result-catalogue field, or candle may leak into the visible chart.

### Play a ticker

Playback begins flat on the qualification bar. The user advances one bar at a time and may:

- **Wait:** advance without entering.
- **Enter:** open the shared entry form.
- **Skip ticker:** finish the ticker with no trade and record a reason.
- **Cancel order:** cancel a working limit order without consuming an attempt.

The entry form offers:

- **Market at close:** fill immediately at the current paused candle close.
- **Limit:** place one persistent exact-price buy limit, first eligible on the next candle.
- Exact initial stop and the existing stop-strategy helpers.
- Existing optional fill-candle protective-stop behavior for a limit fill; otherwise the protective stop begins on the next bar, subject to the existing gap-through safety rule.
- Position size or dollar amount so dollar P&L remains meaningful, although R is the primary result.

Only one working entry order may exist. The trainer does not support active-position adds or partial exits in the first version. A possible secondary entry is expressed as another attempt after the position is flat, keeping each R denominator and entry decision unambiguous.

### Manage an attempt

The position starts with the fixed initial stop. The user may:

- Advance daily bars.
- Fully exit at the paused close.
- Replace the active stop manually.
- Replace the fixed stop with the existing EMA auto-trail at a user-chosen bar, using the same mechanism as Portfolio Simulation.

The trail never activates automatically. The attempt ends immediately when the full position is manually exited or stopped out. Playback pauses and shows an attempt strip with realized R, dollar P&L, bars held, MFE in R, and MAE in R. The user can finish the ticker or continue from the same unseen future point for another attempt. The third filled attempt always ends the ticker.

The exercise horizon is the close of the 90th bar after qualification. On that final bar, any working limit is cancelled unfilled and any open position is force-closed at the final close with exit reason `horizon_end`. No new attempt can begin on or after the final bar. This keeps every candidate comparable and guarantees a realized R result without inventing additional future data.

Rewind is disabled in Entry Trainer mode. Seeing a future candle is irreversible within that exercise.

### Finish and review

The batch review opens after all three tickers are finished or skipped. It reveals identities and dates and provides a tab for each ticker plus a batch summary. Review can be saved and reopened using the application's existing local review/session conventions.

## Candidate Selection

### Universe

Use `/api/stock-list` and the local `collected_stocks` files rather than `big_movers_result.csv`. The result catalogue is selected using eventual move outcomes and would bias the trainer toward winners. Index aliases and symbols without usable daily history are excluded.

### Point-in-time calculation

For each symbol, process bars in ascending date order. Seed EMA10 and EMA20 from the first valid close in the file and update them with the standard multiplier `2 / (period + 1)` on every subsequent close. A candidate must have at least 85 preceding bars, which supplies the masked chart's display context and fully warms both EMAs. At bar `i >= 85`:

```text
gain63 = close[i] / close[i - 63] - 1
qualified = gain63 >= 0.50
         && close[i] > ema10[i]
         && close[i] > ema20[i]
```

EMA values use closes through bar `i` only. No later price, future setup label, eventual high, or future return participates in qualification. The first bar that satisfies the rule is the symbol's qualification date for version one.

A symbol is eligible only when it has at least 90 subsequent local bars after the qualification bar. Its exercise end index is exactly `qualificationIndex + 90`. Forward coverage is a playback-availability check only; future values are not inspected or ranked. The batch samples three unique eligible symbols uniformly, using a shuffled candidate order. Failure to obtain three candidates produces a clear non-mutating error rather than weakening the rules silently.

### Scanner seam and caching

Add an Entry Trainer scanner module behind a small interface:

```text
GET /api/entry-trainer/candidates?count=3
  -> { rules, candidates: [{ symbol, qualificationDate, qualificationBar, endDate }] }
```

The server implementation reads only local CSV data, calculates conditions with the Python standard library, and caches the eligible catalogue in memory. The cache key incorporates source filenames and modification times so changed local data invalidates the catalogue. The caller does not need to know file layouts, EMA seeding, retry logic, or caching rules. This is a deep module: deleting it would push all of that complexity back into the browser.

The endpoint returns identity because the browser must load the bars, but the Entry Trainer adapter keeps it out of visible playback state until review.

## Architecture and Module Seams

### `EntryTrainerScanner`

Owns universe enumeration, CSV parsing reuse, point-in-time qualification, local cache invalidation, and random three-symbol selection. Its interface is the candidate endpoint above.

### `EntryTrainer`

A new browser module, preferably `entry_trainer.js`, owns:

- Batch identity and rules snapshot.
- The three candidate descriptors.
- Current ticker and attempt counters.
- Trainer-only order and attempt records.
- Skip/finish/continue transitions.
- Mask/reveal state.
- Entry-specific report construction and persistence.

Its external interface should remain small:

```js
EntryTrainer.open()
EntryTrainer.isActive()
EntryTrainer.exit()
EntryTrainer.openReview(batchId)
```

The implementation adapts existing `Sim.Ctrl` playback operations rather than reimplementing candle processing. Trainer-specific policy is supplied as a mode/configuration object: no rewind, long-only, no adds, full exits only, maximum three legs, and callbacks for attempt/ticker/batch completion.

### Shared order module

`portfolio_orders.js` currently contains a deep pending-order lifecycle but its browser adapters are portfolio-specific. Generalize the module name or expose a neutral alias while preserving `window.PortSimOrders` compatibility. Entry Trainer supplies a small ledger adapter for one working order; Portfolio Simulation retains its reservation and cash adapter.

The shared order implementation continues to own direction-aware daily-bar limit fill evaluation, next-bar eligibility, price improvement, lifecycle transitions, fill-candle stop choice, and gap-through safety. Do not copy these rules into the trainer controller.

### Existing `Sim` engine

The existing engine remains the authority for positions, fixed stops, manually activated EMA trails, MFE/MAE, realized P&L, initial R, bars held, multiple flat-to-flat legs, and event history. Trainer changes should deepen its mode seam only where necessary; they should not fork the engine.

### Review adapter

Build the Entry Trainer report from trainer batch records and immutable attempt snapshots. Reuse formatting/chart helpers from existing individual and portfolio reviews, but keep a trainer-specific schema so entry-quality fields do not pollute ordinary session records.

## State Model

```text
batch
  id, createdAt, rules, status
  candidates[3]
  currentCandidateIndex

candidate
  symbol, qualificationDate, endDate
  status: pending | active | skipped | completed
  attempts[0..3]
  orderEvents
  skipReason
  review

attempt
  attemptNumber
  entryDate, requestedPrice, fillDate, fillPrice
  initialStop, initialRisk, quantity
  exitDate, exitPrice, exitReason
  realizedPnL, realizedR, barsHeld
  mfe, mfeR, mae, maeR
  stopEvents, trailActivatedAt, trailSpec
```

Runtime state may reference live chart and `Sim` objects, but persisted records contain serializable snapshots only. Version the saved schema from its first release.

## Scoring and Review

### Outcome metrics

Each attempt reports:

- Realized R prominently.
- Dollar P&L secondarily.
- Bars held.
- MFE and MAE in both dollars and R.
- Initial stop distance in dollars and percent.
- Exit efficiency: realized R as a proportion of MFE R when MFE is positive.
- Trail activation date/bar and open R when activated.

Ticker and batch summaries report total realized R, average R per attempt, positive-R rate, total dollar P&L, median bars held, attempts used, and skipped/no-trade count. Do not label these as a portfolio return because candidates are sequential drills rather than concurrent capital deployment.

### Entry quality review

Entry quality is reviewed independently of outcome. Each attempt asks:

- Was the entry near identifiable support or structure?
- Was the stop at genuine invalidation?
- Was the stop artificially tight to manufacture attractive R:R?
- Was the entry extended from EMA10, EMA20, or the prior consolidation?
- Did the user enter before the pullback stabilized?
- Did a limit improve location or avoid necessary confirmation?
- What should be repeated or changed?

This is structured self-review, not an automated objective score. Persist these fields per attempt:

```text
entryLocationRating: 1 | 2 | 3 | 4 | 5
stopValidity: structural | too_tight | too_wide | unclear
timing: early | well_timed | late
limitAssessment: improved | neutral | hurt_confirmation | not_used
repeatNextTime: free text
changeNextTime: free text
```

The batch may show the average self-rated entry location, but it must label it **Self-rated entry quality** and keep it separate from realized R.

### Management review

- Was the trail rule reasonable?
- Was it activated too early, too late, or appropriately?
- Did the manual exit follow price behavior or discomfort?
- How much MFE was retained?

### Comparison points

The review chart may mark deterministic comparison points occurring after qualification and before exercise end. For EMA period `p`, an EMA pullback comparison point is a bar where:

```text
prior close >= prior EMA(p) * 1.03
current low <= current EMA(p)
current close >= current EMA(p)
```

This defines “moved away” as at least 3% above the EMA on the immediately preceding bar and “test” as touching the EMA intraday while closing back above it. Mark the first qualifying EMA10 point and first qualifying EMA20 point, plus later points only after the condition has reset through another prior-close move of at least 3% above that EMA.

The comparison points include:

- First test of EMA10 that closes back above EMA10.
- First test of EMA20 that closes back above EMA20.
- Later repeat tests of those averages after the condition resets as defined above.
- User attempts, cancelled limits, stops, exits, and trail activation.

For a comparison point, use its closing price as the hypothetical entry and the lowest low of that bar and the preceding four bars as the hypothetical stop. Omit the R diagnostic when the stop is not finite or is not below entry. Otherwise begin stop evaluation on the next bar, end at the earlier of the first stop hit or the exercise horizon, and report maximum favorable excursion divided by the hypothetical initial risk. Label it **Hindsight MFE R using 5-bar-low stop**; do not present it as realized R or assume an exit at the maximum.

Comparison points must be labelled by rule, not as `optimal` or `perfect`. Their diagnostic is explicitly hindsight-only and does not alter the user's self-rating or realized R. The manual review asks whether each point was actually actionable given the candles visible then and whether a valid secondary attempt existed.

## Daily-Bar Execution Rules

- Market entry fills at the paused candle close.
- A limit submitted on bar `i` first checks bar `i + 1`.
- Long limit: fill at open when `open <= limit`; otherwise fill at limit when `low <= limit`.
- Limit quantity is fixed at submission and does not increase after price improvement.
- Limit remains working until fill, manual cancellation, ticker completion, or batch exit.
- The attached initial stop starts checking on the candle after fill by default.
- Optional fill-candle stop and mandatory gap-through-stop behavior match Portfolio Simulation.
- Existing fixed stops process before newly submitted actions on later bars.
- On the final exercise bar, cancel any working order and force-close any position at that bar's close.
- Daily OHLC ambiguity is disclosed in the setup and report.

## Error Handling and Invariants

- A batch contains exactly three unique eligible symbols or does not start.
- Qualification never uses future values.
- Only one candidate is active at a time.
- Only one working limit order may exist for the active candidate.
- An attempt begins only on a fill; cancelled/unfilled orders do not increment the counter.
- No candidate can have more than three attempts.
- A new attempt cannot begin while the prior position is open.
- Trainer mode cannot rewind or expose future annotations.
- Exit, skip, batch cancellation, and hard cleanup cancel any working order idempotently.
- Persisted attempts are immutable snapshots; later simulation state cannot rewrite prior R or stop history.
- Failure to render or save review must not change simulation or order state.
- Existing individual, blind, and portfolio sessions retain their current behavior and schemas.

## Persistence and Export

Save completed and intentionally abandoned batches locally under a versioned Entry Trainer key. Persist rules with each batch so later threshold changes do not reinterpret old sessions. Active batches are not resumable in version one. Exiting early performs idempotent order/position cleanup, records the batch as `abandoned`, and saves the reviewable snapshots captured so far. Provide Markdown and CSV export using the same escaping and download conventions as existing reviews.

Entry Trainer sessions may appear as a distinct `entry_trainer` type in the Stats picker, but their R-focused aggregates remain separate from individual/portfolio P&L aggregates. An initial release may expose saved batches from the trainer review rather than modifying every global Stats chart, provided no records are misclassified.

## Implementation Sequence

1. Create the scanner module and candidate endpoint.
2. Add the Entry Trainer browser module and three-candidate batch state.
3. Adapt existing blind playback into trainer policy mode.
4. Generalize pending-order use for the single active trainer candidate.
5. Enforce attempts, fixed-stop-to-manual-trail workflow, no rewind, no adds, and full exits.
6. Add completion summaries, review, persistence, and exports.
7. Inspect the whole branch for no-lookahead leaks and regressions, run source parsing and whitespace checks, then merge to local `main`.

## Verification Strategy

The user explicitly requested no automated tests. Do not add or run automated or browser tests for this feature.

Permitted verification is limited to:

- Python source compilation for changed Python modules.
- JavaScript parsing for standalone modules and all non-empty inline scripts.
- `git diff --check`.
- Manual source review of qualification arithmetic, future-data isolation, order transitions, attempt caps, cleanup, persistence, and report calculations.
- Whole-branch review against this specification before merge.

The handoff must state explicitly that no functional tests were run and that the user will perform manual testing.
