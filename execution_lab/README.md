# Execution Lab

A local intraday execution mode launched from Chart Studies / big_movers. Its
core exercise is finding a useful entry-to-target reward/risk ratio against a
stop below the currently observed low of day (above HOD for shorts), sizing that risk, and managing
the fills and exits as a random synthetic session unfolds.

**Implementation status: essential automated checks passed.** After initially
deferring verification, the user authorized essentials covering actual
ABIDES execution/risk/stops, worker protocol, Flask integration and shutdown
regression passed, along with syntax/compilation checks. Browser behavior,
full-session performance and the broader suite remain unverified.
Commands/results and the deferred checklist are in
[execution-lab-verification.md](../../docs/execution-lab-verification.md).

## Install and open manually

From the workspace:

```bash
bash big_movers/execution_lab/setup.sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 big_movers/Big_movers_server.py
```

If Chart Studies is already running, restart that server using your usual
method so it picks up the new blueprint. Open `http://localhost:5051/` and
click **Execution Lab**, or go directly to `http://localhost:5051/execution-lab/`.
If your server uses a different port, use that port for both pages.

The setup script creates `.venv/` in this directory. It does not change the
existing Flask environment. To use a different supported Python executable:

```bash
EXECUTION_LAB_SETUP_PYTHON=/path/to/python3 bash big_movers/execution_lab/setup.sh
```

The default setup uses the installed system Python 3.13. The worker's
dependencies are NumPy, pandas, SciPy and exchange-calendars. No Gym/Ray or
pomegranate is installed. To point the server at an alternate worker
environment, set `EXECUTION_LAB_PYTHON` to that environment's Python executable
before starting the server. The installed Python 3.13 environment passed the
essential worker tests; other dependency/version combinations remain untested.

## Practice workflow

1. Start a random session. Blank date selects the latest valid US session;
   an explicit holiday/weekend is rejected. Blank seed creates a random seed,
   revealed in the completed review. One observed minute from the open gives
   initial context; the session begins paused at 09:31 ET.
   Regime, volatility and liquidity each default to **Random**. Choose specific
   conditions for focused practice or leave them untouched for a blind session.
   Randomly chosen conditions remain hidden until review. Settings lock during
   the session; repeat copies the same selections and seed.
2. Click **Long** or **Short** in the position strip. The entry dialog offers
   shares, dollar amount or dollar risk sizing and market/limit orders. Use
   **Pick** to select a limit entry, stop or optional target on the chart.
3. Default protection is LOD minus buffer for longs, HOD plus buffer for shorts.
   Manual, percent, 5/10-bar extreme, ATR(14), EMA snapshot/trail and session-base
   stops are available. Candle strategies require completed one-minute bars.
   Preview shows notional and risk; an optional target adds reward/risk.
   Targets remain planning markers, not automatic exits.
4. Submit directly, including while paused. The worker processes a bounded
   50ms exchange interval; limits can remain working and fills depend on actual
   liquidity. Play or advance to let the market unfold.
5. Use **Sell/Cover**, **Add**, **Move Stop**, or **Close**. Sell/Cover offers
   All/Half/Third quantities and market/limit exits. Add stays in the current
   direction. Move Stop adds or replaces levels; stop chips offer Edit/Delete.
   Partial stops use the original entry size; 100% exits all remaining shares,
   including adds. The initial fallback cannot be deleted. A new LOD/HOD does
   not move a fixed stop; EMA auto-trail tightens at advance boundaries.
6. Finish and review. Inspect planned versus actual initial risk, entry
   slippage, fill-based reward/risk, realized R, stop edits, and partial exits.
   Saved reviews persist locally and can be exported as JSON or used to copy
   the seed/date/cash for another attempt.

Waiting, not entering, and accepting a disciplined stop are useful practice
outcomes. A high prospective ratio does not establish a likely profit.

## Execution model and limits

- Vendored JPMC ABIDES kernel and matching engine, pinned to
  `f9cbe51342b7dedd9587e4e069040d68a5c6477f`; BSD license in `vendor/`.
- Custom seeded background market makers and trading agents drive one synthetic
  instrument. This is not a calibrated AAPL/NVDA simulation or historical replay.
- Regimes influence drift/order flow: uptrend, downtrend, opening-anchor range,
  or a smoothly changing reversal. They do not guarantee profitable direction.
  Low/normal/high volatility scales with initial stock price and retains the
  stronger-open/modest-late-session envelope. Deep/normal/thin liquidity changes
  background order sizes. The updated generator is model version 2; earlier
  review seeds do not reproduce their original paths under this version.
- XNYS regular-session calendar, New York display timezone, holidays/early closes.
- Whole shares, USD cents, $0.01 grid, zero fees. Longs use available cash;
  shorts restrict proceeds and reserve 100% entry-notional collateral. Losing
  covers may create a cash debit, blocking new entries. Matching enforces
  available collateral and direction-aware exit quantities, including in-flight fills.
- Market orders sweep available liquidity; unmatched remainder expires. Limit
  orders can rest and partly fill. Stops trigger on executed trades and can slip.
  Protective unfilled exits retry on subsequent prints, rather than invent fills.
- Protective stops are broker-side. They cancel/settle conflicting orders
  before exiting remaining inventory. Market orders already dispatched cannot
  be canceled. Late entry fills remain protected after a stop/close trigger.
- Every new entry requires a stop and size; target and rationale are optional.
  One direction at a time, with same-direction adds after working orders settle.
  Close first to reverse. Short collateral is simplified, with no real broker
  margin, settlement, locate, borrow fees or SSR model.
- No opening/closing auctions, extended hours, halts, NBBO, venue routing or
  borrowing. A full session is modeled, but performance is unmeasured.
- Ending freezes new background orders, settles in-flight human requests,
  expires residual orders and leaves open inventory marked separately. It
  never fabricates a closing liquidation.
- Initial R retains the original stop, including risk contributed by adds.
  Entry fills crossing the stop trigger
  protection and make actual-risk/R metrics unavailable; dollar P&L remains.
- MFE/MAE in review are observed dollar P&L excursions for the trade including
  partial realized exits. Equity/drawdown are sampled at advance boundaries.
- Playback pauses when the tab is hidden. Refresh reconnects to a running
  worker; server/worker restart loses an active in-memory session. Completed
  reviews survive. One active session is shared across tabs.

## Files and troubleshooting

`data/<session-id>.json` stores completed reviews, commands, fills, configurations
and seed. `data/worker.log` contains worker diagnostics. Neither is written into
existing study annotations, historical CSVs or simulator records.

Missing environment: run setup above. Simulation failure/timeout: playback
stops and the UI shows the error; restart Chart Studies before another session.
Do not repeatedly resubmit a request after a network interruption; refresh
first to see whether the worker accepted it. Command IDs make exact retries
idempotent. Advances are bounded to at most 60 simulated seconds per request;
pause takes effect after an already in-flight request completes.

Current interaction plan: [direct orders](../../docs/superpowers/plans/2026-10-04-execution-lab-direct-orders.md).
Original implementation plan: [2026-10-04-execution-lab.md](../../docs/superpowers/plans/2026-10-04-execution-lab.md).
