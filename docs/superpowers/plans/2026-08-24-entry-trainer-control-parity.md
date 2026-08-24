# Entry Trainer Control Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Entry Trainer's playback, rewind, expanded view, add, and partial-sell controls behave consistently with Individual Sim.

**Architecture:** Keep `Sim.Ctrl` as the single playback and history owner. Extend its optional flat-policy adapter so caller-owned state participates in the same atomic snapshots, then configure `EntryTrainer` to provide that state and remove its unnecessary control restrictions. Reuse all existing transport, pop-out, trade, and stop UI.

**Tech Stack:** Inline browser JavaScript/CSS in `Big_movers.html`, Entry Trainer adapter in `entry_trainer.js`, Lightweight Charts 3.8, existing `Sim` and portfolio-order helpers.

**Testing constraint:** The user explicitly requested no automated or runtime testing. Perform static syntax/diff checks only; the user will test interactively.

---

### Task 1: Make shared Sim history policy-aware

**Files:**
- Modify: `Big_movers.html` (`Sim.Ctrl` flat-policy normalization, snapshot push/restore, action capabilities, entry commit)

- [ ] **Step 1: Extend the optional flat-policy contract**

Normalize `captureHistoryState` and `restoreHistoryState` callbacks alongside explicit `allowFlatPlayback` and `disableJumpToEntry` controls. Decouple `sim-btn-entry` visibility from `disableRewind` so Entry Trainer can enable Back without exposing the destructive reset action.

- [ ] **Step 2: Capture complete controller history**

Add the controller-owned flat lifecycle fields and the optional caller-owned snapshot to `_pushSnapshot`. Accept an optional caller-state override for atomic operations whose caller has already started mutating external state.

- [ ] **Step 3: Restore complete controller and caller state**

In `_stepBack`, restore the flat lifecycle fields before rendering, invoke `restoreHistoryState`, then rebuild markers, stops, order UI, action capabilities, and the policy state notification.

- [ ] **Step 4: Permit flat autoplay when policy allows it**

Change `_actionCapabilities` so `allowFlatPlayback` permits Play while flat before an attempt, but not while an attempt result is pending or the horizon is complete. Preserve `pauseWhenFlat` for immediate pause-on-attempt-completion behavior.

- [ ] **Step 5: Capture each bar before policy callbacks mutate it**

Capture policy-owned state once at the start of `_stepForward`, before `beforeFlatStep`. Reuse that capture for the normal bar snapshot, or expose it in the callback context so a handled atomic limit fill can pass it into `_commitFlatEntry`. Do not retain a snapshot when a step is blocked or a fill transaction fails. Entry submission/cancellation continue to use the checkpoint that brought the playhead to the current bar, avoiding same-bar no-op Back steps.

### Task 2: Configure Entry Trainer parity and reversible state

**Files:**
- Modify: `entry_trainer.js` (policy setup, history capture/restore, atomic limit fill, toolbar locking)
- Modify: `Big_movers.html` (Entry Trainer-active toolbar CSS exception)

- [ ] **Step 1: Capture Entry Trainer-owned history**

Snapshot the active candidate's pending order, order events, attempts, batch order state, and runtime result/horizon/retry fields before each reversible mutation.

- [ ] **Step 2: Restore Entry Trainer-owned history**

Restore those fields in place, reconcile buying-power reservations, refresh the working limit line and strip, and reconstruct or hide the attempt-result presentation from restored state.

- [ ] **Step 3: Keep limit fills atomic**

Pass the controller-provided `context.historyPolicyState` from `beforeFlatStep` into `commitFlatEntry` as its history override. Keep the narrower `captureOrderTransaction` snapshot only for rolling back a failed fill transaction. This ensures the shared history record contains both pre-fill Sim and pre-fill Entry Trainer state.

- [ ] **Step 4: Enable consistent controls**

Remove `disableRewind`, `disableAdds`, and `fullExitOnly`; set `allowFlatPlayback` and `disableJumpToEntry`; retain pause-on-attempt-completion, long-only, maximum-three-attempt, causal-daily, and pending-limit behavior.

- [ ] **Step 5: Preserve the expand control**

Lock unrelated chart-toolbar controls individually while leaving `popout-btn` usable, and make the Entry Trainer-active CSS exception explicit.

### Task 3: Static verification and commit

**Files:**
- Modify: `docs/superpowers/plans/2026-08-24-entry-trainer-control-parity.md` (mark completed steps)

- [ ] **Step 1: Inspect targeted diffs**

Confirm only `Big_movers.html`, `entry_trainer.js`, and this plan contain implementation changes; preserve the user's existing CSV, drawings, and metadata edits.

- [ ] **Step 2: Run static checks only**

Run whitespace checks scoped to the changed implementation files and parse the standalone `entry_trainer.js` with Node if available. Do not launch the server, browser, or test suite.

- [ ] **Step 3: Commit the implementation**

Stage only the two implementation files and this plan, then commit with:

```bash
git commit -m "feat: align entry trainer controls"
```
