# Shorts + Stop Strategy Presets — Execution Plan

> Living spec for adding short-selling support to single-ticker Sim and PortSim,
> bundled with FEATURE_PLAN.md item #2 (Stop Strategy Presets) since both depend
> on the same direction-aware primitives.
>
> Reviewed by Codex (May 2026). All cited line numbers are from `Big_movers.html`
> at branch base `e356b59` (main, May 2026).
>
> Cross-references:
> - `ROADMAP.md` — strategic framing (training simulator, not backtester)
> - `FEATURE_PLAN.md` — item #2 (Stop Strategy Presets) is folded into this plan
> - `CLAUDE.md` — codebase orientation, gotchas, design system

---

## Goal

Add full short-selling support to single-ticker Sim and PortSim. Ship Stop
Strategy Presets in their direction-aware form on the same release. Zero
regressions to existing long-only saved reviews.

## Non-goals (explicit, per user)

- Borrow cost, locate fees, hard-to-borrow flags, dividends owed
- Forced buy-in / squeeze events
- Margin leverage > 1:1 (no overshorting)
- Cross-position margin netting (short proceeds fenced per-position by design)

This is a training simulator, not a brokerage emulator.

---

## Locked-in design choices

1. **Per-leg direction.** `legs[i].direction` carries it. Stop-out re-entry
   can flip long ↔ short on the same ticker.
2. **Default direction.** Entry modal pre-selects from `metadata.direction`
   (read once at modal open; does NOT cascade to existing legs after).
3. **Short cash bucket: fenced per-position.** Each short's proceeds are
   locked to that position until cover. No pooling between shorts; no
   funding new longs.

---

## Architecture — three primitives built in P0

### A. `Sim.Direction` adapter

Single source of sign-truth. ~40 lines. All sign-sensitive operations route
through this.

```js
Sim.Direction = (function(){
  const dir = (d) => d === 'short' ? -1 : 1;
  return {
    sign: dir,
    initialRiskPerShare: (d, entry, stop) => (d === 'short' ? stop - entry : entry - stop),
    pnlPerShare:         (d, exit, avg)   => (exit - avg) * dir(d),
    stopFires:           (d, bar, stopPx) => d === 'short' ? bar.high >= stopPx : bar.low <= stopPx,
    fillAtStop:          (d, bar, stopPx) => d === 'short' ? Math.max(bar.open, stopPx) : Math.min(bar.open, stopPx),
    ratchet:             (d, prev, cand)  => d === 'short' ? Math.min(prev, cand) : Math.max(prev, cand),
    intradayBetterPnL:   (d, bar, qty, avg, real) => real + qty * (d === 'short' ? bar.low  - avg : bar.high - avg) * dir(d),
    intradayWorsePnL:    (d, bar, qty, avg, real) => real + qty * (d === 'short' ? bar.high - avg : bar.low  - avg) * dir(d),
    stopValidates:       (d, entry, stop) => d === 'short' ? stop > entry : stop < entry,
    sortStopsForFire:    (d, stops) => stops.slice().sort((a,b) => d === 'short' ? a.price - b.price : b.price - a.price),
  };
})();
```

### B. `PortfolioValuation.markPosition(entry, lastClose)`

Replaces three duplicated equity formulas (`15421`, `19387`, `25206`).
Returns `{longMTM, shortLiability, lockedProceeds}`. Single source of
equity-truth.

### C. `ShortLocks.{applyOpen, applyCover, applyClose}`

Owns partial-cover allocation math. Settles realized P&L to `state.cash` on
every cover so equity stays continuous.

**Worked example: short opened 100sh @ $100.**

- `applyOpen({legId, shares: 100, entry: 100})` →
  `shortLocks[legId] = {shares: 100, proceeds: 10_000, avgEntry: 100}`.
  `state.cash` unchanged.
- `applyCover({legId, qty: 50, fillPx: 90})`:
  - allocate proceeds proportionally: `10_000 × 50/100 = 5_000`
  - cover cost: `50 × 90 = 4_500`
  - realized: `5_000 − 4_500 = +500` → credit `state.cash += 500`
  - remaining lock: `{shares: 50, proceeds: 5_000, avgEntry: 100}`
- `applyClose(legId)`: full cover variant, removes lock entry.

**Sanity check (concern 4 from Codex):** $100k cash, open 100sh short @ $100,
lastClose = $100.
Equity = `100_000 + (longMTM=0) + (lockedProceeds=10_000) − (shortLiability = 100×100 = 10_000)` = **$100,000**. ✓
At lastClose = $90: shortLiability = `100×90 = 9_000`.
Equity = `100_000 + 0 + 10_000 − 9_000` = **$101,000**. ✓

