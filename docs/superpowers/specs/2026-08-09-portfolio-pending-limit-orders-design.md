# Portfolio Pending Limit Orders Design

## Summary

The portfolio simulator currently opens an entry immediately at the submitted price on the paused candle. It will add an explicit order choice to the interactive portfolio entry flows:

- **Market at close** opens or adds immediately at the paused candle's closing price.
- **Limit** creates a persistent, direction-aware order at an exact price. It begins checking on the next candle and remains working until it fills, the user cancels it, its parent position becomes ineligible, or the simulation ends.

This feature applies to interactive card **Setup**, **New Entry**, and **+ Add** actions for both stock and index cards. Portfolio setup wizard rows marked **Pre-entry** remain declarations of positions already open at the simulation start. The standalone single-ticker simulator is out of scope.

## Goals

- Let users choose immediate close execution or a persistent limit order for entries, re-entries, and adds.
- Model long and short limit fills from daily OHLC data without implying unavailable intraday sequencing.
- Prevent multiple pending orders from spending the same portfolio buying power.
- Make pending orders visible and cancellable on normal and expanded cards.
- Preserve pending-order state across rewind and record its lifecycle in portfolio review data.

## Non-goals

- Stop-entry, market-on-open, good-until-date, partial-fill, or multi-order support.
- Editing a working order; users cancel it and submit a replacement.
- More than one pending order per card.
- Applying pending orders to the standalone simulator or setup-wizard pre-entries.
- Reconstructing the exact intraday path inside a daily OHLC candle.

## Terminology

The requested price below a long entry reference is a **buy limit**, not a buy stop. The UI will use the standard term **Limit**. For short entries the inverse rule applies: the limit is normally above the current market and fills when price trades up to it.

## Architecture

Pending orders belong to the portfolio controller, not the core `Sim` active-position engine. The controller already owns cards, cash, playback, snapshots, and portfolio review boundaries. Keeping the new lifecycle there avoids creating a synthetic active position before an order fills and leaves standalone simulation behavior unchanged.

Each live portfolio entry may hold at most one `pendingOrder`:

```text
pendingOrder = {
  id,
  kind: "entry" | "add",
  direction: "long" | "short",
  limitPrice,
  qty,
  sizeMode,
  sizeValue,
  reservedBuyingPower,
  submittedBarIdx,
  submittedDate,
  stopPrice,
  stopTrail,
  stopTriggerMode,
  allowFillBarStop,
  status
}
```

The order stores a fixed whole-share quantity at submission time. Dollar sizing uses `floor(sizeValue / limitPrice)`. The actual fill may improve the price but does not increase the quantity.

Portfolio state will track aggregate reserved buying power separately from cash. Reservation reduces *available* buying power but does not reduce portfolio equity or count as deployed capital. On fill, cancellation, invalidation, rewind, replacement, hard exit, or simulation completion, reservation bookkeeping must remain balanced.

## User Interface

The portfolio versions of Setup, New Entry, and Add forms gain an order-type control:

- **Market at close**
- **Limit**

Market-at-close uses the paused candle's closing price and executes immediately. Limit mode exposes one exact-price input. It also exposes an unchecked checkbox labeled **Activate protective stop on fill candle**. The checkbox is per order, defaults off every time a form opens, and does not remember a prior choice.

A card with a working order shows:

- A `PENDING LIMIT` badge containing price and quantity.
- A dashed horizontal line at the limit price.
- Reserved buying power in order details.
- A **Cancel Order** action in both the standard and expanded card views.

An idle card with a pending entry remains pending rather than active. An active card with a pending add remains active and retains Sell, Move Stop, and Close actions, but cannot place a second add until the pending add is filled or cancelled.

For a pending add, an optional replacement stop is stored with the order and is not applied before the add fills. The position's existing stop remains active while the add waits.

## Submission and Reservation

Limit-order submission validates:

- A positive finite limit price. Initial entries and re-entries require a positive finite protective stop; adds validate a replacement stop only when one is supplied.
- Positive whole-share quantity after sizing.
- A directionally valid supplied protective stop relative to the limit: below for long and above for short.
- Enough unreserved buying power for `qty * limitPrice`.
- No existing pending order on the card.
- An eligible card state: idle/between for entry or active for add.

The controller reserves `qty * limitPrice` when the order is accepted. Long and short orders both reserve notional buying power so concurrent pending orders cannot overcommit the same cash. Existing short-proceeds locking begins only when a short actually fills. For shorts, this reservation is a concurrency guard consistent with the simulator's existing preflight model, not a full margin calculation.

A submitted order is never evaluated against its submission candle. Its first eligible bar is the next portfolio playback candle with data for that card.

## Fill Rules

For each eligible daily candle:

### Long limit

- If `open <= limitPrice`, fill at the opening price.
- Otherwise, if `low <= limitPrice`, fill at the limit price.
- Otherwise remain pending.

