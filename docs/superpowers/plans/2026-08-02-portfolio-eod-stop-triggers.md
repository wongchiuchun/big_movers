# Portfolio End-of-Day Stop Triggers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each Portfolio Simulation stop independently trigger intraday or only at the bar's closing price, with complete UI, state, replay, rewind, and review propagation.

**Architecture:** Store normalized `triggerMode` on every stop level and centralize trigger/fill decisions in the simulation engine. Portfolio-mode modal adapters expose one shared EOD checkbox and pass the mode through existing action payloads; missing or invalid modes normalize to `intraday`.

**Tech Stack:** Inline browser JavaScript/HTML, existing Sim engine and PortSim adapters, Node.js `node:test`, agent-browser.

---

### Task 1: Implement stop semantics test-first

**Files:**
- Create: `tests/portfolio_eod_stops.test.cjs`
- Modify: `Big_movers.html:11380-11720, 12400-12610`

- [ ] Write failing engine tests for unchanged long/short intraday behavior; long/short close touches; close fills; non-triggering intraday breaches that recover by close; partial stops; mixed trigger modes; invalid/missing mode fallback; and an EMA-trailing close-mode stop that ratchets before evaluating the same bar's close.
- [ ] Run `node --test tests/portfolio_eod_stops.test.cjs`; verify failure because stop levels lack `triggerMode` and close-only evaluation.
- [ ] Add a normalizer returning only `intraday` or `close` and attach the normalized value whenever a stop level is created/replaced.
- [ ] Centralize direction-aware stop evaluation so intraday uses low/high plus existing gap fills, while close mode uses close comparison and fills at close.
- [ ] Preserve direction-aware stop ordering and per-stop percentages when mixed modes fire on one bar.
- [ ] Preserve the existing trail-ratchet-before-trigger sequence for both modes; the close-mode EMA regression must prove the newly ratcheted price is evaluated against the current close.
- [ ] Record `triggerMode` and the close fill on stop events/history.
- [ ] Rerun the focused engine test and verify it passes.
- [ ] Commit with `git commit -m "feat: add end-of-day portfolio stops"`.

### Task 2: Thread trigger mode through Portfolio actions

**Files:**
- Modify: `Big_movers.html:6100-6800, 12800-13620, 18300-19080, 19720-19800, 21980-22920`
- Test: `tests/portfolio_eod_stops.test.cjs`
- Test: `tests/portfolio_setup_defaults.test.cjs`

- [ ] Add failing tests for trigger-mode flow through pre-entry setup, initial entry, new leg, optional add replacement stop, Move Stop, queued/immediate actions, replay config, and history serialization.
- [ ] Run the focused tests and verify failures at the missing UI/payload boundaries.
- [ ] Add a reusable unchecked `Trigger only at end-of-day close` control to every stop-creation/replacement modal; expose it only for `ctx.portMode` unless explicitly enabled.
- [ ] Pass `triggerMode` through `PortSim.Modal` adapters and all entry/add/new-leg/move-stop payloads, including EMA-trailing stop specifications.
- [ ] Ensure direct price edits retain the existing stop's mode; full Move Stop replacement uses the currently selected checkbox mode.
- [ ] Ensure snapshots/replay preserve the field through existing deep clones and missing legacy values normalize to intraday.
- [ ] Rerun focused tests and verify all pass.
- [ ] Commit with `git commit -m "feat: expose portfolio EOD stop controls"`.

### Task 3: Surface mode in management, export, and review

**Files:**
- Modify: `Big_movers.html:23950-24520, 24990-25080, 27150-27230, 28850-29300`
- Test: `tests/portfolio_eod_stops.test.cjs`
- Test: `tests/portfolio_review_execution.test.cjs`

- [ ] Add failing tests requiring active-stop/history labels and structured events to distinguish EOD stops, and CSV/review serialization to retain `triggerMode`.
- [ ] Run focused tests and verify the expected failures.
- [ ] Add concise `EOD` labeling to stop popovers, expanded-view stop lists, and relevant event/history output without changing intraday labels.
- [ ] Include normalized trigger mode in CSV/review/event serialization.
- [ ] Rerun focused tests and verify all pass.
- [ ] Commit with `git commit -m "feat: report portfolio EOD stop modes"`.

### Task 4: Full regression and live verification

**Files:**
- Verify only.

- [ ] Run the focused command `node --test tests/portfolio_eod_stops.test.cjs tests/sim_shorts.test.cjs tests/portfolio_review_execution.test.cjs tests/portfolio_setup_defaults.test.cjs tests/offline_local_mode.test.cjs`.
- [ ] Run the complete JavaScript regression suite with `node --test tests/*.test.cjs` and require zero failures.
- [ ] Parse all inline scripts in `Big_movers.html`.
- [ ] In agent-browser, verify a long and short Portfolio stop in both modes, including an intraday breach that closes safely and an EOD close that triggers at the closing price.
- [ ] Verify step-back and replay retain the selected trigger mode.
- [ ] Run `git diff --check` and inspect `git status --short`.