### D. Stable `legId` (minted at `startNewLeg`)

Promoted from P6 to P0 because everything downstream keys off it: locks,
snapshots, exports, markers, replay, step-back undo.

---

## Phase order (after Codex review)

```
P0 → P1 → P3 → P2 → P6 → P5 → P4 → P7 → P8
```

Reasoning:
- **P3 before P2** so stop presets read a real direction (not undefined).
- **P6 before P5/P4/P7** so on-screen equity, exports, and saved reviews
  share the centralized valuation helper.
- **P5 after P1** so short-side R-targets sit at correct prices, not just
  flipped arrow direction.
- **P8 last** but its tests are *written* in P0 and used as merge gates
  throughout.

---

## Phase 0 — Foundation, tests, helpers (½ day)

**Add (no behavior change yet):**

1. `Sim.Direction` module after `Sim.StopRules` (~`Big_movers.html:10915`).
2. `PortfolioValuation.markPosition()` helper.
3. `ShortLocks.{applyOpen, applyCover, applyClose}` module.
4. `direction: 'long'` default field on every entry to `legs[i]` (in
   `_legSnapshots` at `:24516–24590` and on every archived leg in
   `continueSim`).
5. Stable `legId = 'leg_' + Math.random().toString(36).slice(2,10)` minted at
   `startNewLeg`.
6. `state.shortLocks = {}` in PortSim init (`:18446`).
7. Saved-review loader migration: any leg without `direction` reads as
   `'long'`; any review without `shortLocks` reads as `{}`.

**Test scaffolding (`tests/sim_shorts.test.html`)** — six failing tests
that go red first, green at the end of the corresponding phase. These are
the merge gate:

| Test | Phase that turns it green |
|---|---|
| Short initial risk = `shares × (stop − entry)` | P1 |
| Short stop fires on gap-up: fill = `max(open, stop)` | P1 |
| Multi-stop partial cover ordering: lower stop fires first | P1 |
| Short manual close P&L = `(avg − fill) × qty` | P1 |
| Short end-bar force close uses cover semantics | P1 |
| Step-back undo restores `shortLocks` deep-cloned | P6 |
| Long sim on price-inverted bars ≡ short sim on original bars | P1 |
| Equity-equivalence: 1L + 1S = sum of two single-sim runs | P6 |
| v1 saved review (no direction, no shortLocks) replays byte-for-byte | P7 |

**Acceptance:** existing long flow unchanged; saved reviews load
identically; tests are red.

---

## Phase 1 — Sim core direction-aware (1 day)

Route every long-baked Sim core site through `Sim.Direction`. Sites Codex
verified plus the original inventory:

| Line | Current (long-only) | After |
|---|---|---|
| 10044 | `entry.price - entry.stop` | `Sim.Direction.initialRiskPerShare(direction, entry.price, entry.stop)` |
| 10036 | `console.warn('only long supported')` | delete |
| 10138-42 | hardcoded `bar.low/bar.high` | `intradayBetterPnL/intradayWorsePnL` |
| 10153 | `b.price - a.price` | `Sim.Direction.sortStopsForFire(direction, active)` |
| 10157 | `if (bar.low > stop.price) continue` | `if (!stopFires(direction, bar, stop.price)) continue` |
| 10158 | `Math.min(bar.open, stop.price)` | `fillAtStop(direction, bar, stop.price)` |
| 10162 | `(fillPx - avgCost) * sellQty` | `pnlPerShare(direction, fillPx, avgCost) * sellQty` |
| 10196-97 | intraday MFE/MAE | route through adapter |
| 10201 | sell action P&L | `pnlPerShare(direction, fillPx, avgCost) * wantQty` |
| 10259 | end-bar force close P&L | adapter |
| 10309 | `closeAt` manual close P&L | adapter |
| 10380 | sell-action close P&L | adapter |
| 10102 | trail ratchet `>` only | `ratchet(direction, prev, cand)` |
| 14322-385 | single-sim R-star marker placement | adapter (R-target side flips for shorts) |
| 14412-13 | exported curve highs/lows | adapter |
| 14923 | `createSim({direction: 'long'})` | pass modal-selected direction |
| 18723 | `createSim({direction: 'long'})` | pass modal-selected direction |
| 18850 | `startNewLeg({direction: 'long'})` | pass modal-selected direction |
| 19123-154 | `_pushSnapshot` | deep-clone `shortLocks` for step-back |
| 20326-348 | PortSim R-star marker engine | adapter |
| 21232 | PortSim R-star marker engine (cont.) | adapter |

