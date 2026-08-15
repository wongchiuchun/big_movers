# Entry R:R Trainer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-ticker, condition-filtered Entry Trainer that reuses the existing individual simulation engine and portfolio limit-order lifecycle while reporting entry decisions primarily in R.

**Architecture:** Put historical qualification and caching behind a small Python scanner interface, keep batch/session policy in a focused `entry_trainer.js` browser module, and deepen the existing `Sim.Ctrl` seam just enough to run a flat-start trainer policy without forking playback. Reuse `portfolio_orders.js` for persistent limit execution and the existing `Sim` engine for stops, manually activated EMA trails, R, MFE/MAE, and flat-to-flat legs.

**Tech Stack:** Python 3 standard library + Flask, browser JavaScript (UMD/global modules), existing `Sim`/`Sim.Ctrl`/`PortSimOrders`, Lightweight Charts, localStorage, HTML/CSS.

**Testing note:** The user explicitly requested no automated or browser tests. Do not add or run tests. Verification is limited to Python compilation, standalone and inline JavaScript parsing, `git diff --check`, and manual source review.

---

## File Structure

- Create `entry_trainer_scanner.py`: deep server-side module for local-universe enumeration, CSV parsing, point-in-time EMA/gain qualification, mtime-aware caching, and random unique candidate selection.
- Modify `Big_movers_server.py`: thin `/api/entry-trainer/candidates` adapter that delegates to the scanner and returns stable errors.
- Create `entry_trainer.js`: Entry Trainer batch orchestration, masked candidate loading, trainer policy, order ledger, attempt snapshots, deterministic comparison points, persistence, review rendering, and export.
- Modify `portfolio_orders.js`: preserve the existing interface while making order IDs/terminology and the single-entry ledger safe for a non-portfolio caller; do not duplicate fill rules.
- Modify `Big_movers.html`: load the new module, add trainer shell/modal/review styles, expose a narrow arbitrary-symbol chart loader, and deepen `Sim.UI`/`Sim.Ctrl` with trainer policy hooks.
- Modify `README.md`: document Entry Trainer behavior and the two focused modules.

### Task 1: Historical candidate scanner

**Files:**
- Create: `entry_trainer_scanner.py`
- Modify: `Big_movers_server.py` near `/api/stock-list`

- [ ] **Step 1: Add scanner constants and result types**

Define fixed version-one rules in `entry_trainer_scanner.py`:

```python
GAIN_LOOKBACK = 63
MIN_GAIN = 0.50
EMA_PERIODS = (10, 20)
CONTEXT_BARS = 85
FORWARD_BARS = 90
EXCLUDED_SYMBOLS = {"SPX", "SPY", "NDQ", "NDX"}
```

Represent eligible rows as plain dictionaries containing only `symbol`, `qualificationDate`, `qualificationBar`, `contextStartDate`, `endDate`, and a copied `rules` payload.

- [ ] **Step 2: Reuse the server's accepted CSV layouts**

Expose or move the current `/api/ohlcv` local CSV parser into a callable helper rather than inventing a fourth layout parser. The scanner must receive sorted valid bars with finite positive closes and must skip malformed symbols without aborting the whole catalogue.

- [ ] **Step 3: Implement point-in-time qualification**

For each symbol, seed EMA10/EMA20 from the first valid close, update with `alpha = 2 / (period + 1)`, and scan from index 85. The first bar satisfying all conditions wins:

```python
gain_63 = closes[i] / closes[i - 63] - 1.0
qualified = gain_63 >= 0.50 and closes[i] > ema10[i] and closes[i] > ema20[i]
```

Require `i + 90 < len(bars)`. Do not inspect or rank future values.

- [ ] **Step 4: Add mtime-aware catalogue caching**

Build one cache fingerprint from sorted `(absolute_path, st_mtime_ns, st_size)` tuples for every candidate CSV. Rebuild only when that fingerprint changes. Keep cache mutation behind a lock so concurrent local requests cannot publish a partial catalogue.

- [ ] **Step 5: Add random unique selection and the Flask adapter**

Expose `select_candidates(count=3)` from the scanner. Shuffle a copy of the eligible catalogue and return exactly three unique symbols or raise a typed availability error. Add:

```text
GET /api/entry-trainer/candidates?count=3
```

Validate `count == 3` for version one and return `{rules, candidates}`. Return HTTP 409 with a clear message when fewer than three candidates exist; never weaken thresholds.

- [ ] **Step 6: Source-check and commit**

Run only:

```bash
python3 -m py_compile entry_trainer_scanner.py Big_movers_server.py
git diff --check
```

Inspect that no future price participates in eligibility, then commit:

```bash
git add entry_trainer_scanner.py Big_movers_server.py
git commit -m "feat: select point-in-time entry trainer candidates"
```

