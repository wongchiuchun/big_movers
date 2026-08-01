# Annotation Versions and Manual Leg Reviews Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three isolated chart-annotation versions and optional date-range manual leg notes without changing existing Study Notes or AI reviews.

**Architecture:** Keep `drawings.json` backward-compatible by adding an optional per-drawing `version` field and place all active-version filtering/mutation behind small helper functions. Store manual legs in existing per-move metadata as normalized `{id,start,end,notes}` records, and reuse the current chart range-highlight seam for selection and review navigation.

**Tech Stack:** Vanilla HTML/CSS/JavaScript in `Big_movers.html`, Node.js built-in test runner, existing Flask JSON persistence endpoints.

---

## File Map

- Modify `Big_movers.html`: drawing-version helpers/state, scoped drawing operations, responsive topbar controls, reset confirmation, manual-leg helpers/state, Study UI, range selection, and highlighting.
- Create `tests/annotation_versions.test.cjs`: focused legacy/scoping behavior plus toolbar integration checks.
- Create `tests/manual_leg_reviews.test.cjs`: focused date normalization/sorting/update behavior plus Study UI integration checks.
- Modify `README.md`: briefly document annotation versions and optional manual leg detail notes.

No server endpoint or JSON file is modified directly. Runtime persistence continues through `/api/drawings` and `/api/metadata`.

### Task 1: Add the drawing-version seam

**Files:**
- Create: `tests/annotation_versions.test.cjs`
- Modify: `Big_movers.html:6481-6601`

- [ ] **Step 1: Write the failing drawing-version helper test**

Create a small function extractor following `tests/chart_range_drawing.test.cjs`. Test legacy normalization, filtering, and scoped replacement:

```js
test('drawing versions preserve legacy data and scope switch, add, delete, reset, and undo', () => {
  const {
    drawingVersionOf,
    drawingsForVersion,
    replaceDrawingVersion,
    addDrawingToVersion,
    removeDrawingFromVersion,
    setDrawingVersionForKey,
    restoreDrawingVersionFromHistory
  } = loadFunctions([
    'drawingVersionOf',
    'drawingsForVersion',
    'replaceDrawingVersion',
    'addDrawingToVersion',
    'removeDrawingFromVersion',
    'setDrawingVersionForKey',
    'restoreDrawingVersionFromHistory'
  ]);
  const all = [
    { id: 1, type: 'text' },
    { id: 2, type: 'arrow', version: 2 },
    { id: 3, type: 'circle', version: 3 },
    { id: 4, type: 'seg', version: 99 }
  ];

  assert.equal(drawingVersionOf(all[0]), 1);
  assert.equal(drawingVersionOf(all[3]), 1);
  assert.deepEqual(plain(drawingsForVersion(all, 1)).map(d => d.id), [1, 4]);
  assert.deepEqual(
    plain(replaceDrawingVersion(all, 2, [{ id: 5, type: 'note', version: 2 }])).map(d => d.id),
    [1, 3, 4, 5]
  );

  const state = setDrawingVersionForKey({}, 'ABVX_2025', 2);
  assert.equal(state.ABVX_2025, 2);
  const added = addDrawingToVersion(all, 2, { id: 5, type: 'note' });
  assert.equal(drawingVersionOf(added.at(-1)), 2);
  const removed = removeDrawingFromVersion(added, 2, 2);
  assert.deepEqual(plain(removed).map(d => d.id), [1, 3, 4, 5]);

  const reset = replaceDrawingVersion(removed, 2, []);
  assert.deepEqual(plain(reset).map(d => d.id), [1, 3, 4]);
  const restored = restoreDrawingVersionFromHistory(reset, [
    { moveKey: 'OTHER_2025', version: 2, snapshot: [] },
    { moveKey: 'ABVX_2025', version: 2, snapshot: [{ id: 2, version: 2 }] }
  ], 'ABVX_2025', 2);
  assert.deepEqual(plain(restored.drawings).map(d => d.id), [1, 3, 4, 2]);
  assert.equal(restored.history.length, 1);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/annotation_versions.test.cjs`

