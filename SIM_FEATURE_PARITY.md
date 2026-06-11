# Sim Feature Parity — Blind / Individual / Portfolio

Single-file webapp (`Big_movers.html`, ~29k lines). Three sim modes share more
than the surface suggests. This doc maps what each mode has, what's missing,
and what would be worth syncing.

## TL;DR

The biggest gap is on the **Portfolio** side: when a leg closes, there's no
rich per-trade summary modal or per-trade notes/MD export — the user just
sees the PortSim review panel. Individual sim has both. Recommended top
priority: bring `Sim.UI.showSummaryModal` + `Sim.Review` into PortSim's
leg-close flow.

---

## The three modes

| Mode | Namespace | What it is |
|---|---|---|
| **Individual** | `Sim.Ctrl` + `Sim.UI` + `Sim.Review` + `SimSaved` + `SimStats` | One ticker. Manual entry / add / sell / movestop. Step bar-by-bar. End-of-trade summary modal. |
| **Blind** | `SimBlind` (drives `Sim.Ctrl`) | Same as Individual but masks future bars; user enters when they want to commit. |
| **Portfolio** | `PortSim` + `PortSim.Ctrl` + `PortSim.Review` + `PortSim.CardChart` + `PortSim.Index` | Basket of tickers stepping in unified time. Per-ticker cards. Portfolio-level equity, cash, drawdown. |

## Shared engine (key finding)

All three modes drive the **same core sim engine**:

- `Sim.advanceTo(sim, bars, targetIdx)` — bar advancer (line ~10515)
- `Sim.queueAction(sim, action)` — queue add/sell/movestop (line ~10387)
- `Sim.createSim(...)` / `Sim.continueSim(...)` / `Sim.startNewLeg(...)`

PortSim calls `window.Sim.advanceTo(entry.sim, entry.bars, barIdx)` per ticker
each portfolio tick (line 21470) and uses `window.Sim.queueAction(...)` for
user actions (lines 21135, 21147, etc.). Blind sim uses `Sim.Ctrl.openSetup`
with a `'BLIND'` moveKey (line ~16248).

**Implication:** any fix to the shared engine automatically propagates to all
three modes. Recent fixes:

- ✅ `stop.pct >= 0.9999` ⇒ liquidate full current `qty` (line ~10440 in
  `_processStopOnBar`) — inherits to PortSim and Blind automatically.
- ✅ Snapshot-stack step-back in `Sim.Ctrl._stepBack` — inherits to Blind
  (which uses `Sim.Ctrl`). PortSim already had its own snapshot stack
  (`_pushSnapshot` at ~20135).

---

## Feature matrix

