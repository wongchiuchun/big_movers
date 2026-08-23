# Simulation Chart Cutoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep weekly/monthly candles and all main-chart indicators clipped to the current Individual Sim playhead.

**Architecture:** Use `Sim.Ctrl.getCutoffBarTime()` as one inclusive render cutoff. Global chart producers filter their inputs before writing series, while the simulator renders resampled revealed candles as playback advances.

**Tech Stack:** Vanilla JavaScript, Lightweight Charts, single-file `Big_movers.html` application.

---

### Task 1: Make global chart producers simulation-aware

**Files:**
- Modify: `Big_movers.html` near timeframe/indicator helpers

- [ ] **Step 1: Add one revealed-bar helper**

Add a function that reads `Sim.Ctrl.getCutoffBarTime()` and returns `bars.filter(bar => bar.time <= cutoff)` when active, otherwise the original full bar array.

- [ ] **Step 2: Route chart producers through the helper**

Use the filtered source in `applyTimeframe`, `updateMaSeries`, `updateSuperTrend`, `updateSpyOverlay`, and theme-triggered volume refresh. `updateSuperTrend` must resample that revealed source to `currentTF`, and the simulator must refresh it whenever playback changes the active weekly/monthly bucket. Filter precomputed AI overlay points and their markers by the same cutoff before `setData`/`setMarkers`.

- [ ] **Step 3: Stop timeframe buttons from reloading the ticker during Sim**

In `setTimeframe`, call `applyTimeframe()` directly when `Sim.Ctrl.isActive()` instead of `selectRow(activeIdx)`. Keep the existing reload path outside Sim.

### Task 2: Render simulation playback in the active timeframe

**Files:**
- Modify: `Big_movers.html` inside `Sim.Ctrl`

- [ ] **Step 1: Resample only revealed daily bars**

Change `_maskChart(sliceIdx)` to feed `resampleBars(state.bars.slice(0, sliceIdx + 1), currentTF)` into candles and volume. Preserve the inclusive daily playhead as engine state.

- [ ] **Step 2: Update partial weekly/monthly candles safely**

When `currentTF !== 'D'`, make `_appendBar(idx)` rebuild the revealed resampled price/volume series so the current bucket is replaced using only constituents through `idx`. Keep the existing incremental daily path.

- [ ] **Step 3: Keep moving averages causal across timeframe changes**

For weekly/monthly mode, compute enabled moving averages from the revealed resampled bars rather than a full-period precomputed map. For daily mode, retain the existing precomputed/incremental path.

- [ ] **Step 4: Preserve simulation overlays after a timeframe rebuild**

Expose a small `Sim.Ctrl.refreshChartCutoff()` method that obtains the inclusive cutoff through `getCutoffBarTime()`, resolves the corresponding revealed slice, and recomputes/remasks candles, volume, moving averages, SuperTrend, AI overlays, drawings, and current simulation markers. Call it after the global timeframe render while Sim is active. Blind/Random Sim uses the same controller and cutoff contract.

### Task 3: Source verification and commit

**Files:**
- Modify: `Big_movers.html`
- Update: `docs/superpowers/plans/2026-08-23-simulation-chart-cutoff-plan.md`

- [ ] **Step 1: Review focused source paths**

Run `rg` against timeframe switches, cutoff helpers, indicator `setData` paths, and `_appendBar` to confirm all identified leak paths consume the cutoff. Confirm empty optional overlays do not fall back to full data and standard/session-owned teardown paths remain unchanged.

- [ ] **Step 2: Check the diff**

Run `git diff --check -- Big_movers.html docs/superpowers/plans/2026-08-23-simulation-chart-cutoff-plan.md` and inspect the focused diff. Do not run automated tests, a server, or a browser per user instruction.

- [ ] **Step 3: Commit only feature files**

Stage `Big_movers.html` and this plan, verify the user's `collected_stocks/NVTS.csv`, `drawings.json`, and `metadata.json` remain unstaged, then commit with `fix: preserve simulation chart cutoff`.
