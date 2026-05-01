# P&L Calendar View — Design

**Date:** 2026-05-01
**Scope:** `big_movers/Big_movers.html`
**Status:** Draft for review

## Goal

Add a P&L calendar to both the **individual sim** and **portfolio sim** summary views in Big_movers.html. The calendar shows a colored cell per simulated day; clicking a day reveals that day's P&L change, equity, per-position contribution, and the events that fired.

## User-validated decisions

| Decision | Choice |
|---|---|
| Where the calendar lives | New "Calendar" tab inside the existing sim summary modal (individual); new collapsible section in the portfolio summary modal |
| Cell metric | $ change with green/red heat intensity scaled to that sim's range |
| Click behavior | Side detail pane in same modal: $ change, equity at close, per-position contribution, events list |
| Availability | Post-sim **and** mid-sim (📅 Calendar button on both live sim toolbars opens the modal in view-only mode) |
| Layout | Stacked month grids (Mon–Sun, weekends muted) |

## Architecture

One shared component, two adapters, two integration points.

```
                 ┌────────────────────────────────┐
                 │ Sim.UI.PnLCalendar             │
                 │   .render(host, model, opts)   │
                 │   .modelFromIndividual(sim)    │
                 │   .modelFromPortfolio()        │
                 └─────────────┬──────────────────┘
                               │ model
            ┌──────────────────┼──────────────────┐
            │                                     │
   ┌────────▼────────┐                  ┌─────────▼────────┐
   │ Individual sim  │                  │ Portfolio sim    │
   │ summary modal   │                  │ summary modal    │
   │ (Events|Calendar│                  │ (collapsible     │
   │  tabs)          │                  │  Calendar block) │
   └─────────────────┘                  └──────────────────┘
```

**Why this split:** the calendar is pure render-from-model. Each sim's quirks are isolated to a ~30-line adapter. Both adapters are pure functions of existing state, so they're trivial to unit-check.

## Data model (shared)

```js
{
  startDate: 'YYYY-MM-DD',
  endDate:   'YYYY-MM-DD',
  initialEquity: 25000 | null,   // null for individual sim
  days: [
    {
      date: 'YYYY-MM-DD',
      dollarChange: 240.50,
      pctChange: 0.86,            // null for individual sim
      equityClose: 25240.50,
      positions: { NVDA: 220.00, AVGO: 20.50 },
      events: [
        { type: 'add', symbol: 'NVDA', qty: 50, price: 900.0, note: '...' },
        ...
      ]
    },
    ...
  ]
}
```

The calendar grid paints a cell for every weekday between `startDate` and `endDate`. Days missing from `days[]` (holidays, weekends) render as muted "—" cells, not heat-colored.

## Adapters

### Portfolio — `modelFromPortfolio()`

Reuses the existing per-day series produced by `_appendCurves()` and exposed via `window.PortSim.Positions.curve()`. Each `_curve` entry is `{date, port, equity, cash, openCount, positions}` where `port` is **cumulative** total P&L.

- Daily $ change: `curve[i].port − curve[i-1].port` (first day uses 0 baseline)
- Per-symbol contribution: `curve[i].positions[SYM] − curve[i-1].positions[SYM]`
- Daily %: `dollarChange / initialEquity * 100`
- Events for day: walk `st.basket[].sim.eventsLog`, filter where `ev.date === day.date`

No new state. Reuses an existing source-of-truth that already powers the equity chart and CSV export.

### Individual — `modelFromIndividual(sim)`

The individual sim doesn't keep a per-bar series today. Add one tiny field:

- Initialize `sim.pnlSeries = []` in `createSim()` (next to `eventsLog`).
- After each advanced bar (same call site as `_updateExtremes` / `_updateIntradayExtremes`), `sim.pnlSeries.push({ date: bar.time, totalPnL: _computeTotalPnLAtBar(sim, bar) })`.

Then the adapter is the same shape as portfolio's: diff adjacent entries to get daily $ change. Events come from filtering `sim.eventsLog` by date.

## UI integration

### Individual sim summary modal (`#sim-summary-modal`)

Layout today is flat (hero → grid → legs → event log). We insert a 2-tab row between the grid and legs/log:

| Tab | Content | Default |
|---|---|---|
| Events | Existing `#sim-summary-log` | ✓ default (preserves muscle memory) |
| Calendar | New `#sim-summary-calendar` host |  |

Tab switching is a CSS class toggle on the modal — no rerender. Both panes are pre-rendered when the modal opens.

### Portfolio sim summary modal (`#portsim-summary-modal`)

Built dynamically in `_showSummary` (line ~15868). Append a single collapsible "📅 P&L Calendar" section below the per-symbol table. No tab system needed (nothing to compete with). Section is collapsed by default to keep the modal short; user expands to see the grid.

### Live "📅 Calendar" button