Expected: FAIL because `drawingVersionOf` is not defined.

- [ ] **Step 3: Implement the pure helpers and active-version state**

Add near the drawing globals:

```js
let activeDrawingVersions = {}; // session-only, keyed by SYMBOL_YEAR

function drawingVersionOf(d) {
  const value = Number(d && d.version);
  return Number.isInteger(value) && value >= 1 && value <= 3 ? value : 1;
}

function drawingsForVersion(list, version) {
  const value = Number(version);
  const target = Number.isInteger(value) && value >= 1 && value <= 3 ? value : 1;
  return (Array.isArray(list) ? list : []).filter(d => drawingVersionOf(d) === target);
}

function replaceDrawingVersion(list, version, replacement) {
  const value = Number(version);
  const target = Number.isInteger(value) && value >= 1 && value <= 3 ? value : 1;
  const keep = (Array.isArray(list) ? list : []).filter(d => drawingVersionOf(d) !== target);
  return keep.concat(Array.isArray(replacement) ? replacement : []);
}

function addDrawingToVersion(list, version, drawing) {
  const target = Number.isInteger(Number(version)) && Number(version) >= 1 && Number(version) <= 3
    ? Number(version) : 1;
  return (Array.isArray(list) ? list : []).concat({ ...drawing, version: target });
}

function removeDrawingFromVersion(list, version, id) {
  const target = Number.isInteger(Number(version)) && Number(version) >= 1 && Number(version) <= 3
    ? Number(version) : 1;
  return (Array.isArray(list) ? list : []).filter(d =>
    drawingVersionOf(d) !== target || d.id !== id
  );
}

function setDrawingVersionForKey(state, key, version) {
  const target = Number.isInteger(Number(version)) && Number(version) >= 1 && Number(version) <= 3
    ? Number(version) : 1;
  return { ...(state || {}), [key]: target };
}

function restoreDrawingVersionFromHistory(list, history, moveKey, version) {
  const entries = Array.isArray(history) ? history.slice() : [];
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (entry.moveKey === moveKey && entry.version === version) {
      entries.splice(i, 1);
      return {
        drawings: replaceDrawingVersion(list, version, entry.snapshot),
        history: entries,
        restored: true
      };
    }
  }
  return { drawings: list, history: entries, restored: false };
}

function activeDrawingVersion(key = drawKey()) {
  return key && Number.isInteger(activeDrawingVersions[key]) && activeDrawingVersions[key] >= 1 && activeDrawingVersions[key] <= 3
    ? activeDrawingVersions[key]
    : 1;
}

function activeDrawings(key = drawKey()) {
  return key ? drawingsForVersion(drawings[key], activeDrawingVersion(key)) : [];
}
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `node --test tests/annotation_versions.test.cjs`

Expected: PASS.

- [ ] **Step 5: Commit the helper seam**

```bash
git add Big_movers.html tests/annotation_versions.test.cjs
git commit -m "feat: add drawing version helpers"
```

### Task 2: Scope every drawing operation and add responsive version controls

**Files:**
- Modify: `Big_movers.html:185-194, 5231-5320, 6481-6725, 7884-8995`
- Modify: `tests/annotation_versions.test.cjs`

- [ ] **Step 1: Add a failing integration regression test**

Keep this source-level test intentionally focused. It should assert:

```js
test('annotation controls switch and reset only the active version without toolbar overflow', () => {
  assert.match(html, /class="drawing-version-group"/);
  assert.match(html, /data-drawing-version="1"/);
  assert.match(html, /data-drawing-version="2"/);
  assert.match(html, /data-drawing-version="3"/);
  assert.match(html, /id="drawing-version-reset"/);
  assert.doesNotMatch(html, /id="tool-clear"/);
  assert.match(html, /\.drawing-version-group\s*\{[^}]*flex:\s*0 0 auto/s);
  assert.match(html, /\.chart-topbar\s*\{[^}]*flex-wrap:\s*wrap/s);

  const redraw = extractFunction(html, 'redrawAll');
  const add = extractFunction(html, 'addDrawing');
  const undo = extractFunction(html, 'undoActiveDrawingVersion');
  const selectRow = extractFunction(html, 'selectRow');
  assert.match(redraw, /activeDrawings\(/);
  assert.match(add, /addDrawingToVersion\(/);
  assert.match(undo, /restoreDrawingVersionFromHistory\(/);
  assert.match(selectRow, /syncDrawingVersionControls\(\)/);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/annotation_versions.test.cjs`

Expected: FAIL because the controls and scoped operations are missing.

- [ ] **Step 3: Add the responsive topbar group and remove the duplicate clear tool**

Add the approved topbar group near the existing `Txt` and lock controls:

```html
<div class="drawing-version-group" role="group" aria-label="Annotation versions">
  <span class="drawing-version-label">Versions</span>
  <button type="button" data-drawing-version="1" class="drawing-version-btn active">1</button>
  <button type="button" data-drawing-version="2" class="drawing-version-btn">2</button>
  <button type="button" data-drawing-version="3" class="drawing-version-btn">3</button>
  <button type="button" id="drawing-version-reset" class="drawing-version-reset" title="Reset active annotation version" aria-label="Reset active annotation version">↺</button>
</div>
```

Use a non-breaking group that may wrap only as a whole:

```css
.drawing-version-group {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  min-width: max-content;
  height: var(--ctrl);
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 9px;
}
.drawing-version-btn,
.drawing-version-reset { flex: 0 0 27px; width: 27px; height: 100%; }
```

Remove `#tool-clear` from the vertical drawing toolbar markup and collapsed-toolbar CSS so there is only one destructive action.

- [ ] **Step 4: Route rendering, hit-testing, mutations, and undo through the seam**

Update these paths to use `activeDrawings(dk)` or a scoped replacement:

- `redrawAll`
- `getDrawing`
- `hitTest`
- `hitTestFull`
- `addDrawing`
- delete/backspace
- text/note replacement during double-click editing
- drag undo
- `Ctrl/Cmd+Z`

Store undo entries as active-version snapshots:

```js
function pushUndo() {
  const dk = drawKey();
  if (!dk) return;
  const version = activeDrawingVersion(dk);
  undoHistory.push({
    moveKey: dk,
    version,
    snapshot: JSON.parse(JSON.stringify(activeDrawings(dk)))
  });
  if (undoHistory.length > 50) undoHistory.shift();
}

function undoActiveDrawingVersion() {
  const dk = drawKey();
  const version = activeDrawingVersion(dk);
  const result = restoreDrawingVersionFromHistory(drawings[dk], undoHistory, dk, version);
  drawings[dk] = result.drawings;
  undoHistory = result.history;
  return result.restored;
}
```

When adding or deleting, use the behavior-tested helpers:

```js
drawings[dk] = addDrawingToVersion(drawings[dk], activeDrawingVersion(dk), d);
drawings[dk] = removeDrawingFromVersion(drawings[dk], activeDrawingVersion(dk), selectedId);
```

- [ ] **Step 5: Implement version switching and confirmed reset**

Switching must deselect, cancel pending drawing/manual-leg selection, restore chart interaction, update button state through `syncDrawingVersionControls()`, and redraw. `selectRow()` must also call `syncDrawingVersionControls()` after assigning `currentMoveRow`, so changing charts highlights that chart's session-restored version or version 1 rather than leaving the previous chart's button active. Reset must name the move and version, call `pushUndo()`, replace only the active set with `[]`, save, and remain undoable.

```js
function resetActiveDrawingVersion() {
  const dk = drawKey();
  const version = activeDrawingVersion(dk);
  if (!dk || !activeDrawings(dk).length) return;
  if (!confirm(`Reset annotation version ${version} on ${dk.replace('_', ' ')}? Other versions are not affected.`)) return;
  pushUndo();
  drawings[dk] = replaceDrawingVersion(drawings[dk], version, []);
  selectedId = null;
  redrawAll();
  saveDrawings();
}
```

- [ ] **Step 6: Run the focused test and existing drawing tests**

Run: `node --test tests/annotation_versions.test.cjs tests/chart_circle_drawing.test.cjs tests/chart_range_drawing.test.cjs`

Expected: PASS.

- [ ] **Step 7: Commit drawing-version behavior**

```bash
git add Big_movers.html tests/annotation_versions.test.cjs
git commit -m "feat: add chart annotation versions"
```

### Task 3: Add pure manual-leg normalization and editing helpers

**Files:**
- Create: `tests/manual_leg_reviews.test.cjs`
- Modify: `Big_movers.html:7834-7870, 9953-10165`

- [ ] **Step 1: Write the failing manual-leg helper test**

Extract `_drawingTimeKey`, `normalizeManualLegDate`, `normalizeManualLegs`, `updateManualLegNotes`, and `deleteManualLeg` into a VM sandbox. Cover reverse selection, invalid legs, ordering, deletion/renumber-ready output, and note independence:

```js
test('manual legs normalize, sort, and update notes independently', () => {
  const { normalizeManualLegs, updateManualLegNotes, deleteManualLeg } = loadFunctions([
    '_drawingTimeKey',
    'normalizeManualLegDate',
    'normalizeManualLegs',
    'updateManualLegNotes',
    'deleteManualLeg'
  ]);
  const legs = normalizeManualLegs([
    { id: 'b', start: '2025-09-10', end: '2025-08-01', notes: 'later', future: { keep: true } },
    { id: 'a', start: '2025-05-01', end: '2025-06-01', notes: 'earlier' },
    { id: 'bad', start: 'not-a-date', end: '2025-06-01', notes: 'skip' }
  ]);

  assert.deepEqual(plain(legs).map(l => [l.id, l.start, l.end]), [
    ['a', '2025-05-01', '2025-06-01'],
    ['b', '2025-08-01', '2025-09-10']
  ]);
  const updated = updateManualLegNotes(legs, 'b', 'changed');
  assert.equal(updated[0].notes, 'earlier');
  assert.equal(updated[1].notes, 'changed');
  assert.deepEqual(plain(updated[1].future), { keep: true });
  const afterDelete = deleteManualLeg(updated, 'a');
  assert.deepEqual(plain(afterDelete).map((leg, index) => [index + 1, leg.id]), [[1, 'b']]);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/manual_leg_reviews.test.cjs`

Expected: FAIL because the manual-leg helpers are missing.

- [ ] **Step 3: Implement the pure helpers**

```js
function normalizeManualLegDate(value) {
  const key = _drawingTimeKey(value);
  if (key == null) return null;
  const text = String(key).padStart(8, '0');
  return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
}

function normalizeManualLegs(value) {
  if (!Array.isArray(value)) return [];
  return value.map((leg, index) => {
    const source = leg && typeof leg === 'object' ? leg : {};
    let start = normalizeManualLegDate(source.start);
    let end = normalizeManualLegDate(source.end);
    if (!start || !end) return null;
    if (start > end) [start, end] = [end, start];
    return {
      ...source,
      id: String(source.id || `legacy-${index}-${start}-${end}`),
      start,
      end,
      notes: String(source.notes || '')
    };
  }).filter(Boolean).sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end));
}

function updateManualLegNotes(legs, id, notes) {
  return normalizeManualLegs(legs).map(leg =>
    leg.id === id ? { ...leg, notes: String(notes || '') } : leg
  );
}

function deleteManualLeg(legs, id) {
  return normalizeManualLegs(legs).filter(leg => leg.id !== id);
}
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `node --test tests/manual_leg_reviews.test.cjs`

Expected: PASS.

- [ ] **Step 5: Commit the manual-leg domain helpers**

```bash
git add Big_movers.html tests/manual_leg_reviews.test.cjs
git commit -m "feat: add manual leg review helpers"
```

### Task 4: Add optional Manual Leg Reviews to Study

**Files:**
- Modify: `Big_movers.html:198-282, 5417-5438, 8390-8535, 9953-10305, 10450-10490`
- Modify: `tests/manual_leg_reviews.test.cjs`

**Required integration points in `Big_movers.html`:** `setTool`, `setTimeframe`, `selectRow`, `saveMetadata`, both chart click subscriptions, the crosshair-move subscription, and `updateStudyPanel`.

- [ ] **Step 1: Add a failing Study integration regression test**

Assert the new subsection is after `review-box` and independent from `study-notes`, plus the selection hooks exist:

```js
test('manual leg reviews are optional additional detail below AI review', () => {
  const reviewPos = html.indexOf('id="review-box"');
  const manualPos = html.indexOf('id="manual-leg-reviews"');
  const notesPos = html.indexOf('id="study-notes"');
  assert.ok(reviewPos >= 0 && manualPos > reviewPos && notesPos > manualPos);
  assert.match(html, /id="manual-leg-add"/);
  assert.match(html, /id="manual-leg-save-status"/);
  assert.match(html, /function startManualLegPick\(/);
  assert.match(html, /function renderManualLegReviews\(/);
  assert.match(html, /showDateRangeHighlight\(/);
  assert.doesNotMatch(extractFunction(html, 'renderManualLegReviews'), /study-notes/);
  assert.match(extractFunction(html, 'saveMetadata'), /if\s*\(!r\.ok\)/);
  assert.match(extractFunction(html, 'saveMetadata'), /return false/);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/manual_leg_reviews.test.cjs`

Expected: FAIL because the subsection and interaction functions are missing.

- [ ] **Step 3: Add the optional Study subsection and styles**

Insert directly after the existing AI Review section, regardless of whether review content exists:

```html
<div class="study-section" id="manual-leg-reviews">
  <div class="study-label manual-leg-title">
    <span>Manual Leg Reviews</span>
    <button type="button" id="manual-leg-add">+ Add manual leg</button>
  </div>
  <div id="manual-leg-list"></div>
  <div id="manual-leg-save-status" role="status"></div>
</div>
```

Render no empty textarea when the list is empty. Each saved item displays `Leg N`, dates, one textarea, and a delete button.

- [ ] **Step 4: Implement selection state and chart-click consumption**

Add state for active selection, first date, and same-event click consumption. The drawing click handler must give simulation picking first priority, then manual-leg picking, then drawing tools. The second pan/select click subscription must ignore a click consumed by manual-leg picking.

Implement:

```text
startManualLegPick()
handleManualLegChartPick(time) -> boolean consumed
cancelManualLegPick()
finishManualLegPick(start, end)
```

Requirements:

- Start cancels any pending drawing and enters two-point selection.
- First click stores the normalized start and previews the range as the crosshair moves.
- Second click creates a stable ID, normalizes/sorts legs, persists through `setMeta`, rerenders, and opens the new textarea.
- Escape, chart change, timeframe change, annotation-version change, or choosing a drawing tool cancels selection.
- Prevent the same chart click from also selecting an existing drawing.

- [ ] **Step 5: Reuse one range-highlight helper for AI and manual legs**

Extract the date-based portion of `showLegHighlight`:

```js
function showDateRangeHighlight(start, end) {
  const hl = document.getElementById('leg-highlight');
  if (!hl || !chart || !start || !end) return hideLegHighlight();
  const x1 = time2p(start);
  const x2 = time2p(end);
  if (x1 == null || x2 == null) return hideLegHighlight();
  hl.style.left = Math.min(x1, x2) + 'px';
  hl.style.width = (Math.abs(x2 - x1) || 4) + 'px';
  hl.style.display = 'block';
}
```

Keep `showLegHighlight(legEl)` as the AI-review adapter and use `showDateRangeHighlight` for manual rows and selection preview.

- [ ] **Step 6: Implement independent notes and confirmed deletion**

Use a 500 ms debounce keyed by move key and leg ID. Capture the move row before scheduling so switching charts cannot save text to the wrong chart. Persist only `manualLegs`; never read from or write to `m.notes`, `study-notes`, `reviewsCache`, or `reviews.json`.

Make `saveMetadata()` report HTTP and network failures without changing its existing callers:

```js
async function saveMetadata() {
  try {
    const r = await fetch('/api/metadata', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(metadata)
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return true;
  } catch (e) {
    return false;
  }
}
```

The manual-leg debounce updates in-memory metadata before awaiting persistence, so typed text remains visible on failure. After the debounce, await `saveMetadata()` and set `#manual-leg-save-status` to a non-blocking `Could not save leg notes` message when it returns `false`; clear the message on the next successful save.

Deletion confirmation must name the displayed leg and range. After deletion, normalize/sort and rerender so numbering closes the gap.

- [ ] **Step 7: Render manual legs from `updateStudyPanel`**

Call `renderManualLegReviews()` after `updateReviewSection()`. The manual section must still render when `reviewsCache[key]` is absent.

- [ ] **Step 8: Run focused Study tests**

Run: `node --test tests/manual_leg_reviews.test.cjs tests/annotation_versions.test.cjs`

Expected: PASS.

- [ ] **Step 9: Commit manual leg UI**

```bash
git add Big_movers.html tests/manual_leg_reviews.test.cjs
git commit -m "feat: add manual chart leg reviews"
```

### Task 5: Document and verify the complete feature

**Files:**
- Modify: `README.md:27-52`

- [ ] **Step 1: Update the feature documentation**

Add concise bullets explaining:

- Each chart supports three switchable annotation versions; existing drawings are version 1.
- Reset affects only the active version and requires confirmation.
- Manual Leg Reviews are optional date-range detail notes below AI Review and remain separate from main Study Notes.

- [ ] **Step 2: Run the focused tests**

Run: `node --test tests/annotation_versions.test.cjs tests/manual_leg_reviews.test.cjs tests/chart_circle_drawing.test.cjs tests/chart_range_drawing.test.cjs`

Expected: PASS.

- [ ] **Step 3: Run the full JavaScript suite once**

Run: `node --test tests/*.test.cjs`

Expected: all tests pass with zero failures.

- [ ] **Step 4: Run repository hygiene checks**

Run: `git diff --check`

Expected: no output.

Run: `git status --short`

Expected: only intended feature files are modified before the final commit.

- [ ] **Step 5: Perform the short manual verification checklist**

Verify in the local application:

1. Legacy drawings appear in version 1.
2. Versions 1/2/3 switch without sharing drawings.
3. Reset cancellation and confirmation affect only the active version; undo restores it.
4. Narrowing the chart wraps the intact version group inside the topbar border.
5. Manual legs sort chronologically and retain independent text after reload.
6. Deleting a middle manual leg requires confirmation and renumbers the remaining legs without moving their notes.
7. Main Study Notes and AI Review remain unchanged.

If GUI automation is unavailable, hand this seven-item checklist to the user rather than expanding automated coverage.

- [ ] **Step 6: Commit documentation and any final test-only corrections**

```bash
git add README.md Big_movers.html tests/annotation_versions.test.cjs tests/manual_leg_reviews.test.cjs
git commit -m "docs: describe annotation versions and manual leg reviews"
```

- [ ] **Step 7: Request final code review**

Use `superpowers:requesting-code-review` against the merge base. Address Critical or Important findings, rerun the focused tests and the full suite, and keep Minor findings advisory unless they affect correctness.
