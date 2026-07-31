# Price and Date Range Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary Measure tool with separate persistent Price Range and Date Range chart drawings.

**Architecture:** Add small pure helpers for range geometry, price metrics, nearest-timeframe-bar lookup, and inclusive bar counts. Keep the two tools visually distinct but share placement, persistence, selection, hit testing, movement, resizing, cutoff handling, and canvas-label rendering through the existing drawing layer in `Big_movers.html`.

**Tech Stack:** Browser JavaScript, HTML/CSS, Canvas 2D, Node.js built-in test runner, local browser smoke testing.

---

## File Map

- Modify `Big_movers.html`: replace Measure toolbar/state, add shared range helpers, and integrate both persistent drawing types.
- Create `tests/chart_range_drawing.test.cjs`: direct calculation tests and focused HTML integration assertions.
- Modify `tests/chart_circle_drawing.test.cjs`: keep the existing time-normalization and toolbar registration regressions aligned with the shared nearest-bar helper and Measure replacement.
- Reference `docs/superpowers/specs/2026-07-31-price-and-date-range-tools-design.md`: approved requirements.

### Task 1: Pure Range Calculations

**Files:**
- Create: `tests/chart_range_drawing.test.cjs`
- Modify: `Big_movers.html`
- Modify: `tests/chart_circle_drawing.test.cjs`

- [ ] **Step 1: Write failing tests for range geometry and price metrics**

Create a Node test with the same named-function extractor/VM pattern as `tests/chart_circle_drawing.test.cjs`. Test:

```js
test('range geometry normalizes visual bounds without changing endpoint identity', () => {
  const { getRangeGeometry } = loadFunctions(['getRangeGeometry']);
  assert.deepEqual(plain(getRangeGeometry(30, 40, 10, 15)), {
    x1: 30, y1: 40, x2: 10, y2: 15,
    left: 10, top: 15, right: 30, bottom: 40,
    width: 20, height: 25
  });
});

test('price range keeps direction and handles a zero start', () => {
  const { calculatePriceRange } = loadFunctions(['calculatePriceRange']);
  assert.deepEqual(plain(calculatePriceRange(10, 12.5)), {
    change: 2.5, percentage: 25, direction: 'gain'
  });
  assert.deepEqual(plain(calculatePriceRange(20, 15)), {
    change: -5, percentage: -25, direction: 'loss'
  });
  assert.deepEqual(plain(calculatePriceRange(0, 5)), {
    change: 5, percentage: null, direction: 'gain'
  });
});
```

- [ ] **Step 2: Write failing tests for inclusive timeframe bar counts**

Test `nearestBarIndex(bars, time)` and `countBarsInRange(bars, p1Time, p2Time)` with string and BusinessDay anchors:

- Same bar returns 1.
- Forward and reversed anchors return the same inclusive count.
- An exact tie chooses the earlier bar.
- Representative Daily, Weekly, and Monthly arrays count bars from the full supplied series rather than viewport state.

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
node --test tests/chart_range_drawing.test.cjs
```

Expected: FAIL because the new range helpers are absent.

- [ ] **Step 4: Implement the minimal pure helpers**

Add near the existing drawing time/geometry helpers:

```js
function getRangeGeometry(x1,y1,x2,y2){
  return {
    x1,y1,x2,y2,
    left:Math.min(x1,x2),top:Math.min(y1,y2),
    right:Math.max(x1,x2),bottom:Math.max(y1,y2),
    width:Math.abs(x2-x1),height:Math.abs(y2-y1)
  };
}

