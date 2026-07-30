# Chart Circle Drawing Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, resizable, outline-only perfect-circle annotation to the chart drawing toolbar.

**Architecture:** Extend the existing overlay-canvas drawing system in `Big_movers.html` with a `circle` drawing type represented by centre anchor `p1` and circumference anchor `p2`. Keep circle geometry and hit classification in small pure helpers so the important behavior can be tested directly, while reusing the existing two-point placement, persistence, selection, undo, locking, cutoff, and drag infrastructure.

**Tech Stack:** Browser JavaScript, HTML/CSS, Canvas 2D, Node.js built-in test runner.

---

## File Map

- Modify `Big_movers.html`: toolbar UI, saved tool settings, circle geometry, rendering, preview, placement, selection, drag/resize, and keyboard shortcut.
- Create `tests/chart_circle_drawing.test.cjs`: direct geometry tests plus focused integration assertions against the HTML application.
- Reference `docs/superpowers/specs/2026-07-30-chart-circle-drawing-tool-design.md`: approved behavior and scope.

### Task 1: Circle Geometry and Hit Classification

**Files:**
- Create: `tests/chart_circle_drawing.test.cjs`
- Modify: `Big_movers.html`

- [ ] **Step 1: Write the failing geometry tests**

Create a Node test that reads `Big_movers.html`, extracts named function declarations, evaluates them in a VM, and asserts:

```js
test('circle geometry uses the centre-to-edge pixel distance as radius', () => {
  const { getCircleGeometry } = loadFunctions(['getCircleGeometry']);
  assert.deepEqual(
    plain(getCircleGeometry(10, 20, 13, 24)),
    { cx: 10, cy: 20, edgeX: 13, edgeY: 24, radius: 5 }
  );
});

test('circle hit classification distinguishes resize handle and whole circle', () => {
  const { getCircleGeometry, getCircleHitPart } = loadFunctions(
    ['getCircleGeometry', 'getCircleHitPart']
  );
  const g = getCircleGeometry(100, 100, 120, 100);
  assert.equal(getCircleHitPart(120, 100, g, 8, 10), 'radius');
  assert.equal(getCircleHitPart(100, 100, g, 8, 10), 'whole');
  assert.equal(getCircleHitPart(100, 120, g, 8, 10), 'whole');
  assert.equal(getCircleHitPart(108, 108, g, 8, 10), null);
});
```

The extractor must load functions in order and expose them on the VM sandbox. Use JSON serialization for cross-realm value comparison.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
node --test tests/chart_circle_drawing.test.cjs
```

Expected: FAIL because `getCircleGeometry` is not present.

- [ ] **Step 3: Add the minimal pure helpers**

Near the existing arrow geometry helper in `Big_movers.html`, add:

```js
function getCircleGeometry(cx,cy,edgeX,edgeY){
  return {cx,cy,edgeX,edgeY,radius:Math.hypot(edgeX-cx,edgeY-cy)};
}

function getCircleHitPart(mx,my,geometry,threshold,endpointThreshold){
  if(Math.hypot(mx-geometry.edgeX,my-geometry.edgeY)<endpointThreshold)return'radius';
  if(Math.hypot(mx-geometry.cx,my-geometry.cy)<endpointThreshold)return'whole';
  return Math.abs(Math.hypot(mx-geometry.cx,my-geometry.cy)-geometry.radius)<threshold?'whole':null;
}
```

- [ ] **Step 4: Run the test and verify GREEN**

Run:

```bash
node --test tests/chart_circle_drawing.test.cjs
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit the geometry seam**

```bash
git add Big_movers.html tests/chart_circle_drawing.test.cjs
git commit -m "test: define chart circle geometry"
```

### Task 2: Toolbar and Persistent Circle Settings

**Files:**
- Modify: `tests/chart_circle_drawing.test.cjs`
- Modify: `Big_movers.html`

- [ ] **Step 1: Add failing toolbar/settings assertions**

Add a focused test that asserts the application contains:

- `tool-circle` and `cfg-circle` controls.
- A `popup-circle` with blue, orange, and yellow swatches plus custom color, width, and style controls.
- `circle:{color:'#2196f3',width:2,style:'solid'}` in `toolSettings`.
- `circle` in popup setup, saved-settings restoration, `TOOLS`, and the `Alt+C` key map.
- A color-sync function that updates the circle custom input, selected preset, and toolbar icon.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
node --test tests/chart_circle_drawing.test.cjs
```

Expected: the geometry tests pass and the toolbar/settings test fails because the circle UI is absent.

- [ ] **Step 3: Add the Circle toolbar group**

Add an outline-circle icon beside the arrow tool. Add a settings popup using:

- Default/custom color input value `#2196f3`.
- Presets `#2196f3`, `#ff6b35`, and `#f5c842`.
- Width options 1–4, default 2.
- Solid, dashed, and dotted styles.

Add narrowly scoped CSS for circle preset swatches, matching the existing arrow swatch treatment.

- [ ] **Step 4: Wire settings and persistence**

Add the default `toolSettings.circle` object, circle color UI synchronization, generic popup event wiring, saved-settings restoration, `TOOLS` registration, and shortcut mapping:

```js
'c':'circle'
```

Ensure the toolbar icon reflects the current circle color after preset, custom-color, and settings-restoration changes.

- [ ] **Step 5: Run the test and verify GREEN**

Run:

```bash
node --test tests/chart_circle_drawing.test.cjs
```

