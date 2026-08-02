# Preserve Modified Balanced Basket Roles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve known randomized ticker roles after portfolio setup edits, identify only genuinely new tickers as unknown, and clearly label modified baskets in post-simulation Review.

**Architecture:** Add a small provenance API to `portfolio_basket.js` that owns generation creation, reconciliation, role resolution, and current role counts. The setup wizard, controller, Stats persistence, and Review call that shared API instead of deleting metadata or implementing conflicting fallback rules. Version-2 generation records keep an immutable origin snapshot while legacy version-1 payloads remain readable.

**Tech Stack:** Browser JavaScript (ES5-compatible module style), Node.js `node:test`, single-file HTML application, agent-browser live verification.

---

## File Map

- Modify `portfolio_basket.js`: add the shared basket-provenance API and export it through the existing browser/CommonJS wrapper.
- Modify `Big_movers.html`: create version-2 generation records; reconcile setup/runtime edits; use shared role resolution and current counts across controller, Stats, and Review.
- Modify `tests/portfolio_balanced_basket.test.cjs`: unit-test provenance creation, reconciliation, resolution, current counts, and legacy behavior.
- Modify `tests/portfolio_balanced_integration.test.cjs`: assert setup and controller wiring retains generation metadata rather than clearing it.
- Modify `tests/portfolio_review_execution.test.cjs`: assert Review/Stats/rerun precedence, modified labeling, and current composition behavior.

### Task 1: Add the basket-provenance API

**Files:**
- Modify: `portfolio_basket.js:410-540`
- Test: `tests/portfolio_balanced_basket.test.cjs`

- [ ] **Step 1: Write failing provenance unit tests**

Add focused tests using the existing `Basket` CommonJS import:

```javascript
test('generation reconciliation preserves roles and marks date edits modified', () => {
  const generated = Basket.createGeneration({
    mode: 'balanced', seed: 'seed',
    composition: { mover: 1, anchor: 1, noise: 1 },
    roles: { MOVE: 'mover', LIQ: 'anchor', CMP: 'noise' },
    startDate: '2020-01-01', endDate: '2020-06-01',
    symbols: ['MOVE', 'LIQ', 'CMP']
  });
  const edited = Basket.reconcileGeneration(generated, {
    startDate: '2020-02-01', endDate: '2020-06-01',
    symbols: ['MOVE', 'LIQ', 'CMP']
  });
  assert.equal(edited.modified, true);
  assert.equal(Basket.resolveRole(edited, 'LIQ', 'unknown'), 'anchor');
});

test('current role counts omit removals and count additions as unknown', () => {
  const counts = Basket.countCurrentRoles(generation, [
    { symbol: 'MOVE', role: 'unknown' },
    { symbol: 'LIQ', role: 'unknown' },
    { symbol: 'NEW', role: 'unknown' }
  ]);
  assert.deepEqual(counts, { mover: 1, anchor: 1, noise: 0, unknown: 1 });
});
```

Also cover symbol-order changes, reverting to the exact origin, same-year mode,
invalid roles, and version-1 objects without `origin`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/portfolio_balanced_basket.test.cjs`

Expected: FAIL because `createGeneration`, `reconcileGeneration`,
`resolveRole`, and `countCurrentRoles` do not exist.

- [ ] **Step 3: Implement the minimal shared API**

Add and export four cohesive helpers:

```javascript
function createGeneration(options) { /* normalized version-2 snapshot */ }
function reconcileGeneration(generation, current) { /* cloned object + modified */ }
function resolveRole(generation, symbol, explicitRole) { /* valid explicit, generation, unknown */ }
function countCurrentRoles(generation, entries) { /* mover/anchor/noise/unknown */ }
```

Implementation constraints:

- normalize symbols by trimming and uppercasing;
- preserve the immutable `origin` and original `roles` map;
- compare normalized dates and ordered symbol arrays;
- do not claim legacy version-1 metadata is modified when origin is absent;
- treat explicit `unknown` as a placeholder, not an override of a valid
  generation role; and
- return new generation/count objects rather than mutating caller input.

- [ ] **Step 4: Run the focused unit test and verify GREEN**

Run: `node --test tests/portfolio_balanced_basket.test.cjs`

Expected: all tests pass.

- [ ] **Step 5: Commit the provenance API**

```bash
git add portfolio_basket.js tests/portfolio_balanced_basket.test.cjs
git commit -m "feat: preserve randomized basket provenance"
```

### Task 2: Reconcile setup and runtime ticker edits

**Files:**
- Modify: `Big_movers.html:20140-20230, 20270-20450, 20815-20845, 21130-21185, 21920-22010, 23370-23580`
- Test: `tests/portfolio_balanced_integration.test.cjs`
- Test: `tests/portfolio_setup_defaults.test.cjs`

- [ ] **Step 1: Write failing setup/controller integration tests**

Extend source-contract and extracted-function tests to require:

- `_commitRandomBasket` calls `PortSimBasket.createGeneration` with original
  dates and ordered symbols;
- `readFormToState` calls `PortSimBasket.reconcileGeneration` rather than
  assigning `basketGeneration = null`;
- ticker/date input handlers do not erase generation metadata;
- controller bootstrap calls `PortSimBasket.resolveRole`; and
- runtime add/replace reconciles generation against the current basket and
  gives a restored original symbol its original role.

- [ ] **Step 2: Run integration tests and verify RED**

Run:

```bash
node --test \
  tests/portfolio_balanced_integration.test.cjs \
  tests/portfolio_setup_defaults.test.cjs
