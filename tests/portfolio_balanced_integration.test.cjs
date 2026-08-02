const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'Big_movers.html'), 'utf8');
const basketApi = require(path.join(root, 'portfolio_basket.cjs'));

function extractFunction(source, name) {
  let start = source.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('Function not found: ' + name);
  if (source.slice(Math.max(0, start - 6), start) === 'async ') start -= 6;
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

function loadResolver() {
  const names = ['_toDateStr', '_makeRandomWindow', '_uniqueSymbolRows', '_resolveBalancedBasket'];
  const sandbox = { Promise, Set, Map };
  vm.createContext(sandbox);
  vm.runInContext(
    names.map(name => extractFunction(html, name)).join('\n') +
      '\nthis.resolve = _resolveBalancedBasket;',
    sandbox
  );
  return sandbox.resolve;
}

function barsFor(start = '2019-01-01', end = '2021-12-31') {
  return [
    { time: start, close: 10, volume: 3000000 },
    { time: '2020-08-01', close: 10, volume: 3000000 },
    { time: '2020-08-15', close: 10, volume: 3000000 },
    { time: '2020-08-20', close: 10, volume: 3000000 },
    { time: '2020-08-25', close: 10, volume: 3000000 },
    { time: '2020-08-28', close: 10, volume: 3000000 },
    { time: end, close: 10, volume: 3000000 }
  ];
}

test('balanced resolver keeps a viable composition in the same window', async () => {
  const resolve = loadResolver();
  const manifest = {
    data_start: '2015-01-01',
    data_end: '2025-12-31',
    symbols: [
      { symbol: 'GROW', group: 'growth', eligibility: [{ from: '2015-01-01', to: null }] },
      { symbol: 'BROAD', group: 'broad', eligibility: [{ from: '2015-01-01', to: null }] }
    ]
  };
  const rows = [
    { symbol: 'MOVE1', year: 2020 },
    { symbol: 'MOVE2', year: 2020 },
    { symbol: 'NOISE1', year: 2019 }
  ];
  const liquidBars = Array.from({ length: 25 }, (_, index) => ({
    time: index < 24
      ? `2020-08-${String(index + 1).padStart(2, '0')}`
      : '2021-12-31',
    close: 10,
    volume: 3000000
  }));
  liquidBars.unshift({ time: '2019-01-01', close: 10, volume: 3000000 });
  let windowCalls = 0;

  const result = await resolve({
    year: 2020,
    size: 4,
    seed: 'same-window',
    rows,
    manifest,
    makeWindow() {
      windowCalls++;
      return { start: '2020-09-01', end: '2020-12-31' };
    },
    loadBars(symbol) {
      return Promise.resolve(/^NOISE/.test(symbol) ? liquidBars : barsFor());
    },
    basketApi
  });

  assert.ok(result.selection);
  assert.equal(result.attempts.length, 1);
  assert.equal(windowCalls, 1);
  assert.equal(result.selection.rows.length, 4);
  assert.deepEqual(
    { ...result.selection.composition },
    { mover: 2, anchor: 1, noise: 1 }
  );
});

test('balanced resolver stops after twelve distinct failed windows', async () => {
  const resolve = loadResolver();
  const windows = Array.from({ length: 13 }, (_, index) => ({
    start: `2020-${String(index + 1).padStart(2, '0')}-01`,
    end: `2020-${String(index + 1).padStart(2, '0')}-28`
  }));
  let windowCalls = 0;
  let selectCalls = 0;

  const result = await resolve({
    year: 2020,
    size: 6,
    seed: 'twelve-only',
    rows: [{ symbol: 'MOVE', year: 2020 }],
    manifest: {
      data_start: '2015-01-01',
      data_end: '2025-12-31',
      symbols: []
    },
    makeWindow() {
      return windows[windowCalls++];
    },
    loadBars() {
      return Promise.resolve(barsFor());
    },
    basketApi: {
      createRng: basketApi.createRng,
      hasWindowCoverage: basketApi.hasWindowCoverage,
      isAnchorEligible: basketApi.isAnchorEligible,
      noiseLiquidity: basketApi.noiseLiquidity,
      selectBasket() {
        selectCalls++;
        return null;
      }
    }
  });

  assert.equal(result.selection, null);
  assert.equal(result.attempts.length, 12);
  assert.equal(windowCalls, 12);
  assert.equal(selectCalls, 12);
  assert.equal(result.attempts.some(attempt => attempt.start === windows[12].start), false);
});

test('balanced resolver uses extended windows from the shared generator', async () => {
  const resolve = loadResolver();

  const result = await resolve({
    year: 2020,
    size: 6,
    seed: 'extended-cross-year',
    extended: true,
    rows: [],
    manifest: {
      data_start: '2015-01-01',
      data_end: '2025-12-31',
      symbols: []
    },
    loadBars() {
      return Promise.resolve([]);
    },
    basketApi: {
      createRng: basketApi.createRng,
      hasWindowCoverage: basketApi.hasWindowCoverage,
      isAnchorEligible: basketApi.isAnchorEligible,
      noiseLiquidity: basketApi.noiseLiquidity,
      selectBasket() {
        return null;
      }
    }
  });

  assert.equal(result.selection, null);
  assert.equal(result.attempts.length, 12);
  assert.ok(result.attempts.every(attempt => {
    const days = (Date.parse(attempt.end) - Date.parse(attempt.start)) / 86400000;
    return days >= 180 && days <= 270;
  }));
  assert.ok(result.attempts.some(attempt => attempt.end.startsWith('2021-')));
});