function calculatePriceRange(startPrice,endPrice){
  const start=Number(startPrice),end=Number(endPrice);
  if(!Number.isFinite(start)||!Number.isFinite(end)){
    return {change:null,percentage:null,direction:'gain'};
  }
  const change=end-start;
  return {
    change,
    percentage:start===0?null:(change/start*100),
    direction:change<0?'loss':'gain'
  };
}
```

Implement `nearestBarIndex` using `drawingTimeToMs`. Iterate chronologically and update only for a strictly smaller distance so an exact tie retains the earlier bar. Refactor `nearestBarTime` to reuse the index helper. Update the VM function list in `tests/chart_circle_drawing.test.cjs` so the extracted `nearestBarTime` has its new `nearestBarIndex` dependency. Implement inclusive `countBarsInRange` as `Math.abs(endIndex-startIndex)+1`, returning zero when an anchor cannot map.

- [ ] **Step 5: Run the tests and verify GREEN**

Run:

```bash
node --test tests/chart_range_drawing.test.cjs tests/chart_circle_drawing.test.cjs
```

Expected: all tests pass, including the existing BusinessDay regression.

- [ ] **Step 6: Commit the calculation seam**

```bash
git add Big_movers.html tests/chart_range_drawing.test.cjs tests/chart_circle_drawing.test.cjs
git commit -m "test: define chart range calculations"
```

### Task 2: Replace the Measure Toolbar and Transient State

**Files:**
- Modify: `tests/chart_range_drawing.test.cjs`
- Modify: `Big_movers.html`
- Modify: `tests/chart_circle_drawing.test.cjs`

- [ ] **Step 1: Add a failing toolbar/state test**

Assert that:

- `tool-price-range` and `tool-date-range` buttons exist with distinct accessible labels.
- `tool-measure` is absent.
- `TOOLS` contains `price-range` and `date-range` but not `measure`.
- `Alt+P` maps to `price-range`; `Alt+M` maps to `date-range`.
- `measureStart`, `measureEnd`, `drawMeasure`, and `drawTool==='measure'` are absent.
- Collapsed-toolbar CSS hides both new buttons.

Update the existing circle toolbar assertion so its expected `TOOLS` list contains `price-range` and `date-range` instead of `measure`.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
node --test tests/chart_range_drawing.test.cjs
```

Expected: calculation tests pass and toolbar/state test fails against the old Measure tool.

- [ ] **Step 3: Replace the toolbar control**

Replace Measure with:

- Price Range button using a vertical double-arrow/range icon and title `Price Range [Alt+P]`.
- Date Range button using a horizontal double-arrow/range icon and title `Date Range [Alt+M]`.

Update collapsed-toolbar selectors for both buttons.

- [ ] **Step 4: Remove transient Measure state and register the new tools**

Remove `measureStart`, `measureEnd`, `drawMeasure`, its redraw call, Measure-specific `setTool` cleanup, and the Measure click branch. Register both tool IDs and shortcuts. Do not add settings popups: Price Range colors are directional and Date Range is blue by design.

- [ ] **Step 5: Run tests and parse inline scripts**

Run:

```bash
node --test tests/chart_range_drawing.test.cjs
```

Then compile every inline script in `Big_movers.html` with `new Function(...)`.

Expected: tests pass and every inline script parses.

- [ ] **Step 6: Commit the toolbar replacement**

```bash
git add Big_movers.html tests/chart_range_drawing.test.cjs tests/chart_circle_drawing.test.cjs
git commit -m "feat: replace measure with range tools"
```

### Task 3: Persistent Placement, Rendering, Selection, and Editing

**Files:**
- Modify: `tests/chart_range_drawing.test.cjs`
- Modify: `Big_movers.html`

- [ ] **Step 1: Add failing interaction/wiring assertions**

Assert that:

