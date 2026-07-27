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
  for (let i = brace; i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}') {
      depth--;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error('Unclosed function: ' + name);
}

function loadFunctions(names, extras = {}) {
  const sandbox = { ...extras };
  vm.createContext(sandbox);
  const source = names.map(name => extractFunction(html, name)).join('\n')
    + '\n' + names.map(name => `this.${name} = ${name};`).join('\n');
  vm.runInContext(source, sandbox);
  return sandbox;
}

test('startup uses a bundled chart engine and no remote font assets', () => {
  assert.match(
    html,
    /<script src="vendor\/lightweight-charts\.standalone\.production\.js"><\/script>/
  );
  assert.doesNotMatch(html, /https:\/\/unpkg\.com\/lightweight-charts/);
  assert.doesNotMatch(html, /https:\/\/fonts\.(?:googleapis|gstatic)\.com/);

  const vendorPath = path.join(root, 'vendor', 'lightweight-charts.standalone.production.js');
  assert.ok(fs.existsSync(vendorPath), 'bundled Lightweight Charts file is missing');
  const vendorSource = fs.readFileSync(vendorPath, 'utf8');
  assert.ok(vendorSource.length > 100000, 'bundled chart engine is unexpectedly small');
  assert.match(vendorSource, /LightweightCharts/);
});

function createFetchAllHarness(firstResponse) {
  let autoFetchCalls = 0;
  const sandbox = loadFunctions(
    ['_needsExtend', 'fetchAllTickers'],
    {
      _shiftMonths() { return '2019-09-01'; },
      _fetchOneTicker() { return Promise.resolve(firstResponse); },
      _normalizeOhlcvResponse(json) { return Array.isArray(json) ? json : []; },
      _autoFetchTicker() {
        autoFetchCalls++;
        return Promise.resolve({ ok: false, error: 'offline' });
      },
      $() { return null; },
      Setup: {},
      populateTickerDatalist() {}
    }
  );
  return {
    fetchAllTickers: sandbox.fetchAllTickers,
    autoFetchCalls: () => autoFetchCalls
  };
}

test('portfolio setup does not extend historical local data to today', async () => {
  const bars = [
    { time: '2019-01-02', close: 90 },
    { time: '2020-06-30', close: 110 }
  ];
  const harness = createFetchAllHarness({ _status: 200, json: bars });

  const result = await harness.fetchAllTickers({
    startDate: '2020-01-02',
    endDate: '2020-06-30',
    tickers: [{ symbol: 'LOCAL' }]
  });

  assert.equal(harness.autoFetchCalls(), 0);
  assert.equal(result.perTicker.LOCAL.error, null);
  assert.equal(result.perTicker.LOCAL.bars.length, 2);
});

test('missing local ticker reports an explicit-fetch error without auto-fetching', async () => {
  const harness = createFetchAllHarness({ _status: 404 });

  const result = await harness.fetchAllTickers({
    startDate: '2020-01-02',
    endDate: '2020-06-30',
    tickers: [{ symbol: 'MISSING' }]
  });

  assert.equal(harness.autoFetchCalls(), 0);
  assert.match(result.perTicker.MISSING.error, /No local data/i);
  assert.match(result.perTicker.MISSING.error, /Fetch/i);
});

test('cross-year noise checks local bars without calling fetch-ticker', async () => {
  const requests = [];
  const { _ensureNoiseDataCovers } = loadFunctions(
    ['_ensureNoiseDataCovers'],
    {
      fetch(url) {
        requests.push(url);
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({ error: 'not found' })
        });
      },
      encodeURIComponent
    }
  );

  const result = await _ensureNoiseDataCovers('LOCAL', '2020-01-01', '2020-12-31');

  assert.equal(requests.length, 1);
  assert.equal(requests[0], '/api/ohlcv?symbol=LOCAL');
  assert.equal(result.ok, false);
  assert.match(result.error, /local/i);
});

test('index loading never auto-fetches QQQ', () => {
  const fetchAndLoad = extractFunction(html, 'fetchAndLoad');
  assert.doesNotMatch(fetchAndLoad, /_autoFetchQQQ/);
  assert.doesNotMatch(fetchAndLoad, /\/api\/fetch-ticker/);
});

test('randomizer explains that noise selection is local-only', () => {
  assert.match(html, /Cross-year noise[^]*Uses local price data only/);
  assert.doesNotMatch(html, /Cross-year noise[^]*Will auto-fetch missing price data/);
});
