# Extended Portfolio Simulation Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Portfolio Simulator randomization mode that generates 6–9 calendar-month windows, including cross-year windows, while leaving the existing default unchanged.

**Architecture:** Keep date-window policy in the existing `_makeRandomWindow` helper inside `Big_movers.html`. The setup UI reads one unchecked checkbox and passes that boolean to both randomization paths; the balanced resolver delegates to the same helper so date generation is no longer duplicated.

**Tech Stack:** Vanilla HTML/CSS/JavaScript, Node.js built-in test runner (`node:test`), existing seeded `PortSimBasket` randomizer.

---

## File map

- Modify `Big_movers.html`: add the checkbox and explanatory copy; extend `_makeRandomWindow`; route the selected mode through same-year and balanced randomization.
- Create `tests/portfolio_simulation_window.test.cjs`: unit-test standard and extended date-window boundaries directly from the production helper.
- Modify `tests/portfolio_balanced_integration.test.cjs`: prove the balanced resolver's default path uses the mode-aware shared helper.
- Modify `tests/portfolio_setup_defaults.test.cjs`: verify the checkbox contract, default state, user-facing copy, and both handler call sites.
- Modify `README.md`: document the optional extended timeframe.

Do not modify or stage the user's existing `metadata.json` change.

### Task 1: Centralize standard and extended window generation

**Files:**
- Create: `tests/portfolio_simulation_window.test.cjs`
- Modify: `tests/portfolio_balanced_integration.test.cjs:7-38,82-144`
- Modify: `Big_movers.html:20264-20302`

- [ ] **Step 1: Write failing unit tests for the shared window helper**

Create `tests/portfolio_simulation_window.test.cjs` with a small balanced-brace function extractor like the existing integration test. Extract `_toDateStr` and `_makeRandomWindow` from `Big_movers.html`, evaluate them in a `vm` context, and add these tests:

```javascript
test('standard windows retain the 120-day floor and year-end cap', () => {
  const makeWindow = loadWindowHelper();
  assert.equal(daysBetween(makeWindow(2020, sequenceRng([0, 0, 0]), false)), 120);

  const late = makeWindow(2020, sequenceRng([0.999999, 0.999999, 0.999999]), false);
  assert.equal(late.start, '2020-08-28');
  assert.equal(late.end, '2020-12-31');
});

test('extended windows span 180 to 270 calendar days and may cross year-end', () => {
  const makeWindow = loadWindowHelper();
  assert.equal(daysBetween(makeWindow(2020, sequenceRng([0, 0, 0]), true)), 180);

  const longest = makeWindow(2020, sequenceRng([0.999999, 0.999999, 0.999999]), true);
  assert.equal(longest.start, '2020-08-28');
  assert.equal(daysBetween(longest), 270);
  assert.match(longest.end, /^2021-/);
});
```

Implement `sequenceRng(values)` to return the values in order, and `daysBetween(range)` as the UTC millisecond difference divided by `86400000`.

- [ ] **Step 2: Run the helper tests and verify RED**

Run:

```bash
node --test tests/portfolio_simulation_window.test.cjs
```

Expected: the standard test passes, while the extended test fails because `_makeRandomWindow` ignores its third argument, still uses 120–180 days, and caps at year-end.

- [ ] **Step 3: Implement the minimum mode-aware helper**

Change the helper to:

```javascript
function _makeRandomWindow(year, rng, extended) {
  var startMonth = Math.floor(rng() * 8); // Jan..Aug
  var startDay = 1 + Math.floor(rng() * 28);
  var minDays = extended ? 180 : 120;
  var dayVariants = extended ? 91 : 61;
  var windowDays = minDays + Math.floor(rng() * dayVariants);
  var start = new Date(Date.UTC(year, startMonth, startDay));
  var end = new Date(Date.UTC(year, startMonth, startDay + windowDays));
  if (!extended) {
    var yearEnd = new Date(Date.UTC(year, 11, 31));
    if (end.getTime() > yearEnd.getTime()) end = yearEnd;
  }
  return { start: _toDateStr(start), end: _toDateStr(end) };
}
```

This keeps all existing standard behavior, retains the January–August start distribution, and only removes the year-end cap for extended mode.

- [ ] **Step 4: Run the helper tests and verify GREEN**

Run:

```bash
node --test tests/portfolio_simulation_window.test.cjs
```

Expected: 2 tests pass.

- [ ] **Step 5: Write a failing balanced-resolver integration test**

Update `loadResolver()` in `tests/portfolio_balanced_integration.test.cjs` to evaluate `_toDateStr` and `_makeRandomWindow` before `_resolveBalancedBasket`. Add a test that calls the resolver without an injected `makeWindow`, with `seed: 'extended-cross-year'`, `extended: true`, a valid manifest date range, empty candidate pools, and a basket API whose `selectBasket()` always returns `null`. This seed deterministically produces several cross-year attempts with the existing `PortSimBasket.createRng`. Assert that all recorded attempts span 180–270 days and at least one attempt ends in the following year:

```javascript
assert.equal(result.attempts.length, 12);
assert.ok(result.attempts.every(attempt => {
  const days = (Date.parse(attempt.end) - Date.parse(attempt.start)) / 86400000;
  return days >= 180 && days <= 270;
}));
assert.ok(result.attempts.some(attempt => attempt.end.startsWith('2021-')));
```

