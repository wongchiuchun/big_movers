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

test('circle geometry uses the centre-to-edge pixel distance as radius', () => {
  const { getCircleGeometry } = loadFunctions(['getCircleGeometry']);

  assert.deepEqual(
    plain(getCircleGeometry(10, 20, 13, 24)),
    { cx: 10, cy: 20, edgeX: 13, edgeY: 24, radius: 5 }
  );
});

test('circle hit classification distinguishes resize handle and whole circle', () => {
  const { getCircleGeometry, getCircleHitPart } = loadFunctions([
    'getCircleGeometry',
    'getCircleHitPart'
  ]);
  const geometry = getCircleGeometry(100, 100, 120, 100);

  assert.equal(getCircleHitPart(120, 100, geometry, 8, 10), 'radius');
  assert.equal(getCircleHitPart(100, 100, geometry, 8, 10), 'whole');
  assert.equal(getCircleHitPart(100, 120, geometry, 8, 10), 'whole');
  assert.equal(getCircleHitPart(108, 108, geometry, 8, 10), null);
});
