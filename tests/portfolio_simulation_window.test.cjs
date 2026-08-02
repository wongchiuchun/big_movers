const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'Big_movers.html'), 'utf8');

function extractFunction(source, name) {
  const start = source.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('Function not found: ' + name);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index++) {
    if (source[index] === '{') depth++;
    if (source[index] === '}') {
      depth--;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error('Unclosed function: ' + name);
}

function loadWindowHelper() {
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(
    extractFunction(html, '_toDateStr') + '\n' +
      extractFunction(html, '_makeRandomWindow') +
      '\nthis.makeWindow = _makeRandomWindow;',
    sandbox
  );
  return sandbox.makeWindow;
}

function sequenceRng(values) {
  let index = 0;
  return function () {
    return values[index++];
  };
}

function daysBetween(range) {
  return (Date.parse(range.end) - Date.parse(range.start)) / 86400000;
}

test('standard windows retain the 120-day floor and year-end cap', () => {
  const makeWindow = loadWindowHelper();
  assert.equal(daysBetween(makeWindow(2020, sequenceRng([0, 0, 0]), false)), 120);

  const late = makeWindow(
    2020,
    sequenceRng([0.999999, 0.999999, 0.999999]),
    false
  );
  assert.equal(late.start, '2020-08-28');
  assert.equal(late.end, '2020-12-31');
});

test('extended windows span 180 to 270 calendar days and may cross year-end', () => {
  const makeWindow = loadWindowHelper();
  assert.equal(daysBetween(makeWindow(2020, sequenceRng([0, 0, 0]), true)), 180);

  const longest = makeWindow(
    2020,
    sequenceRng([0.999999, 0.999999, 0.999999]),
    true
  );
  assert.equal(longest.start, '2020-08-28');
  assert.equal(daysBetween(longest), 270);
  assert.match(longest.end, /^2021-/);
});