**Symmetry test refinement:** percent-based presets are NOT symmetric under
additive bar-mirroring. The symmetry harness uses *absolute-distance*
presets only (e.g., "$1.50 below entry"). Percent presets get their own
test using multiplicative inverse.

**Acceptance:** all P0 tests except step-back, equity-equivalence, and v1
replay are green.

---

## Phase 3 — Entry / setup modals (1 day) [moved earlier]

- Direction radio in `showSetupModal`, `showNewLegModal`, PortSim per-row
  setup. Default value reads `getMeta(currentMoveRow).direction || 'long'`.
- **Read-once semantics:** changing study metadata mid-sim does NOT mutate
  `legs[i].direction`. Legs are executed facts.
- Validation routes through `Sim.Direction.stopValidates` at line `11595`
  (`showAddModal`) and equivalents in `showSetupModal` / `showNewLegModal`.
  Error: "Stop must be above entry for short" / "below entry for long".
- Risk-$ / Distance-% recompute live via
  `Sim.Direction.initialRiskPerShare`.
- PortSim setup row: when row direction = short, size validator caps short
  notional at current `state.cash` (1:1, no leverage). Submit calls
  `ShortLocks.applyOpen` instead of debiting cash.

**Acceptance:** every entry-modal field updates live for both directions;
submit blocked when validation fails.

---

## Phase 2 — Direction-aware StopRules + Stop Strategy Presets (2 days)

(Now runs after P3 so direction is always present.)

- All `Sim.StopRules.*Below` become direction-aware:
  - `pctOffset(d, price, pct)` returns `price * (1 - dir*pct)`
  - `atrOffset(d, bars, idx, k)`
  - `swingOpposite(d, bars, idx, n, buffer)` — for short, `max(high)` over
    last N bars + buffer
  - `baseOpposite(d, symbol, year)` — read `pivot.base_low`/`base_high`
    from `ai_classifications.json`. **Codex confirmed neither field
    exists**, so always compute from bars: `for d='long': min(low) over
    bars[base_start..base_end]; for d='short': max(high)`.
  - `emaOffset(d, bars, idx, period, k)`
- **Fix off-by-one bug** at `10948–10967`: base-date mapping uses "previous
  bar" for both `base_start` and `base_end`, leaking one pre-base bar on
  non-trading-day boundaries. Use `first bar where date >= base_start` and
  `last bar where date <= base_end`.
- Stop preset dropdown labels switch by direction:
  - Long: "Manual / % below entry / ATR below / Below 5-bar low / Below
    10-bar low / Below base low"
  - Short: "Manual / % above entry / ATR above / Above 5-bar high / Above
    10-bar high / Above base high"
- Same picker on PortSim per-row setup (`~:2600` markup, JS handler
  `~:11286`).

**Acceptance:** synthetic table tests — for each preset × direction,
computed stop matches hand-calculated value.

---

## Phase 6 — PortSim cash & equity centralization (1 day) [moved earlier]

