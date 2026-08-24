# Entry Trainer Control Parity Design

## Goal

Make Entry Trainer use the established Individual Sim interaction model while preserving the trainer's masked, point-in-time exercise and three-attempt workflow.

## Current Problems

- Entry Trainer's policy disables rewind, adds, partial sells, and flat-position autoplay even though the shared Sim engine supports them.
- The Entry Trainer strip exposes `Wait` near the top of the chart while the familiar transport at the bottom is partly disabled.
- The whole chart toolbar is made inert, which also blocks the existing pop-out control.
- Simply removing the rewind restriction would restore only Sim-owned state. Entry Trainer also owns pending orders, order events, buying-power reservations, and completed-attempt records, so those could remain ahead of the rewound chart.

## Design

### Canonical Playback Controls

The existing bottom Sim transport remains the canonical playback surface. Entry Trainer explicitly permits flat-position autoplay while retaining the existing pause-on-attempt-completion behavior:

- `Play` advances continuously while the trainer is flat or in a position.
- `Forward` advances exactly one bar.
- `Back` rewinds exactly one saved bar transition.
- The Entry Trainer `Wait` action remains as a convenient one-bar alias for `Forward`; it no longer substitutes for or disables the bottom transport.

Playback still stops automatically for an attempt result, the ticker horizon, or another existing terminal condition.

### Reversible Policy State

The shared Sim controller will extend its policy adapter with two optional callbacks:

- `captureHistoryState()` returns serializable caller-owned state whenever the controller pushes a rewind snapshot.
- `restoreHistoryState(snapshot)` restores that caller-owned state when the controller steps back.

Sim snapshots continue to own chart, position, stop, event, marker, curve, and flat-policy lifecycle state. The flat-policy portion includes completed-leg deduplication, attempt-pending status, the current exit reason, and whether the horizon callback has fired. Restoring these fields ensures rewinding a stop, full exit, or horizon re-enables the appropriate controls and permits the completion callback to fire again if playback reaches that outcome again.

Entry Trainer's snapshot contribution owns only trainer-specific mutable state for the active ticker:

- pending order and order lifecycle events;
- batch order-state and reserved buying power;
- completed attempts for the active candidate;
- current result/horizon bookkeeping and any order retry notice.

The controller captures caller-owned state once at the start of every forward bar, before `beforeFlatStep` can expire, invalidate, retry, or fill a working order. If the callback does not consume the step, that captured state is attached to the normal Sim snapshot for the bar. If an atomic limit fill consumes the step, the same pre-step caller snapshot is supplied to the entry-commit checkpoint before the live order transitions to filled. Failed or blocked steps create no checkpoint, so Back never lands on a no-op state. The resulting history record always pairs pre-step Sim state with pre-step trainer state.

Entry submission and cancellation do not create same-bar history entries. They mutate the current paused bar, and the existing checkpoint that brought the playhead to that bar remains the Back boundary. Consequently Back still moves one bar, restoring the complete caller state from before that bar instead of first producing a same-bar undo step.

After a restore, Entry Trainer reconciles order reservations, refreshes the limit line and strip, and shows or hides the attempt result from restored state. Starting a subsequent attempt remains a rewind boundary, matching Individual Sim's existing behavior.

### Position Management

Entry Trainer stops setting `disableAdds` and `fullExitOnly` in its Sim policy. It reuses the existing Individual Sim actions and modals:

- `Add` increases the active long position and uses existing buying-power validation and optional stop replacement/trailing controls.
- `Sell` permits partial or full exits.
- `Move Stop` retains the existing stop-management behavior.
- A completed attempt is recorded only when the position is fully closed or stopped out; adds and partial sells remain events within that attempt.

No separate Entry Trainer execution engine or duplicate trade modal is introduced.

### Expanded View

The existing `popout-btn` is permitted during Entry Trainer. The trainer will lock unrelated toolbar actions individually instead of making the entire chart topbar inert. The existing `sim-popout` layout supplies the expanded chart-left/simulator-right view and its existing Escape behavior.

### Safety and Invariants

- Future bars remain masked through the existing chart-cutoff path.
- Rewind never leaves a future pending-order fill, reservation, or attempt summary attached to an earlier chart bar.
- Long-only and maximum-three-attempt rules remain unchanged.
- Exact-price limit entry behavior and daily-OHLC execution conventions remain unchanged.
- Other Sim callers that do not provide policy-history callbacks retain their current behavior.
- Entry Trainer keeps `Jump to Entry` disabled independently from Back; resetting to the first bar would bypass the trainer-owned restore contract and the current attempt boundary.

## Verification

Verify the following focused flows:

1. Flat Entry Trainer playback responds to Play, Forward, Wait, and Back.
2. Rewinding across limit placement, cancellation, fill, stop, and attempt completion restores both Sim and trainer-owned state.
3. Add and partial Sell use the existing modals and appear in the attempt event history.
4. Pop-out opens and closes during Entry Trainer without unlocking unrelated controls or revealing future bars.
5. Ordinary Individual Sim behavior remains unchanged when no policy-history callbacks are supplied.