- `isRangeTool`, `rangeDrawingTypeForTool`, `getRangeHitPart`, `formatRangePrice`, and shared range-rendering helpers exist.
- Both tools enter the standard `pendingP1` two-click path.
- Second click stores `priceRange` or `dateRange` with untouched `p1` and `p2`.
- Preview and final rendering use `getRangeGeometry`.
- Price rendering calls `calculatePriceRange` and makes percentage primary.
- Date rendering calls `countBarsInRange(resampleBars(currentBars,currentTF), ...)` and pluralizes `bar`/`bars`.
- Both drawing types have explicit simulation-cutoff guards in hit testing.
- Hit testing distinguishes `p1`, `p2`, and `whole` using endpoints plus expanded rectangle bounds.
- Dragging handles changes one anchor; dragging `whole` changes both.
- No server/API integration is added.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
node --test tests/chart_range_drawing.test.cjs
```

Expected: existing range tests pass and interaction assertions fail because persistent behavior is not wired.

- [ ] **Step 3: Add shared preview and label rendering**

Implement helpers that:

- Draw a translucent rectangle and outline from normalized visual bounds while retaining original endpoint identity.
- Keep labels visible for very narrow or flat rectangles by centering against the bounds and clamping the label box to the canvas.
- Format Price Range percentage with two decimals and signed absolute values with up to four meaningful decimals below `$1` and two decimals otherwise.
- Render `—%` when percentage is unavailable.
- Render Date Range as `1 bar` or `N bars`.
- Use green/red Price Range colors, blue Date Range color, and yellow selection styling.

Extend `drawPreview` to obtain the pointer price/time from chart coordinates and display the correct live metrics for either range tool.

- [ ] **Step 4: Add persistent placement**

Use `rangeDrawingTypeForTool` to map toolbar IDs to stored types. First click retains `pendingP1`; second click persists `{type, p1:pendingP1, p2:{price,time}}`, rejects only when both pixel dimensions are below a small minimum, clears the hint, saves, and returns to Pan / Select.

- [ ] **Step 5: Add final rendering**

In `drawOne`, map both anchors to canvas coordinates and render through the shared range visual:

- Price Range metrics always use stored semantic `p1.price` to `p2.price`.
- Date Range count always uses the full `resampleBars(currentBars,currentTF)` series, independent of viewport.
- Selected ranges show handles at the actual `p1` and `p2` coordinates.

- [ ] **Step 6: Add hit testing and drag behavior**

For `priceRange` and `dateRange`:

- Apply the simulation cutoff guard before coordinate mapping.
- Return `p1`/`p2` near endpoint handles.
- Return `whole` inside an endpoint-threshold-expanded rectangle, including flat/narrow ranges and the label region.
- Reuse the two-anchor drag behavior so endpoint drags resize and whole drags translate both anchors.

- [ ] **Step 7: Run focused and related tests**

Run:

```bash
node --test tests/chart_range_drawing.test.cjs tests/chart_circle_drawing.test.cjs
node --test tests/offline_local_mode.test.cjs tests/portfolio_setup_defaults.test.cjs
```

Expected: all tests pass.

- [ ] **Step 8: Commit persistent range behavior**

```bash
git add Big_movers.html tests/chart_range_drawing.test.cjs
git commit -m "feat: add persistent price and date ranges"
```

### Task 4: Final Automated and Browser Verification

**Files:**
- Verify: `Big_movers.html`
- Verify: `tests/chart_range_drawing.test.cjs`

- [ ] **Step 1: Parse all inline scripts and run the complete Node suite**

Run the inline-script compilation check, then:

```bash
node --test tests/*.test.cjs
```

Expected: zero syntax errors and zero test failures.

- [ ] **Step 2: Start or reuse the local application**

Run:

```bash
PORTNUM=5063 python3 Big_movers_server.py
```

Open `http://127.0.0.1:5063`. Before placing test drawings, snapshot the chosen symbol's existing drawings entry so it can be restored exactly afterward.

- [ ] **Step 3: Browser-test Price Range**

Verify:

1. `Alt+P` and the toolbar button activate Price Range.
2. First click plus pointer movement shows a green/red live rectangle and prominent percentage.
3. Second click persists it and returns to Pan / Select.
4. Positive, negative, and sub-dollar cases show correct percentage and absolute-change formatting.
5. Selection, both resize handles, whole movement, Delete/Backspace, undo, lock, save/reload, Clear, zoom, pan, price-scale changes, and cutoff behavior work without console errors.

- [ ] **Step 4: Browser-test Date Range**

Verify:

1. `Alt+M` and the toolbar button activate Date Range.
2. Same-bar selection shows `1 bar`; multi-bar and reversed selection use inclusive counts.
3. D/W/M switches recalculate against the full active-timeframe series.
4. Panning and zooming do not change the count within one timeframe.
5. Selection, resizing, movement, save/reload, deletion, undo, lock, Clear, and cutoff behavior match Price Range.

- [ ] **Step 5: Restore local test state**

Restore the exact saved drawings entry captured before the smoke test and restore any changed drawing-lock or tool-setting state. Close the browser session. Do not stop a server process that was already running before verification.

- [ ] **Step 6: Check the final repository state**

Run:

```bash
git diff --check
git status --short --branch
git log -7 --oneline
```

Expected: only the user's pre-existing `collected_stocks/EAT.csv`, `drawings.json`, and `metadata.json` modifications remain unstaged; implementation and tests are committed on `main`.
