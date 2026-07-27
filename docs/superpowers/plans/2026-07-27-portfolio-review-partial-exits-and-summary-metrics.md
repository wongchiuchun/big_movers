# Portfolio Review Partial Exits and Summary Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every executed partial exit in portfolio trade review charts and automatically show Stats-consistent win-rate and capital-deployment metrics in the end summary.

**Architecture:** Extend the existing SimStats trade record with a backward-compatible `eventsLog`, and teach session review reconstruction to prefer it over the legacy synthetic final-exit marker. Add one shared SimStats portfolio-metrics function that both the end summary and Stats persistence consume.

**Tech Stack:** Single-file HTML/JavaScript application, Node.js `node:test`/`vm` regression tests, Lightweight Charts markers, localStorage-backed SimStats records.

---

### Task 1: Preserve complete trade execution history

**Files:**
- Create: `tests/portfolio_review_execution.test.cjs`
- Modify: `Big_movers.html` in `_extractTradesFromSim` and `_synthMetaFromSession`

- [ ] **Step 1: Write the failing event-history tests**

Extract the two functions from `Big_movers.html` and assert that:

```js
const trades = extractTradesFromSim(simWithPartialSell, bars, { symbol: 'TEST' });
assert.deepEqual(trades[0].eventsLog, simWithPartialSell.legs[0].eventsLog);

const meta = synthMetaFromSession(session, [{
  symbol: 'TEST',
  eventsLog: [
    { type: 'sell', date: '2025-01-10', qty: 25, price: 120 },
    { type: 'close', date: '2025-01-20', qty: 75, price: 130 }
  ]
}]);
assert.equal(meta.basket[0].legs[0].eventsLog.length, 2);
```

Also assert that a legacy trade without `eventsLog` still receives one synthesized final-exit event.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node tests/portfolio_review_execution.test.cjs`

Expected: FAIL because extracted trades do not retain `eventsLog`, and reconstruction discards stored events.

- [ ] **Step 3: Implement minimal event persistence**

Copy normalized events into each extracted trade:

```js
eventsLog: (leg.eventsLog || []).map(function(ev){
  return {
    type: ev.type || null,
    date: ev.date || null,
    qty: ev.qty != null ? +ev.qty : null,
    price: ev.price != null ? +ev.price : null,
    direction: ev.direction || leg.direction || 'long',
    legId: ev.legId || leg.legId || null
  };
})
```

In `_synthMetaFromSession`, use `t.eventsLog` when present; otherwise retain the existing final-exit synthesis.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `node tests/portfolio_review_execution.test.cjs`

Expected: all event-history assertions pass.

### Task 2: Share Stats metrics with the end summary

**Files:**
- Modify: `tests/portfolio_review_execution.test.cjs`
- Modify: `Big_movers.html` in the SimStats module and portfolio `_showSummary`

- [ ] **Step 1: Write failing metric and wiring tests**

Assert the shared calculator returns the existing dashboard definitions:

```js
assert.equal(metrics.tradeCount, 2);
assert.equal(metrics.winCount, 1);
assert.equal(metrics.winRate, 50);
assert.equal(metrics.avgPctDeployed, 50);
assert.equal(metrics.peakPctDeployed, 75);
```

Assert `_showSummary` calls the shared calculator and renders `Win rate`, `Avg capital deployed`, and `Peak capital deployed`. Assert `addCurrentPortfolio` also calls the shared calculator rather than independently aggregating trades/deployment.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node tests/portfolio_review_execution.test.cjs`

Expected: FAIL because the shared portfolio calculator and automatic summary lines do not exist.

- [ ] **Step 3: Implement the shared calculation**

Add a SimStats function that extracts all basket trades, calls the existing `_aggSession` and `_deployedPortfolio` helpers, and returns the trade rows plus dashboard-format metrics. Export it on `window.SimStats`.

Update `addCurrentPortfolio` to consume that function. Update `_showSummary` to call the same function once and render:

```text
Win rate: 50.0% (1W / 2 trades)
Avg capital deployed: 50.0%
Peak capital deployed: 75.0%
```

Show `—` when no trade or deployment history is available.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `node tests/portfolio_review_execution.test.cjs`

Expected: all metric and wiring assertions pass.

### Task 3: Full regression verification

**Files:**
- Verify: `Big_movers.html`
- Verify: `tests/*.test.cjs`

- [ ] **Step 1: Run every Node regression test**

Run: `node --test tests/*.test.cjs`

Expected: zero failed test files.

- [ ] **Step 2: Check whitespace and inspect the exact diff**

Run: `git diff --check`

Expected: no output and exit status 0.

Run: `git status --short && git diff -- Big_movers.html tests/portfolio_review_execution.test.cjs`

Expected: only the intended implementation/test changes plus the user's pre-existing default-checkbox change and its test.
