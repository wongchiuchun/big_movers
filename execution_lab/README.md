# Execution Lab

A local intraday execution mode launched from Chart Studies / big_movers. Its
core exercise is finding a useful entry-to-target reward/risk ratio against a
stop below the currently observed low of day, sizing that risk, and managing
the fills and exits as a random synthetic session unfolds.

**Implementation status: unverified.** At the user's request, no tests, import
probes, browser checks, benchmarks, or simulation smoke runs were performed.
The deferred checklist is [execution-lab-verification.md](../../docs/execution-lab-verification.md).

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
before starting the server. Dependency compatibility remains untested.

## Practice workflow

1. Start a random session. Blank date selects the latest valid US session;
   an explicit holiday/weekend is rejected. Blank seed creates a random seed,
   revealed in the completed review. One observed minute from the open gives
   initial context; the session begins paused at 09:31 ET.
2. Choose your target from the visible chart. Click the chart to set a target,
   limit entry or custom stop. Targets are planning markers, not automatic exits.
3. Set a risk budget and LOD buffer. The preview shows prospective reward/risk,
   risk per share, cash-capped shares, and planned dollar risk. Market entry
   estimates follow the current ask; a limit entry uses your selected price.
4. Queue the entry, then play or advance. Orders entered while paused have not
   executed. Status and account figures update from actual exchange messages.
5. Manage a fixed protective stop, partial market/limit exits, and working
   orders. Close all also cancels/settles a remaining entry. A new lower LOD
   never automatically lowers your existing stop.
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
- XNYS regular-session calendar, New York display timezone, holidays/early closes.
- Whole shares, USD cents, $0.01 grid, long-only cash, zero fees. Matching enforces
  available cash/inventory at the exchange, including in-flight executions.
- Market orders sweep available liquidity; unmatched remainder expires. Limit
  orders can rest and partly fill. Stops trigger on executed trades and can slip.
  Protective unfilled exits retry on subsequent prints, rather than invent fills.
- Protective stops are broker-side. They cancel/settle conflicting sell orders
  before exiting remaining inventory. Market orders already dispatched cannot
  be canceled. Late entry fills remain protected after a stop/close trigger.
- Every new entry requires an explicit entry/stop/target/risk plan. One position
  or pending entry at a time; no scale-ins, margin, shorting or settlement rules.
- No opening/closing auctions, extended hours, halts, NBBO, venue routing or
  borrowing. A full session is modeled, but performance is unmeasured.
- Ending freezes new background orders, settles in-flight human requests,
  expires residual orders and leaves open inventory marked separately. It
  never fabricates a closing liquidation.
- Initial R retains the original stop. At/below-stop entry fills trigger
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

Implementation plan: [2026-10-04-execution-lab.md](../../docs/superpowers/plans/2026-10-04-execution-lab.md).