Expected: all tests pass.

- [ ] **Step 6: Commit the toolbar/settings slice**

```bash
git add Big_movers.html tests/chart_circle_drawing.test.cjs
git commit -m "feat: add circle drawing controls"
```

### Task 3: Placement, Preview, Rendering, Selection, and Editing

**Files:**
- Modify: `tests/chart_circle_drawing.test.cjs`
- Modify: `Big_movers.html`

- [ ] **Step 1: Add failing behavior integration assertions**

Add assertions that verify:

- Circle participates in two-point placement and stores `{type:'circle', p1, p2, color, width, style}`.
- Placement rejects a radius below 4 canvas pixels without clearing `pendingP1`.
- Preview renders an arc using centre-to-pointer distance.
- Final rendering uses `ctx2.arc(...geometry.radius...)` without filling.
- Selected rendering draws centre and circumference handles.
- Hit testing delegates to `getCircleHitPart`.
- Hit testing returns no match when `_drawingExceedsCutoff` says either circle anchor is beyond the simulation cutoff.
- Dragging the `radius` part changes only `p2`; dragging `whole` changes both anchors.

Keep these assertions focused on required wiring; geometry correctness remains covered by direct function tests.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
node --test tests/chart_circle_drawing.test.cjs
```

Expected: existing tests pass and the behavior integration test fails because circle drawing behavior is not wired.

- [ ] **Step 3: Add live preview and placement**

Extend the existing two-point drawing flow:

- First click assigns `pendingP1`.
- Pointer movement calls `redrawAll()` through the existing pending-point path.
- Circle preview draws a dashed perfect circle from `pendingP1` to the current pointer.
- Second click with radius under 4 pixels leaves `pendingP1` intact.
- A valid second click adds the drawing, saves it, clears the hint, and returns to Pan / Select.

- [ ] **Step 4: Add final rendering and selected handles**

In `drawOne`, map both anchors to canvas coordinates, derive `getCircleGeometry`, and stroke one `ctx2.arc` with the existing color, width, selection color, and line-style behavior. Never fill the circle. When selected, draw visible handles at the centre and stored circumference point.

- [ ] **Step 5: Add hit testing and editing**

In `getHitPart`, first apply the same simulation-cutoff guard used by the arrow drawing, then reject unmappable anchors, classify the resize handle as `radius`, and classify the centre/circumference as `whole`. This prevents an invisible future-anchored circle from affecting the cursor, selection, or dragging. In `applyDrag`:

- `radius` updates only `p2`.
- `whole` translates both `p1` and `p2`.

This preserves a perfect circle because the radius is always calculated in current canvas pixels.

- [ ] **Step 6: Run focused and related tests**

Run:

```bash
node --test tests/chart_circle_drawing.test.cjs
node --test tests/portfolio_setup_defaults.test.cjs tests/offline_local_mode.test.cjs
```

Expected: all tests pass.

- [ ] **Step 7: Commit the completed behavior**

```bash
git add Big_movers.html tests/chart_circle_drawing.test.cjs
git commit -m "feat: add resizable chart circles"
```

### Task 4: Final Verification

**Files:**
- Verify: `Big_movers.html`
- Verify: `tests/chart_circle_drawing.test.cjs`

- [ ] **Step 1: Parse every inline script**

Run a Node script that extracts every inline `<script>` block from `Big_movers.html` and compiles each with `new Function(...)`.

Expected: every inline script parses.

- [ ] **Step 2: Run the complete Node test suite**

Run:

```bash
node --test tests/*.test.cjs
```

Expected: zero failures.

- [ ] **Step 3: Run the local browser interaction checklist**

Start the existing local server with:

```bash
PORTNUM=5063 python3 Big_movers_server.py
```

Open `http://127.0.0.1:5063`, choose a ticker with local OHLCV data, and verify:

1. On Daily view, select Circle, click a centre, move the pointer, and confirm a round dashed preview follows the pointer.
2. Click the edge and confirm an outline-only blue circle is created and the tool returns to Pan / Select.
3. Select the circle; confirm centre and circumference handles appear.
4. Drag the circumference handle; confirm only the radius changes and the shape stays round.
5. Drag the centre or a non-handle part of the circumference; confirm the whole circle moves without changing size.
6. Switch among Daily, Weekly, and Monthly; horizontally zoom/pan and change the price scale; confirm the circle remains round and both anchors continue tracking the chart.
7. Change width, solid/dash/dot style, each color preset, and a custom color; place circles and confirm each setting is applied and restored after reload. Confirm an already-saved circle also reloads in the same position and size.
8. Verify Delete, Backspace, undo, lock, and Clear follow existing drawing behavior.
9. During simulation playback, use a fixture/saved circle with one anchor beyond the cutoff; confirm it is neither visible nor selectable until both anchors are revealed.

Expected: every interaction behaves as described without console errors.

- [ ] **Step 4: Check the patch and repository state**

Run:

```bash
git diff --check
git status --short
git log -5 --oneline
```

Expected: no whitespace errors; only the user's pre-existing `collected_stocks/EAT.csv`, `drawings.json`, and `metadata.json` modifications remain unstaged.

- [ ] **Step 5: Review the approved requirements**

Confirm the implementation covers perfect-circle rendering, centre-to-edge placement, live preview, outline-only display, adjustable radius, whole-object movement, presets/custom color, width/style settings, persistence, shortcut, selection, deletion, undo, locking, and simulation cutoff behavior without a server or dependency change.
