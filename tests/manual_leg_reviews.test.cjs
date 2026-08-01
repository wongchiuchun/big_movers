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
  assert.doesNotMatch(extractFunction(html, 'cancelManualLegPick'), /manualLegClickConsumed\s*=\s*false/);
  assert.match(html, /if\(manualLegPick\|\|manualLegClickConsumed\)return;/);
  assert.match(extractFunction(html, 'loadIndexInChart'), /if\(manualLegPick\)cancelManualLegPick\(\)/);
  assert.match(extractFunction(html, 'setupDrag'), /if\(manualLegPick\)return;/);
  assert.match(extractFunction(html, 'clearCurrentMoveRow'), /cancelManualLegPick\(\)/);
  assert.equal((html.match(/currentMoveRow\s*=\s*null/g) || []).length, 2);
  assert.match(extractFunction(html, 'saveMetadata'), /if\s*\(!r\.ok\)/);
  assert.match(extractFunction(html, 'saveMetadata'), /return false/);
});

test('metadata saves are serialized in call order', async () => {
  const payloads = [];
  let active = 0;
  let maxActive = 0;
  let releaseFirst;
  const metadata = { version: 1, customTags: [], items: { move: { notes: 'first' } } };
  const sandbox = {
    metadata,
    metadataSaveQueue: Promise.resolve(),
    fetch: async (_url, options) => {
      payloads.push(JSON.parse(options.body));
      active++;
      maxActive = Math.max(maxActive, active);
      if (payloads.length === 1) {
        await new Promise(resolve => { releaseFirst = resolve; });
      }
      active--;
      return { ok: true };
    }
  };
  vm.createContext(sandbox);
  const saveSource = extractFunction(html, 'saveMetadata').replace(/^function /, 'async function ');
  vm.runInContext(saveSource + '\nthis.saveMetadata = saveMetadata;', sandbox);

  const first = sandbox.saveMetadata();
  await new Promise(resolve => setImmediate(resolve));
  metadata.items.move.notes = 'second';
  const second = sandbox.saveMetadata();
  releaseFirst();

  assert.equal(await first, true);
  assert.equal(await second, true);
  assert.equal(maxActive, 1);
  assert.deepEqual(payloads.map(payload => payload.items.move.notes), ['first', 'second']);
});
