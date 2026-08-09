# Portfolio Pending Limit Orders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent exact-price limit orders, cash reservation, cancellation, chart feedback, rewind, and review activity to interactive portfolio entries, re-entries, and adds.

**Architecture:** Add a deep `PortSimOrders` module that owns order creation, validation, direction-aware daily-bar fill evaluation, reservation accounting, terminal transitions, and lifecycle events behind a small interface. Keep `Big_movers.html` as the adapter for modal DOM, portfolio playback, the existing `Sim` engine, cash/short locks, snapshots, chart rendering, and review serialization. Do not modify standalone simulation or setup-wizard pre-entry semantics.

**Tech Stack:** Browser JavaScript (UMD modules), existing `PortSim`/`Sim` namespaces, Lightweight Charts, HTML/CSS, local persisted review/session structures.

**Testing note:** The user explicitly requested no test runs. Do not add or run automated tests for this implementation. Verification is limited to JavaScript syntax parsing, `git diff --check`, and manual diff inspection.

---

### Task 1: Pending-order domain module

**Files:**
- Create: `portfolio_orders.js`
- Modify: `Big_movers.html` (top-level script loading)

- [ ] **Step 1: Define the module interface**

Expose `window.PortSimOrders` and CommonJS with a focused interface:

```js
create(draft, context)              // returns {ok, order|error}
availableBuyingPower(state)         // cash minus aggregate live reservations
evaluateFill(order, bar, barIdx)    // null or {price, gapImproved}
canSettle(state, order, fillPrice)  // reservation-aware drift guard
reserve(state, entry, order)        // attach and reserve exactly once
transition(state, entry, status, details) // release once + append lifecycle event
recordEvent(entry, type, details)   // non-terminal activity such as gap-through-stop
reconcile(state, entries)           // recompute reservation from working orders
cloneOrder(order)
```

`create` mints stable IDs, fixes quantity at the limit, validates entry/add eligibility and supplied stops, and records submission metadata. `evaluateFill` implements long `open <= limit || low <= limit` and short inverse rules while rejecting the submission bar.

- [ ] **Step 2: Implement cent-safe reservation and lifecycle invariants**

Store aggregate `state.reservedBuyingPower`, per-order `reservedBuyingPower`, `status: 'working'`, and an entry-level `orderEvents` array. Terminal transitions (`filled`, `cancelled`, `invalidated`, `expired`) are idempotent and release once. A gap-through-stop order first transitions to `filled`, then records a separate non-terminal `gap_stop` position event so both required lifecycle facts survive. `reconcile` is the defensive snapshot/restore authority.

- [ ] **Step 3: Load the module after `portfolio_assets.js`**

Add `<script src="portfolio_orders.js"></script>` before inline portfolio controller modules.

- [ ] **Step 4: Source-check and commit**

Run non-test JavaScript parsing and `git diff --check`, inspect the interface, then commit:

```bash
git add portfolio_orders.js Big_movers.html
git commit -m "feat: add portfolio pending order model"
```

### Task 2: Portfolio-only order form controls

**Files:**
- Modify: `Big_movers.html` (setup/new-leg/add modal markup, `Sim.UI` portfolio context, `PortSim.Modal` adapters)

- [ ] **Step 1: Add reusable order-type markup to three forms**

Add `Market at close` and `Limit` pills, an exact limit-price field, and an unchecked `Activate protective stop on fill candle` checkbox to Setup, New Entry, and Add. Keep controls hidden or existing behavior unchanged when `portMode` is false.

- [ ] **Step 2: Wire modal state and submission values**

On every open reset order type to market and fill-bar stop to unchecked. Market mode displays the paused close and prevents arbitrary fill editing. Limit mode enables exact price validation. Submit:

```js
{
  orderType: 'market_close' | 'limit',
  price,
  allowFillBarStop,
  // existing direction, size, and stop fields
}
```

For Add, store an optional replacement stop without applying it while the limit remains working.

- [ ] **Step 3: Preserve standalone behavior**

Guard all new order UI and price locking behind `ctx.portMode`. Confirm standalone `showSetupModal`, `showNewLegModal`, and Add callers retain their prior fields and timing.

- [ ] **Step 4: Source-check and commit**

Parse inline scripts, run `git diff --check`, inspect modal reset/submit paths, then commit:

```bash
git add Big_movers.html
git commit -m "feat: add portfolio limit order controls"
```

### Task 3: Controller submission, reservation, cancellation, and fills

**Files:**
- Modify: `Big_movers.html` (`PortSim.Ctrl`, cash/header derived values, playback loop)

- [ ] **Step 1: Add portfolio order state helpers**

Initialize `reservedBuyingPower`, attach `pendingOrder`/`orderEvents` to stock and index entries, and expose available buying power without subtracting reservations from equity or deployed capital.

- [ ] **Step 2: Route market and limit submissions**