### Short limit

- If `open >= limitPrice`, fill at the opening price.
- Otherwise, if `high >= limitPrice`, fill at the limit price.
- Otherwise remain pending.

The fill price can improve but can never be worse than the limit. At fill, release the full reservation and apply the actual fill through the existing long cash-debit or short-lock mechanism. A better long fill costs less than the reservation, so the unused amount becomes available buying power. A better short fill may create proceeds greater than the reserved notional; those proceeds go into the existing short lock, the reservation is fully released, and no incremental cash preflight is required. This deliberately preserves the portfolio simulator's current short-collateral model rather than introducing margin accounting in this feature.

For a pending initial entry, fill creates the `Sim` leg using the actual price and fill candle. For a re-entry, fill starts the next leg. For an add, fill adds the fixed quantity to the still-active leg using the actual price.

## Candle Processing and Protective Stops

The default behavior acknowledges that daily OHLC data does not identify the exact intraday path:

- A protective stop attached to a newly filled entry or replacement stop attached to an add becomes eligible on the candle after the fill.
- If **Activate protective stop on fill candle** is checked, the new stop may trigger on the fill candle after the order fills.

For an active position with a pending add, the position's already-active stop is processed first. If it closes the position, the add is invalidated, its reservation is released, and it is not filled on that candle. If the position survives, the controller evaluates the add. When a fill-bar stop is enabled, only the newly activated or replacement stop receives the additional post-fill check; already-active stops are not processed twice.

There is one mandatory safety exception. If a long gaps open at or below its proposed stop, or a short gaps open at or above it, the entry fills at the improved opening price and immediately closes at that opening price. This prevents an invalid-risk position whose protective stop is already through the market, even when fill-candle stops were otherwise disabled. The rule also applies to a pending add that carries a replacement stop: after the add fills, a gap through that replacement stop closes the entire resulting position, matching the existing full-position replacement-stop behavior. A pending add without a replacement stop has no new gap-through check; its already-active stop was processed before the add. The review labels the safety exception as a gap-through-stop event.

## Cancellation and Invalidations

The user can cancel a pending order from either card view. Cancellation removes its line and badge, releases its reservation, records an event, and leaves any existing position unchanged.

A pending add is automatically invalidated if its position closes or becomes ineligible before fill. All remaining working orders are cancelled at simulation completion or hard exit. Replacing/removing a runtime ticker also cancels its order before removing the card. These paths must be idempotent so repeated cleanup cannot release the same reservation twice.

## Rewind and Replay

Portfolio snapshots will include every card's pending order and aggregate reservation state. Stepping backward restores the exact order lifecycle, card indicator, order line, and available buying power at that historical point. Replaying or starting a new run starts from the configured initial state with no interactive pending orders.

Order IDs and lifecycle records must remain stable within restored snapshots so a fill or cancellation is not duplicated after stepping backward and advancing again.

## Review and Reporting

Order activity records the following states with date, price, quantity, direction, card identity, and reason where relevant:

- placed
- filled
- manually cancelled
- automatically invalidated
- cancelled unfilled at simulation end
- gap-through-stop

Executed trades use the actual fill date and price. Never-filled orders do not create legs and are excluded from trade counts, win rate, profit factor, capital deployment, and P&L. Their lifecycle remains available in the portfolio review/report as order activity. Existing entry, leg, role, stock/index identity, and proxy-symbol reporting remain intact.

## Error Handling and Invariants

- Aggregate reserved buying power equals the sum of live working-order reservations within one-cent rounding tolerance and can never be negative.
- A pending order can transition to a terminal state only once.
- A fill cannot both debit cash and retain its reservation.
- A card cannot have two working pending orders.
- Missing card data for a portfolio date leaves an order working; it does not invent a fill.
- If state drift makes buying power unavailable despite a reservation, fail safely by invalidating the order, releasing any remaining reservation, recording the reason, and leaving the portfolio state coherent.
- Review and chart rendering failures must not alter order or cash state.

## Verification Strategy

Focused automated coverage will exercise pure limit-fill evaluation and controller integration:

- Long and short touch/no-touch fills.
- Opening gaps and price improvement.
- First eligibility on the candle after submission.
- Share and dollar sizing.
- Reservation, release, price-improvement remainder, and concurrent-order rejection.
- Manual cancellation and automatic invalidation.
- Initial entry, re-entry, and add fills.
- Existing-stop priority for pending adds.
- Default next-candle protective stop, optional fill-candle stop, and mandatory gap-through-stop handling.
- Rewind restoration without duplicate fills or releases.
- End-of-simulation cleanup.
- Actual fill data in review and exclusion of unfilled orders from performance metrics.

Manual verification will confirm the controls, pending badge, chart line, cancellation actions, expanded-card behavior, playback transitions, and review presentation for both stock and index cards.
