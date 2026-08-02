# Portfolio Expanded Weekly and Long EMAs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent Daily/Weekly and optional 100/250 EMA controls to each Portfolio Simulation expanded ticker chart without revealing future bars.

**Architecture:** Keep chart preferences on each live basket entry and centralize the expanded modal's displayed-bar/marker transformation in pure helpers. Rebuild the modal chart when preferences change, using only the already-revealed daily slice and the existing weekly resampler.

**Tech Stack:** Inline browser JavaScript/CSS/HTML, Lightweight Charts 3.8, Node.js `node:test`, agent-browser.

---

### Task 1: Define timeframe transformations test-first

**Files:**
- Create: `tests/portfolio_expand_timeframe.test.cjs`
- Modify: `Big_movers.html:24540-24870`

- [ ] Write tests that extract the expanded-modal helpers and verify daily pass-through, Monday-keyed weekly OHLCV aggregation, incomplete current weeks, cross-year weeks, and no bars after the playhead.
- [ ] Write marker tests proving daily event dates map to the containing Monday in Weekly mode and multiple events may share one weekly candle.
- [ ] Run `node --test tests/portfolio_expand_timeframe.test.cjs`; verify failure because the helpers do not exist.
- [ ] Add pure `_expandedBarsForTimeframe(revealedBars, timeframe)` and `_expandedMarkerTime(date, timeframe)` helpers which reuse `resampleBars(..., 'W')` and never read unrevealed bars.
- [ ] Rerun the focused test and verify it passes.
- [ ] Commit with `git commit -m "test: define portfolio expanded timeframes"` including the test and minimal helper code.

### Task 2: Add per-entry controls and lazy EMA series

**Files:**
- Modify: `Big_movers.html:4254-4494, 6003-6045, 24540-25400, 21985-22030, 23525-23560`
- Test: `tests/portfolio_expand_timeframe.test.cjs`

- [ ] Add failing DOM/source tests for `Daily | Weekly`, `100 EMA`, and `250 EMA` controls; per-entry `expandedChartPrefs`; lazy long-EMA series; and replacement defaults.
- [ ] Run the focused test and verify the expected failures.
- [ ] Add compact wrapping controls to the expanded-modal header and cache their DOM nodes.
- [ ] Normalize each entry's preferences as `{ timeframe: 'D', ema100: false, ema250: false }`; initialize new/replacement entries with defaults and retain preferences across close/reopen.
- [ ] Refactor `_buildChart`/refresh so 10/20/50 EMA always use displayed candles, while 100/250 line series are created/populated only when enabled and removed or cleared when disabled.
- [ ] On a control change, persist the entry preference and rebuild the modal chart without changing simulation state.
- [ ] Map entry/exit/R markers to weekly keys in Weekly mode; retain stop price lines at their actual prices.
- [ ] Rerun the focused test and existing portfolio setup/offline tests; verify all pass.
- [ ] Commit with `git commit -m "feat: add weekly portfolio expanded charts"`.

### Task 3: Verify the expanded chart

**Files:**
- Verify only.

- [ ] Run `node --test tests/portfolio_expand_timeframe.test.cjs tests/portfolio_setup_defaults.test.cjs tests/offline_local_mode.test.cjs`.
- [ ] Run a JavaScript parse check over every inline script in `Big_movers.html` using the repository's existing test/helper pattern.
- [ ] In a named agent-browser session, start Portfolio Sim, open a ticker's Expand modal, switch Daily/Weekly, toggle 100/250 EMA, advance playback, close/reopen, and verify preferences persist with no future bars.
- [ ] Run `git diff --check` and inspect `git status --short`.

