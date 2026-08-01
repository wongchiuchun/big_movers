const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');

function extractFunction(source, name) {
  const start = source.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('Function not found: ' + name);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let i = brace; i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}') {
      depth--;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error('Unclosed function: ' + name);
}

function loadFunctions(names) {
  const sandbox = {};
  vm.createContext(sandbox);
  const source = names.map(name => extractFunction(html, name)).join('\n')
    + '\n' + names.map(name => `this.${name} = ${name};`).join('\n');
  vm.runInContext(source, sandbox);
  return sandbox;
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

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
  const edit = extractFunction(html, 'setupDrag');
  const save = extractFunction(html, 'saveDrawings');
  const reset = extractFunction(html, 'resetActiveDrawingVersion');
  const selectRow = extractFunction(html, 'selectRow');
  assert.match(redraw, /activeDrawings\(/);
  assert.match(add, /addDrawingToVersion\(/);
  assert.match(undo, /restoreDrawingVersionFromHistory\(/);
  assert.ok((edit.match(/\.\.\.d/g) || []).length >= 2, 'text and note edits preserve unknown drawing fields');
  assert.match(save, /if\s*\(!r\.ok\)/);
  assert.match(save, /return false/);
  assert.match(reset, /await saveDrawings\(/);
  assert.match(selectRow, /syncDrawingVersionControls\(\)/);
});