- [ ] **Step 6: Run the resolver test and verify RED**

Run:

```bash
node --test tests/portfolio_balanced_integration.test.cjs
```

Expected: the new test fails because the resolver's private duplicate still generates standard capped windows.

- [ ] **Step 7: Delegate balanced date generation to the helper**

In `_resolveBalancedBasket`, read the option and replace the duplicated generator:

```javascript
var extended = !!options.extended;
var rng = api.createRng(seed + ':windows');
var makeWindow = options.makeWindow || function () {
  return _makeRandomWindow(year, rng, extended);
};
```

Keep injected `makeWindow` support unchanged so the existing retry-boundary tests remain deterministic.

- [ ] **Step 8: Run both window-related test files and verify GREEN**

Run:

```bash
node --test tests/portfolio_simulation_window.test.cjs tests/portfolio_balanced_integration.test.cjs
```

Expected: all tests pass.

- [ ] **Step 9: Commit the date policy and resolver refactor**

```bash
git add Big_movers.html tests/portfolio_simulation_window.test.cjs tests/portfolio_balanced_integration.test.cjs
git commit -m "feat: support extended portfolio simulation windows"
```

### Task 2: Add and wire the Extended timeframe checkbox

**Files:**
- Modify: `tests/portfolio_setup_defaults.test.cjs:14-27`
- Modify: `Big_movers.html:20469-20523,30483-30503`

- [ ] **Step 1: Write failing UI contract tests**

Extend `tests/portfolio_setup_defaults.test.cjs` with a helper that extracts `handleRandomize`. Add a focused test:

```javascript
test('extended timeframe is optional and reaches both randomization paths', () => {
  const extendedCheckbox = html.match(
    /<input\b[^>]*\bid=["']portsim-rand-extended["'][^>]*>/i
  );
  assert.ok(extendedCheckbox, 'extended timeframe checkbox is missing');
  assert.doesNotMatch(extendedCheckbox[0], /\bchecked\b/i);
  assert.match(html, /Extended timeframe/i);
  assert.match(html, /6–9 month/i);

  const handler = extractFunction(html, 'handleRandomize');
  assert.match(handler, /_makeRandomWindow\(year, rng, extendedOn\)/);
  assert.match(handler, /extended:\s*extendedOn/);
});
```

- [ ] **Step 2: Run the setup test and verify RED**

Run:

```bash
node --test tests/portfolio_setup_defaults.test.cjs
```

Expected: the new test fails because the checkbox and `extendedOn` routing do not exist.

- [ ] **Step 3: Add the checkbox and update nearby copy**

Below the Balanced basket label, add:

```html
<label class="portsim-randomize-noise" for="portsim-rand-extended">
  <input type="checkbox" id="portsim-rand-extended">
  <span>⏳ Extended timeframe — random 6–9 month window (up to about 180 trading days), with cross-year periods allowed.</span>
</label>
```

Leave it unchecked. Update the Randomize tooltip and hint to explain that normal mode uses 4–6 months and Extended timeframe uses 6–9 months. Reuse the existing option style; do not add a new visual system.

- [ ] **Step 4: Route the checkbox through both randomization paths**

At the start of `handleRandomize`, add:

```javascript
var extendedEl = $('#portsim-rand-extended');
var extendedOn = !!(extendedEl && extendedEl.checked);
```

Then change the same-year call to:

```javascript
var windowRange = _makeRandomWindow(year, rng, extendedOn);
```

and add this resolver option in the balanced call:

```javascript
extended: extendedOn,
```

- [ ] **Step 5: Run setup and integration tests and verify GREEN**

Run:

```bash
node --test tests/portfolio_setup_defaults.test.cjs tests/portfolio_simulation_window.test.cjs tests/portfolio_balanced_integration.test.cjs
```

Expected: all tests pass.

- [ ] **Step 6: Commit the checkbox and wiring**

```bash
git add Big_movers.html tests/portfolio_setup_defaults.test.cjs
git commit -m "feat: add extended portfolio timeframe control"
```

### Task 3: Document and verify the completed feature

**Files:**
- Modify: `README.md:59-65`

- [ ] **Step 1: Document the opt-in timeframe**

Add a Portfolio Simulation bullet:

```markdown
- **Optional extended timeframe** — randomization normally uses 4–6 calendar months; enable Extended timeframe for a random 6–9 month window that may cross into the following year
```

- [ ] **Step 2: Run the complete JavaScript test suite**

Run:

```bash
node --test tests/*.test.cjs
```

Expected: every JavaScript test passes with zero failures.

- [ ] **Step 3: Check the patch and working tree**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended feature files plus the pre-existing unstaged `metadata.json` modification appear.

- [ ] **Step 4: Commit the documentation**

```bash
git add README.md
git commit -m "docs: describe extended portfolio simulations"
```

- [ ] **Step 5: Re-run final verification after all commits**

Run:

```bash
node --test tests/*.test.cjs
git status --short
```

Expected: all JavaScript tests pass; `metadata.json` remains modified and unstaged, with no other uncommitted feature changes.