| Capability | Blind | Individual | Portfolio | Notes |
|---|:-:|:-:|:-:|---|
| **Setup** (entry, size mode, stop, EMA-trail, direction, equity) | ✓ | ✓ | ✓ | Identical setup modal under the hood |
| **Transport: play / pause / speed** | ✓ | ✓ | ✓ | |
| **Transport: step forward 1** | ✓ | ✓ | ✓ | |
| **Transport: step back 1** | ✓ | ✓ | ✓ | All snapshot-based now (post-fix) |
| **Step-back preserves user actions** | ✓ | ✓ (just fixed) | ✓ | Was the leg-data-loss bug |
| **Jump to entry** | ✗ | ✓ | ✗ | Minor UX. Individual only |
| **Add / partial sell / move stop** | ✓ | ✓ | ✓ | Shared via queueAction |
| **Close all (manual)** | ✓ | ✓ | ✓ | |
| **Multi-leg / re-entry (continue, +New Entry)** | ✓ | ✓ | ✓ | |
| **Stop semantics (initial + moved + EMA-trail)** | ✓ | ✓ | ✓ | Shared engine |
| **100% stop closes full current qty (post-add)** | ✓ | ✓ | ✓ | Shared engine fix |
| **Visual: R-levels, R-stars, leg markers, stop lines** | ✗ (playback-only) | ✓ | ✓ | Blind hides intentionally |
| **Direction-aware UI (long/short labels & arrows)** | ✓ | ✓ | ✓ | |
| **End-of-trade summary modal (R, P&L, MFE/MAE, events, calendar)** | partial | ✓ | **✗** | **Gap: PortSim leg close has no modal** |
| **Per-trade notes + Markdown export** | ✗ | ✓ (`Sim.Review`) | partial (`PortSim.Review` is portfolio-level, not per-leg) | **Gap** |
| **Save / load sim runs** | ✗ | ✓ (`SimSaved`) | ✓ (`PortSim.Review` save/load) | |
| **Stats aggregation across runs** | ✗ | ✓ (`SimStats`) | ✓ (PortSim feeds `SimStats`) | |
| **Screenshot of chart with annotations** | ✓ | ✓ | ✓ | |
| **Replay (re-run from day 0)** | ✓ (implicit) | ✓ (button in summary) | **✗** | **Gap** |
| **Equity curve / P&L over time** | ✗ | ✓ (in summary tab) | ✓ (Index pane + per-card curve) | |
| **Benchmark overlay (SPY/index)** | ✗ | ✗ (only B&H number in summary) | ✓ (`PortSim.Index`) | **Gap on individual** |
| **Blind mode (mask future bars)** | ✓ (the whole point) | ✗ | ✗ | Could be ported to PortSim |
| **Trade list / events log filtering** | ✗ | ✓ | ✓ | |

---

## Recommendations (ranked)

### High — close the biggest UX gap on PortSim leg close

#### 1. Per-leg summary modal in PortSim
**What:** When a PortSim leg closes (stop or manual close), open
`Sim.UI.showSummaryModal` with that leg's derived data — same modal
individual sim shows. Currently PortSim leg-close is silent (or only
visible in the Review panel later).

**Effort:** ~80 lines. Reuse the existing modal; just need to compute
derived stats for that single leg and call `showSummaryModal`. The
`onReenter` / `onSave` / `onAddToStats` handlers wire to PortSim
equivalents.

**Path:** In `PortSim.Ctrl`'s leg-close detection (after `Sim.advanceTo`
returns events with `type === 'stop'` or `type === 'close'`), pause and
fire the modal.

#### 2. Per-leg notes + MD export in PortSim
**What:** Same `Sim.Review` module, scoped per (portfolioRunId, ticker, legId).

**Effort:** ~30 lines once #1 is in. The Notes tab already exists in
`sim-summary-modal`. Just point the runId to a portfolio-aware key.

### Medium

#### 3. Replay button in PortSim
**What:** "Re-run this portfolio from day 0 with the same setup." Useful
for iterating entries across a basket without rebuilding setups.

**Effort:** ~50 lines. PortSim already snapshots full state — replay is
pop-to-empty + re-init from saved baseline.

#### 4. Benchmark line on individual sim summary
**What:** Add a SPY (or selected index) overlay to the equity curve shown
in the summary. Today individual sim only shows a B&H % number. PortSim
has a full Index pane; we can borrow that data source.

**Effort:** ~60 lines. Uses existing `/api/ohlcv?symbol=SPY` cache.

### Low / defer

#### 5. Jump-to-entry button in PortSim
Individual has it; PortSim doesn't. Minor.

#### 6. Blind mode for PortSim
Mask future bars across all basket cards. Conceptually clean (entire chart
mask is a per-card transformation), but a noticeable feature. Defer until
explicitly requested.

#### 7. Visual aids in Blind sim
By design Blind hides chart adornments. Don't change.

---

## Decisions needed

1. **Sync #1 + #2 (per-leg summary + notes/MD in PortSim)?** — yes / no / part of it
2. **Sync #3 (Replay in PortSim)?** — yes / no / later
3. **Sync #4 (Benchmark on individual summary)?** — yes / no / later
4. **Anything else from the matrix worth elevating?**

Tell me what to build and in what order.