### Task 2: Trainer shell and arbitrary-symbol chart seam

**Files:**
- Create: `entry_trainer.js`
- Modify: `Big_movers.html` topbar, script loading, CSS, and chart-loading section

- [ ] **Step 1: Load the new module in dependency order**

Load `entry_trainer.js` after `portfolio_orders.js` and after the inline `Sim`/`Sim.Ctrl` definitions it calls, or call a deferred `EntryTrainer.wire()` after all dependencies exist. Preserve existing page startup ordering.

- [ ] **Step 2: Add a distinct Entry Trainer launcher and setup overlay**

Add a topbar `🎯 Entry Trainer` button. The setup overlay states the fixed 50%/63-bar/EMA10/EMA20 rules, three tickers, 90-bar horizon, long-only direction, maximum three attempts, and daily-OHLC limitation. Require starting equity with the existing `$300,000` default because limit notional validation and dollar reporting need a stable value.

- [ ] **Step 3: Expose one chart-loading adapter for non-catalogue symbols**

Add a small global interface such as:

```js
window.MainChartSession = {
  loadSymbol: async function(symbol, options) { /* fetch /api/ohlcv, clear row-only state, install bars */ },
  maskIdentity: function(mask),
  revealIdentity: function(meta),
  restore: function()
};
```

`loadSymbol` must clear result-catalogue markers, AI overlays, drawings, and study metadata; set daily bars and volume; and return the full sorted bar array. It must not require a row in `big_movers_result.csv`.

Add a neutral masked-date provider at the same seam rather than masking only the chart axis. Refactor the three existing direct consumers of `SimBlind.formatDate/formatBarIdx` (crosshair label, simulation day readout, and entry/new-leg modal date label) to consult a shared `SimDateMask` interface. `SimBlind` and `EntryTrainer` install adapters into that interface; ordinary mode returns no override. Entry Trainer must mask the chart title, range, axis ticks, crosshair, current-day readout, entry form date, stop/event labels, and any toast/status text during playback. Absolute dates may appear only after reveal/review.

- [ ] **Step 4: Create the batch state and lifecycle interface**

In `entry_trainer.js`, expose only:

```js
EntryTrainer.open()
EntryTrainer.isActive()
EntryTrainer.exit()
EntryTrainer.openReview(batchId)
EntryTrainer.wire()
```

Internally store a versioned batch with three candidates, active index, fixed rules, equity, status, candidate attempt/order records, and runtime-only chart references. Fetch all three descriptors before mutating the current chart; an error leaves the existing screen unchanged.

- [ ] **Step 5: Add masked ticker navigation**

Load the active candidate, verify the returned bars contain the exact qualification/end dates, mask symbol and absolute dates, and show 85 context bars through qualification. Add a compact progress strip (`Ticker 1 of 3`, `Attempt 0 of 3`) and actions for `Wait / Enter / Skip ticker / Exit batch`.

- [ ] **Step 6: Source-check and commit**

Parse `entry_trainer.js`, parse all non-empty inline scripts with the existing Node VM source-check pattern, run `git diff --check`, inspect module load order, then commit:

```bash
git add entry_trainer.js Big_movers.html
git commit -m "feat: add entry trainer batch shell"
```

### Task 3: Deepen the individual simulator policy seam

**Files:**
- Modify: `Big_movers.html` in `Sim.UI` modal wiring and `Sim.Ctrl`
- Modify: `entry_trainer.js`

- [ ] **Step 1: Replace portfolio-only order-form naming with an execution mode**

Rename the internal `_setupPortfolioOrderControls` helper to a neutral `_setupOrderControls` implementation while accepting existing `ctx.portMode` for compatibility. Add `ctx.orderMode === 'pending_limit'` for Entry Trainer. Ordinary individual setup/new-leg/add modals must retain their current editable-price behavior.

- [ ] **Step 2: Add a flat-playback session policy to `Sim.Ctrl`**

Extend the existing blind `startBlindPlayback` path into a neutral entry point:

```js
Sim.Ctrl.startFlatPlayback({
  bars,
  moveKey,
  startBarIdx,
  endBarIdx,
  initialEquity,
  policy
});
```

The trainer policy contains declarative flags (`longOnly`, `disableRewind`, `disableAdds`, `fullExitOnly`, `pauseWhenFlat`, `maxLegs`) and completion callbacks. Existing `startBlindPlayback` becomes a compatibility adapter using the same implementation.

- [ ] **Step 3: Enforce trainer controls in one place**

When trainer policy is active:

- hide/disable rewind and jump-to-entry;
- hide Add and partial Sell;
- expose Enter only while flat and before the horizon;
- use full close at paused close;
- constrain direction to long;
- pause after stop/full exit;
- invoke `onAttemptComplete(snapshot)` exactly once;
- disallow a fourth filled leg;
- cancel working orders and force-close at the 90th forward bar.