Keep Market at close immediate at the paused close for Setup/New Entry/Add. Replace raw-cash preflights with `PortSimOrders.availableBuyingPower` so immediate orders cannot consume funds already reserved for working limits. For Limit, pass a draft into `PortSimOrders.create` and `reserve`, leave entry/re-entry inactive, and leave an add's current position and stop unchanged.

- [ ] **Step 3: Add cancellation controls to the controller interface**

Expose a card-identity-aware `cancelPendingOrder(entry)` action. It transitions once, releases reservation, clears the line/badge, and rerenders without changing an existing position.

- [ ] **Step 4: Integrate candle fill processing**

For each entry with data on the new unified date:

1. Advance existing active positions so current stops fire first.
2. Invalidate a pending add when its position closes.
3. Evaluate surviving pending entries/adds through `PortSimOrders.evaluateFill`.
4. Before releasing anything, call `canSettle`: for longs, require raw cash minus other live reservations to cover actual cost; for shorts, require it to cover the order's originally reserved notional without adding a new gap-price margin requirement. If drift broke that invariant, invalidate once and leave no position.
5. Release reservation and create a sim/start a leg/add at actual fill price.
6. Apply long cash debit or existing short lock.
7. Activate protective/replacement stop from the next bar by default.
8. If enabled, process only the new stop on the fill bar.
9. Force close at the open for the specified gap-through-stop safety case, after recording both `filled` and separate `gap_stop` events.

Return synthetic fill/stop events to the normal cash folding and render flow without processing existing stops twice.

- [ ] **Step 5: Handle lifecycle cleanup**

Cancel or invalidate orders on manual cancellation, parent close, runtime card replacement/removal, end of simulation, and hard exit. Keep every path idempotent.

- [ ] **Step 6: Source-check and commit**

Parse scripts, run `git diff --check`, inspect cash/short/add processing ordering, then commit:

```bash
git add Big_movers.html
git commit -m "feat: execute portfolio pending limit orders"
```

### Task 4: Rewind-safe snapshots and card presentation

**Files:**
- Modify: `Big_movers.html` (`_pushSnapshot`, `_stepBack`, CardPanel, CardChart, ExpandModal, Track J)

- [ ] **Step 1: Snapshot and restore orders**

Clone `pendingOrder`, `orderEvents`, and aggregate `reservedBuyingPower` into every playback snapshot. On restore, reconcile aggregate reservation from live working orders before rendering so advancing again cannot duplicate a fill or release.

- [ ] **Step 2: Render pending state on standard cards**

Display a `PENDING LIMIT` badge with side, quantity, and price. Draw a dashed order line separate from protective stops and entry/R lines. Show reserved buying power and a Cancel Order action. Active cards with a pending add retain Sell/Move Stop/Close and disable further Add.

- [ ] **Step 3: Render and cancel from expanded cards**

Mirror pending details, dashed line, and Cancel Order action in `ExpandModal`. Refresh immediately after placement/cancellation/fill/rewind.

- [ ] **Step 4: Source-check and commit**

Parse scripts, run `git diff --check`, inspect standard/expanded cleanup and rewind flows, then commit:

```bash
git add Big_movers.html
git commit -m "feat: show rewind-safe pending orders"
```

### Task 5: Review persistence and reporting

**Files:**
- Modify: `Big_movers.html` (archive/session/review capture, rendered report, Markdown/PDF/export paths)

- [ ] **Step 1: Preserve order activity across archive and session capture**

Carry `orderEvents` with stock/index identity through runtime archive, summary/session state, saved review records, and reconstructed reviews. Never convert a never-filled order into a trade leg.

- [ ] **Step 2: Add order activity to the portfolio report**

Render placed, filled, cancelled, invalidated, expired, and gap-through-stop events with symbol/card identity, direction, quantity, price, date, and reason. Ensure actual fill date/price feeds executed legs.

- [ ] **Step 3: Keep metrics trade-only**

Confirm review win rate, profit factor, average capital deployed, P&L, and trade counts continue to derive only from executed legs/events; pending/cancelled orders are informational.

- [ ] **Step 4: Source-check and commit**

Parse scripts, run `git diff --check`, inspect all persistence/export paths, then commit:

```bash
git add Big_movers.html
git commit -m "feat: report portfolio order activity"
```

### Task 6: Final non-test review and integration readiness

**Files:**
- Modify only if review finds a defect: `portfolio_orders.js`, `Big_movers.html`

- [ ] **Step 1: Inspect the complete branch diff against the spec base**

Review for missing stock/index handling, duplicate cash transitions, fill-on-submission-bar errors, stale UI, lost snapshot fields, standalone regressions, and accidental edits to user-owned data.

- [ ] **Step 2: Run permitted non-test checks only**

Run JavaScript syntax parsing for the module and inline scripts plus `git diff --check`. Do not run automated or browser tests.

- [ ] **Step 3: Commit any review corrections**

Commit only source fixes. Leave the user's modified CSV, drawings, and metadata files untouched in the primary worktree.

- [ ] **Step 4: Report the completed branch and checks performed**

State explicitly that automated tests were not run at the user's request.