```

Expected: FAIL on missing provenance API calls and existing destructive
`basketGeneration = null` assignments.

- [ ] **Step 3: Wire the setup and controller to the shared API**

Make these minimal changes:

1. `_commitRandomBasket` creates a version-2 record through
   `PortSimBasket.createGeneration`.
2. `readFormToState` reconciles after it reads the live form.
3. Remove provenance-clearing listeners from date/symbol/add/remove handlers;
   the submit-time reconciliation determines whether the final setup changed.
4. `_bootstrapFromConfig` resolves each role through the shared helper.
5. `_addOrReplaceTicker` reconciles `_state.basketGeneration` after the basket
   mutation and resolves the added symbol from the retained origin map.
6. Leave cash, benchmark, pre-entry, size, and stop handlers provenance-neutral.

- [ ] **Step 4: Run integration tests and verify GREEN**

Run the command from Step 2.

Expected: all tests pass.

- [ ] **Step 5: Commit setup/controller wiring**

```bash
git add Big_movers.html \
  tests/portfolio_balanced_integration.test.cjs \
  tests/portfolio_setup_defaults.test.cjs
git commit -m "fix: retain roles after portfolio setup edits"
```

### Task 3: Make Review and Stats prefer known provenance

**Files:**
- Modify: `Big_movers.html:15690-15770, 28560-28655, 29220-29270, 29470-29510, 29910-29945`
- Test: `tests/portfolio_review_execution.test.cjs`

- [ ] **Step 1: Write failing Review and persistence tests**

Add behavior tests asserting:

```javascript
assert.equal(
  Basket.resolveRole(generation, 'LIQ', 'unknown'),
  'anchor'
);
```

Extend extracted-function/source tests so `_buildMeta`, `_renderOverview`,
`_synthMetaFromSession`, and `_onRerun` use the shared resolver. Add a render
fixture containing one removed original and one new ticker, and assert Review
shows `balanced · modified`, current mover/anchor/noise counts, and
`unknown 1`. Add a runtime-replacement fixture where the retired original
remains in trade history but is excluded from current composition. Verify a
metadata-free legacy session remains unknown.

- [ ] **Step 2: Run the Review test and verify RED**

Run: `node --test tests/portfolio_review_execution.test.cjs`

Expected: FAIL because explicit `unknown` currently overrides generation roles
and Review displays the original composition without a modified label.

- [ ] **Step 3: Replace duplicated precedence and stale counts**

- Use `PortSimBasket.resolveRole` in controller bootstrap, Stats session
  reconstruction, live/saved Review metadata, and rerun configuration.
- Preserve retired entries in the Review ticker/trade table, but mark them as
  retired and use `PortSimBasket.countCurrentRoles` only on active entries.
- Persist `activeSymbols` on new Stats sessions (from the live active basket,
  not the active-plus-retired trade-history union) so Stats reconstruction can
  distinguish current membership. Legacy sessions without `activeSymbols`
  retain their existing behavior without guessed removals.
- Render `balanced · modified` (or `same-year · modified`) when appropriate.
- Render `unknown N` only when the current count is non-zero.
- Change the seed label to `original seed` for modified baskets.
- Preserve the existing final-review-only role reveal.

- [ ] **Step 4: Run the Review test and verify GREEN**

Run: `node --test tests/portfolio_review_execution.test.cjs`

Expected: all tests pass.

- [ ] **Step 5: Commit Review/Stats wiring**

```bash
git add Big_movers.html tests/portfolio_review_execution.test.cjs
git commit -m "fix: report roles for modified portfolio baskets"
```

### Task 4: Regression and live verification

**Files:**
- Verify only; no planned production changes.

- [ ] **Step 1: Run the complete focused JavaScript suite**

Run:

```bash
node --test \
  tests/portfolio_balanced_basket.test.cjs \
  tests/portfolio_balanced_integration.test.cjs \
  tests/portfolio_review_execution.test.cjs \
  tests/portfolio_setup_defaults.test.cjs \
  tests/offline_local_mode.test.cjs
```

Expected: all tests pass with zero failures, warnings, or cancellations.

- [ ] **Step 2: Run the anchor backend regressions**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m unittest \
  tests.test_market_anchor_manifest \
  tests.test_market_anchor_sync -v
```

Expected: all tests pass.

- [ ] **Step 3: Check the patch and user-owned files**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; the pre-existing `drawings.json` and
`metadata.json` modifications remain untouched.

- [ ] **Step 4: Verify the original symptom in the live app**

Using a named agent-browser session against `http://127.0.0.1:5051/`:

1. Open Portfolio Setup and generate a six-ticker balanced basket.
2. Record the generated roles through runtime state.
3. Change one ticker or generated date.
4. Start/finalize the simulation and open Review.
5. Confirm unchanged randomized tickers retain their roles, the new ticker is
   `unknown`, current counts are accurate, and the origin label says
   `balanced · modified`.

- [ ] **Step 5: Commit any test-only verification adjustment if necessary**

Only if Step 4 exposes a missing regression assertion, add that test first,
watch it fail, implement the minimal correction, rerun all verification, and
commit the isolated correction.