Normal individual, blind, and portfolio flows must not read trainer state.

- [ ] **Step 4: Return immutable attempt snapshots through the policy callback**

Snapshot the completed leg's entry, initial stop/risk, stop/trail events, exit, realized P&L/R, MFE/MAE and bars held before `Sim.continueSim` mutates live state. Include `trailActivatedAt`, `trailSpec`, and open R at activation derived from the event bar.

- [ ] **Step 5: Source-check and commit**

Parse all inline scripts, run `git diff --check`, and manually inspect ordinary Sim/Blind callers before committing:

```bash
git add Big_movers.html entry_trainer.js
git commit -m "feat: add entry training playback policy"
```

### Task 4: Persistent exact-price limits and attempt transitions

**Files:**
- Modify: `portfolio_orders.js`
- Modify: `Big_movers.html` in `Sim.Ctrl`
- Modify: `entry_trainer.js`

- [ ] **Step 1: Preserve the deep shared order interface**

Keep `create`, `evaluateFill`, `reserve`, `transition`, `recordEvent`, and `reconcile` as the single implementation of daily limit semantics. Generalize minted ID text if helpful, but retain `window.PortSimOrders` so Portfolio Simulation does not change. Do not copy fill logic into `entry_trainer.js`.

- [ ] **Step 2: Add a single-candidate order ledger adapter**

For the active candidate, create a serializable order owner with `pendingOrder`, `orderEvents`, identity fields, and a ledger state with `cash = startingEquity`. Use `PortSimOrders.create/reserve` for submission and `transition` for fill/cancel/expiry. Only one order can work, and unfilled/cancelled orders never increment attempts.

- [ ] **Step 3: Route trainer entry submission**

Market-at-close creates the leg immediately at the paused close. Limit mode stores fixed quantity, exact limit, initial stop, stop trigger mode, and optional fill-candle stop. Validate positive whole shares, notional within starting equity, and stop below limit.

Trainer entry/new-attempt forms must not offer `ema_trail` as an initial stop strategy, and every created entry order must persist `stopTrail: null`. Snapshot EMA values remain available as fixed initial-stop helpers. The only path that can attach an EMA auto-trail is the existing Move Stop action after a position is active and the user explicitly selects `ema_trail` on that later bar.

- [ ] **Step 4: Evaluate the order before normal position advancement**

On each new bar while flat, call `evaluateFill`. On fill, release the reservation, start a new `Sim` leg at the actual improved/limit price, and attach the initial stop. Default stop eligibility is the next candle. Reuse `Sim.processAttachedStopOnBar` for the optional fill-candle stop and mandatory gap-through safety without processing older stops twice.

- [ ] **Step 5: Complete cancellation and horizon cleanup**

Cancel from the trainer strip, expire on ticker completion, and cancel idempotently on skip, batch exit, or load failure. Render a dashed limit line and pending details using the existing portfolio visual conventions, removing them on every terminal transition.

- [ ] **Step 6: Enforce three filled attempts and candidate progression**

After a completed attempt, show realized R/$/bars/MFE-R/MAE-R and `Try Again` or `Finish Ticker`. `Try Again` calls the shared flat-leg continuation only when attempts `< 3` and future bars remain. The third attempt or the horizon forces `Finish Ticker`. `Skip` is available only while flat and cancels a working order first.

- [ ] **Step 7: Source-check and commit**

Parse `portfolio_orders.js`, `entry_trainer.js`, and inline scripts; run `git diff --check`; manually inspect portfolio order callers for unchanged semantics; then commit:

```bash
git add portfolio_orders.js entry_trainer.js Big_movers.html
git commit -m "feat: execute entry trainer limit attempts"
```

### Task 5: Deterministic entry comparison analysis

**Files:**
- Modify: `entry_trainer.js`

- [ ] **Step 1: Calculate review-only EMA series point in time**

Reuse one internal EMA helper with the scanner's seed/multiplier rules. Compute EMA10/EMA20 across candidate bars without exposing future series during playback.

- [ ] **Step 2: Detect deterministic comparison points**

For each EMA, detect a comparison point only when the prior close is at least `1.03 * priorEMA`, the current low touches/crosses the current EMA, and the current close is at or above it. After emitting one point, require the 3%-above condition again before another point of the same EMA type can emit.

- [ ] **Step 3: Calculate hindsight MFE R without claiming an optimal entry**

Use comparison-bar close as hypothetical entry and the lowest low of that bar plus four prior bars as stop. Reject invalid stops. Starting on the next bar, stop at the first low through the stop or at the exercise horizon, and report maximum high-based favorable excursion divided by per-share initial risk. Label every result `Hindsight MFE R using 5-bar-low stop`.

