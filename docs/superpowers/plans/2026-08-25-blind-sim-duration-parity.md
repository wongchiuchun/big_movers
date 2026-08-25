# Blind Sim Duration and Individual-Sim Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the existing Blind Sim to offer randomized 4–6 month and 6–12 month windows while continuing to run entirely through the Individual Sim controller.

**Architecture:** Keep `SimBlind` as a thin selection-and-masking adapter inside `Big_movers.html`. Add pure helpers for duration selection and end-index calculation, move candidate selection after the existing modal submission so the chosen full window is known, and launch through the unchanged `Sim.Ctrl.startBlindPlayback` facade.

**Tech Stack:** Inline browser JavaScript and HTML, Node.js built-in test runner, Git.

**Working directory:** Run every command below from `/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers`.

---

## File Map

- Modify `Big_movers.html`: update the existing Blind modal, duration selection, candidate eligibility, messaging, and shared-controller launch.
- Create `tests/blind_sim_duration.test.cjs`: verify the duration bands, inclusive end-index semantics, modal choices, and continued shared-controller routing.

### Task 1: Define the Blind duration contract

**Files:**
- Create: `tests/blind_sim_duration.test.cjs`
- Modify: `Big_movers.html` (`SimBlind` constants/helpers and existing modal markup)

- [x] **Step 1: Write the failing duration tests**

Add Node tests that extract pure `_randomBlindDurationBars`, `_blindEndIdx`, and `_pickBlindWindow` helpers from `Big_movers.html`. Assert deterministic RNG values return 84/126 for `4-6`, 126/252 for `6-12`, invalid bands fall back to `4-6`, and `endIdx = startIdx + N - 1`.

Test `_pickBlindWindow` at the exact minimum eligible data length, one bar short, both RNG boundaries, and with a current-year start cap. Assert it returns `null` for insufficient coverage, never truncates `durationBars`, and returns an inclusive end index within the loaded bar count.

Also assert the Blind modal contains the two band values and no longer contains `sim-blind-bars`.

- [x] **Step 2: Run the focused test and verify failure**

Run: `node --test tests/blind_sim_duration.test.cjs`

Expected: FAIL because the helpers and duration selector do not exist yet.

- [x] **Step 3: Add minimal duration helpers and modal controls**

In the existing `SimBlind` IIFE:

```javascript
const DURATION_BANDS = {
  '4-6': { min: 84, max: 126 },
  '6-12': { min: 126, max: 252 }
};

function _randomBlindDurationBars(band, rng) {
  const range = DURATION_BANDS[band] || DURATION_BANDS['4-6'];
  const random = typeof rng === 'function' ? rng : Math.random;
  return range.min + Math.floor(random() * (range.max - range.min + 1));
}

function _blindEndIdx(startIdx, durationBars) {
  return startIdx + durationBars - 1;
}

function _pickBlindWindow(barCount, durationBars, minContext, maxStartCap, rng) {
  let maxStartIdx = barCount - durationBars;
  if (Number.isInteger(maxStartCap) && maxStartCap >= 0) {
    maxStartIdx = Math.min(maxStartIdx, maxStartCap);
  }
  if (maxStartIdx < minContext) return null;
  const random = typeof rng === 'function' ? rng : Math.random;
  const startIdx = minContext + Math.floor(random() * (maxStartIdx - minContext + 1));
  const endIdx = _blindEndIdx(startIdx, durationBars);
  if (endIdx >= barCount) return null;
  return { startIdx, endIdx, durationBars };
}
```

Replace the free-form bars input with a select offering `4-6` and `6-12`. Submit `{ initialEquity, fixedRiskDollar, durationBand }`.

- [x] **Step 4: Run the focused test and verify pass**

Run: `node --test tests/blind_sim_duration.test.cjs`

Expected: PASS.

### Task 2: Require a complete randomly sized playback window

**Files:**
- Modify: `Big_movers.html` (`SimBlind._open` and a focused launch helper)
- Modify: `tests/blind_sim_duration.test.cjs`

- [x] **Step 1: Add failing structural assertions**

Assert that the focused launch function samples `durationBars` before its candidate retry loop, calls `_pickBlindWindow` for each candidate using that same value, and still invokes `Sim.Ctrl.startBlindPlayback` rather than another controller. The behavioral helper tests from Task 1 prove full-window eligibility, inclusive end indices, current-year caps, and no truncation.

- [x] **Step 2: Run the focused test and verify failure**

Run: `node --test tests/blind_sim_duration.test.cjs`

Expected: FAIL because `_open` still picks a ticker before reading the duration and caps the requested bars to available data.

- [x] **Step 3: Update the existing selection flow**

Keep `_open` as the public Blind button handler. Open the existing Blind modal first; after submission:

1. Draw one duration in the selected band.
2. Retry existing local candidates.
3. For each loaded ticker, calculate the existing current-year cap index when applicable and call `_pickBlindWindow(currentBars.length, durationBars, MIN_CONTEXT, capIdx)`.
4. The helper chooses a random start, enforces `maxStartIdx = currentBars.length - durationBars`, and returns the inclusive end index.
5. Reject the candidate when the helper returns `null`; never resample or shorten `durationBars` inside the retry loop.
6. Apply the existing Blind state/mask and call the unchanged `Sim.Ctrl.startBlindPlayback` with that exact start/end pair.

Remove the prior `Math.min(...)` truncation. On bounded retry failure, show a duration-specific message and suggest the shorter band. If `Sim.Ctrl.startBlindPlayback(...)` returns `false`, clear the Blind state/mask and report failure instead of leaving the chart masked; retain the existing exception cleanup.

- [x] **Step 4: Run focused verification**

Run: `node --test tests/blind_sim_duration.test.cjs`

Expected: PASS.

Run: `node --check entry_trainer.js`

Expected: PASS (unchanged shared controller consumer remains syntactically valid).

- [x] **Step 5: Check scope and commit**

Run: `git diff --check -- Big_movers.html tests/blind_sim_duration.test.cjs docs/superpowers/plans/2026-08-25-blind-sim-duration-parity.md`

Expected: no output.

Stage only the three scoped files, preserving user-owned CSV/JSON changes, then commit:

```bash
git add Big_movers.html tests/blind_sim_duration.test.cjs docs/superpowers/plans/2026-08-25-blind-sim-duration-parity.md
git commit -m "feat: extend blind simulation windows"
```