- Individual: `<button id="sim-btn-calendar">📅 Calendar</button>` in the existing sim transport row, alongside Export / Exit.
- Portfolio: equivalent button in the portfolio sim toolbar.
- Click opens the existing summary modal in **view-only mode**: Continue button hidden, sim is not paused or exited. Modal is dismissable normally; closing returns to the running sim.
- Modal content snapshots the model at open time. No live refresh — close and reopen to see the latest.

### Calendar component DOM

```
.pnlcal-root
├── .pnlcal-grid               # left side
│   └── .pnlcal-month          # one per month spanned
│       ├── .pnlcal-month-label   "April 2024"
│       ├── .pnlcal-weekdays      "M T W T F S S"
│       └── .pnlcal-days
│           └── .pnlcal-day [data-date="2024-04-17"]
│               ├── .pnlcal-day-num   "17"
│               └── .pnlcal-day-val   "+$240"
└── .pnlcal-detail             # right side, hidden until first click
    ├── .pnlcal-detail-date    "Apr 17, 2024"
    ├── .pnlcal-detail-totals  "+$340 · +1.2% · Equity $28,450"
    ├── .pnlcal-detail-pos     per-symbol contribution rows
    └── .pnlcal-detail-events  events fired that day
```

- Single delegated click handler on `.pnlcal-grid`, reads `data-date`, swaps detail pane content.
- Re-clicking the same day collapses the pane (toggle).
- On viewports narrower than 720px, detail pane stacks below grid instead of beside it.

### Heat color scaling

Per-sim, not global. `maxAbs = max(|day.dollarChange|)` over `days`. Cell opacity = `|dollarChange| / maxAbs`, clamped to `[0.15, 1.0]` so any nonzero day stays visible. `dollarChange === 0` renders with a thin neutral border, no fill.

## Edge cases

| Case | Behavior |
|---|---|
| Sim with 0 days played | `days = []` → calendar shows empty-state "No simulated days yet." |
| Symbol added mid-sim | Its first appearance has `positions[SYM] = curr − 0`, which is correct |
| Symbol fully closed mid-sim | Keeps appearing in detail pane with $0 contribution on subsequent days |
| Holidays / weekends | No entry in `days[]` → muted "—" cell, not heat-colored |
| Single-day sim | Calendar renders one cell; detail pane fully usable |
| Exit-before-end | Calendar shows whatever days had data |

## Error handling

- All adapter functions return a valid (possibly empty) model — never throw.
- `Sim.UI.PnLCalendar.render` no-ops if `host` is null or `model.days` is missing.
- If `LightweightCharts` were ever needed (it isn't — pure DOM), we'd guard like the existing equity chart does. Calendar uses no third-party charting.

## Testing

Manual verification (browser):

1. **Portfolio sim, 1-month basket** — calendar tab renders, every day has a cell, totals match the per-symbol table sum.
2. **Portfolio sim, 6-month basket** — multiple month grids stack, detail pane works for any day.
3. **Individual sim, full play** — same as above, single-symbol detail pane.
4. **Mid-sim Calendar button (both views)** — modal opens, sim continues ticking in background, modal dismisses cleanly.
5. **Click → click same day** — detail pane toggles closed.
6. **Empty sim (started, never played)** — empty-state message, no crash.

Where reasonable, add a small JS smoke check at the bottom of the file: a function that constructs a synthetic `_curve` and asserts `modelFromPortfolio()` produces the expected `days[]`. Same for `modelFromIndividual()` with a synthetic `sim`. These run only when `window.__pnlcal_test === true` so they don't fire in normal use.

## Risks

- **`_curve` not yet populated when modal opens mid-sim, day 0.** Mitigation: empty-state branch in the renderer.
- **`bar.time` format mismatch with `eventsLog[].date`** — both are ISO `YYYY-MM-DD` per existing code (verified at lines 9245, 14507 area). Adapter test catches drift.
- **Modal feels cramped on narrow screens.** Mitigation: detail pane stacks below grid under 720px.
- **Tab system collides with existing modal CSS.** The summary modal currently has no tabs; we add scoped classes (`.sim-summary-tabs`) to avoid touching shared `.fetch-modal-overlay` styles.

## Out of scope (v1)

- Persisting calendar state across sim runs.
- Comparing two sims side-by-side on the calendar.
- Exporting calendar as image (Screenshot button already covers the modal).
- Heatmap layout (Approach B/C from brainstorming) — revisit if year+ sims become common.
- Real-time calendar updates while modal is open mid-sim — closing/reopening is enough for v1.

## Files touched

- `big_movers/Big_movers.html` — single-file project. All changes here:
  - New `Sim.UI.PnLCalendar` module (CSS + JS) — ~250 lines
  - Tab row markup in `#sim-summary-modal` — ~10 lines
  - `pnlSeries` init + push in individual sim — 2 lines
  - `📅 Calendar` button + handler in individual sim toolbar — ~15 lines
  - Collapsible calendar section in portfolio `_showSummary` — ~20 lines
  - `📅 Calendar` button + handler in portfolio sim toolbar — ~15 lines

Total: roughly 300 lines of additions, zero deletions, no refactor of existing simulator code.