- [ ] **Step 4: Preserve comparison records in the ticker snapshot**

Store rule name, bar/date, hypothetical entry/stop, diagnostic MFE R, and horizon/stop end reason. Never mix comparison points into actual attempt counts, P&L, R, win rate, or self-review fields.

- [ ] **Step 5: Source-check and commit**

Parse `entry_trainer.js`, run `git diff --check`, manually calculate at least two sample rows from source logic without running a test harness, then commit:

```bash
git add entry_trainer.js
git commit -m "feat: identify entry trainer comparison points"
```

### Task 6: Entry-focused batch review, persistence, and export

**Files:**
- Modify: `entry_trainer.js`
- Modify: `Big_movers.html` review CSS/shell if required

- [ ] **Step 1: Define and persist schema version one**

Save serializable completed and abandoned batches under an Entry Trainer-specific localStorage key. Persist the rules snapshot, candidates, attempts, order activity, comparison points, skip/exit reasons, and review fields. Active batches are not resumable. Save abandoned snapshots only after idempotent cleanup.

- [ ] **Step 2: Build the batch summary**

Show total realized R first, then average R/attempt, positive-R rate, total dollar P&L, median bars held, attempts used, and skipped/no-trade count. Label the optional average of `entryLocationRating` as `Self-rated entry quality`; never call sequential drills portfolio return.

- [ ] **Step 3: Build per-ticker charts and attempt tables**

Reveal ticker and absolute dates in review. Mark requested limits, fills, initial stops, stop moves, manual trail activation, exits, and comparison points. Show realized R, dollar P&L, bars held, MFE and MAE in both dollars and R, initial stop distance in both dollars and percent, exit efficiency, and trail activation open R per attempt.

- [ ] **Step 4: Add structured manual review fields**

Persist per attempt:

```text
entryLocationRating: 1..5
stopValidity: structural | too_tight | too_wide | unclear
timing: early | well_timed | late
limitAssessment: improved | neutral | hurt_confirmation | not_used
repeatNextTime: text
changeNextTime: text
```

Add ticker-level prompts for better buy points, secondary attempts, and trail reasonableness, plus batch-level recurring entry habit and next-drill focus.

The management review must explicitly ask whether the trail was activated too early, too late, or appropriately; whether the manual exit followed observable price behavior or a desire to relieve discomfort; and how much MFE was retained.

- [ ] **Step 5: Add saved-review browsing and Markdown/CSV exports**

Use existing escape/download conventions. Export actual attempts and order lifecycle separately from comparison diagnostics. Keep R and P&L columns distinct and preserve abandoned/skipped sessions.

- [ ] **Step 6: Source-check and commit**

Parse all scripts, run `git diff --check`, manually trace save/load/export field names, then commit:

```bash
git add entry_trainer.js Big_movers.html
git commit -m "feat: review entry trainer batches"
```

### Task 7: Documentation and full-branch review

**Files:**
- Modify: `README.md`
- Modify only for defects: `entry_trainer_scanner.py`, `Big_movers_server.py`, `entry_trainer.js`, `portfolio_orders.js`, `Big_movers.html`

- [ ] **Step 1: Document the workflow and data limitations**

Add Entry Trainer to the feature overview and file layout. State the selection rules, full-local-universe source, masked three-ticker batches, daily-bar execution limits, maximum three attempts, fixed-stop-to-manual-EMA-trail behavior, and R-first review.

- [ ] **Step 2: Review the complete feature diff against the spec**

Inspect from `main` through branch tip for future-data leaks, result-catalogue bias, scanner/client EMA drift, fourth-attempt paths, order transition imbalance, fill-bar double processing, horizon cleanup, mask leaks, comparison rows contaminating metrics, localStorage migration failures, and ordinary individual/portfolio regressions.

- [ ] **Step 3: Run permitted non-test checks only**

Run:

```bash
python3 -m py_compile entry_trainer_scanner.py Big_movers_server.py
node --check entry_trainer.js
node --check portfolio_orders.js
# Parse every non-empty inline script with Node's VM parser.
git diff --check main...HEAD
```

Do not start the server, open a browser, add tests, or run existing tests.

- [ ] **Step 4: Commit review corrections and documentation**

Commit README and any source corrections found by review:

```bash
git add README.md entry_trainer_scanner.py Big_movers_server.py entry_trainer.js portfolio_orders.js Big_movers.html
git commit -m "docs: describe entry R:R training workflow"
```

- [ ] **Step 5: Integrate and clean up**

Use the `superpowers:finishing-a-development-branch` workflow. Confirm the primary worktree's user-owned `drawings.json` and `metadata.json` remain untouched, merge `feature/entry-rr-trainer` into local `main`, remove the feature worktree, and delete the merged feature branch. Do not push unless the user separately asks.