- Replace `Cash.debitInitialEntry` (`:15368`) with
  `Cash.openPosition(direction, ...)`:
  - Long: debit cash (today's path).
  - Short: don't touch cash; call `ShortLocks.applyOpen`.
- Replace `Cash.creditManualClose` with
  `Cash.closePosition(direction, legId, fillPx)`:
  - Long: credit cash (today's path).
  - Short: call `ShortLocks.applyCover`/`applyClose`.
- `_renderAll` (`:15421`), `_portfolioSnap` (`:19387`), `_buildMeta`
  (`:25206`) all delegate to `PortfolioValuation.markPosition`. **No more
  duplicated equity formulas.**
- **Same-bar flip ordering invariant:** when a long stops out and the user
  selects re-entry as short on the same bar, ordering is `stop fires →
  cash settles → next bar processes new entry`. Same-bar new-leg submit
  must defer to next `advanceTo` call. Asserted in test.
- Invariants asserted after every cash mutation in dev mode:
  - `state.cash >= 0`
  - `Σ shortLocks[k].proceeds == Σ shortLocks[k].shares × shortLocks[k].avgEntry` (until any cover; re-derived after each cover)
- `_pushSnapshot` deep-clones `shortLocks` (cf. P1 site at 19123).

**Acceptance:** equity-equivalence test green; step-back undo test green;
invariants never trip.

---

## Phase 5 — Chart visualization (½ day)

- Entry / add / sell / cover / stop markers route arrow shape + position
  through `direction`:
  - Long entry: `position:'belowBar', color:'#6ee7b7', shape:'arrowUp', text:'L'`
  - Short entry: `position:'aboveBar', color:'#fb7185', shape:'arrowDown', text:'S'`
  - Cover/sell markers: opposite arrow, neutral color.
- Stop-line via `createPriceLine` (Codex confirmed LWC v3.8.0 accepts
  arbitrary prices). The bug is **semantic only**: `−1R (init)` labels and
  R-target colors. Recompute label and color from `direction`.
- Per-card border tint: 2px green-tint on long, red-tint on short.

**Acceptance:** opening a known short setup shows red downward arrows
above the entry bar and stop line above the entry price.

---

## Phase 4 — Mid-trade actions (½ day)

- Engine event types stay neutral: `add`, `sell`, `stop`, `close`. Add a
  `direction` field to every event. Render labels at the **view layer
  only**: long shows "Sell"/"Add"; short shows "Cover"/"Add Short". Don't
  fork engine types.
- Single-sim buttons (`:5870–5880`) and PortSim card buttons
  (`:5510–5520`): label updates per active leg's direction on every
  `advanceTo` tick.
- Stop-out re-entry modal exposes direction radio defaulted to **opposite**
  of just-closed leg (since "broke down → flip short" is the common case).
  User can flip back.
- Per-leg direction is locked once the leg is open; flip only on
  re-entry.

**Acceptance:** button labels follow active-leg direction; stop-out
re-entry surfaces direction flip with sensible default.

---

## Phase 7 — Exports & saved review backward-compat (½ day)

- `_legSnapshots` (`:24516–24590`) adds `direction` per row.
- `_extractTradesFromSim` (`:13341`, `:13897`) emits per-leg direction, not
  session-level. (Codex flagged today's behavior: portfolio sessions
  hardcode long, so post-flip legs export wrong.)
- `_buildMeta` (`:25206`) emits `shortLocks` snapshot in the saved-review
  payload, via `PortfolioValuation.markPosition`.
- Markdown export `_buildMD` (`:25482`): add `Dir` column to leg table
  ('L' / 'S').
- Saved-review loader: tolerates absent `direction` (= 'long') and absent
  `shortLocks` (= `{}`); silent-migrate on first save.
- **Backward-compat assertion:** when a v1 review (no direction, no
  shortLocks) is loaded, the replay equity curve must reproduce the saved
  equity byte-for-byte (within rounding). Self-check fires once per v1
  review.
- PDF print (`_renderPrintAll`, `:25669`): direction badge next to each
  leg.

**Acceptance:** existing saved reviews open and render identically; v1
replay assertion passes; new reviews carry full short state.

---

## Phase 8 — Verification (½ day)

1. All P0 tests green.
2. Symmetry test green.
3. Equity-equivalence test green.
4. **Manual end-to-end on a real tagged-short setup**: entry → add →
   trail → partial cover → stop → flip to long → close. Compare equity
   curve to hand math. (Codex's recommendation; required gate.)
5. Final code review of the entire branch.

---

## Net effort (post-Codex)

~9 working days. The slip from the original ~7d estimate is the five
newly-discovered touch points (R-star markers, three duplicated equity
formulas, step-back snapshot, CSV export, three hardcoded-long submit
paths) and the centralized valuation helper.

## Deferred to follow-up (out of scope here)

- 🪁 `Apply Trail` mid-trade button — entry-time trail spec only for v1
- Position sizing rules (FEATURE_PLAN #4)
- Decision log (FEATURE_PLAN #5)
- Hide-future-bars (FEATURE_PLAN #1)
- Borrow cost / leverage / squeeze model

## Risk register

- **R1: Single 26k-line HTML.** No parallel implementer agents on the same
  region — sequential per phase.
- **R2: Per-leg direction × shared cash.** Mitigated by per-position
  fenced lock + same-bar ordering invariant.
- **R3: ai_classifications.json missing base_high/base_low.** Confirmed by
  Codex; computed from bars in `baseOpposite`. Off-by-one in date mapping
  fixed in P2.
- **R4: Saved-review backward compat.** Mitigated by v1 replay assertion
  in P7.
- **R5: Symmetry test breakage on percent presets.** Mitigated by
  restricting symmetry harness to absolute-distance presets; percent gets
  its own multiplicative test.

---

## Worktree

`/.claude/worktrees/shorts-feature` on branch `feature/shorts-and-stop-presets`
(off `main` at `e356b59`).

Tests live at `tests/sim_shorts.test.html` (created in P0). Tests are the
merge gate — work only ships if all are green.
