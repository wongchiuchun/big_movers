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

function loadHelpers() {
  const sandbox = { Date, Map };
  vm.createContext(sandbox);
  vm.runInContext(
    extractFunction(html, 'resampleBars') + '\n' +
    extractFunction(html, '_expandedBarsForTimeframe') + '\n' +
    extractFunction(html, '_expandedMarkerTime') + '\n' +
    'this.barsFor = _expandedBarsForTimeframe; this.markerTime = _expandedMarkerTime;',
    sandbox
  );
  return sandbox;
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('expanded timeframe uses daily bars directly and weekly OHLCV from revealed bars only', () => {
  const { barsFor } = loadHelpers();
  const revealed = [
    { time: '2020-12-31', open: 10, high: 12, low: 9, close: 11, volume: 100 },
    { time: '2021-01-01', open: 11, high: 14, low: 10, close: 13, volume: 200 },
    { time: '2021-01-04', open: 13, high: 15, low: 12, close: 14, volume: 300 },
    { time: '2021-01-05', open: 14, high: 16, low: 13, close: 15, volume: 400 }
  ];

  assert.deepEqual(plain(barsFor(revealed, 'D')), revealed);
  assert.deepEqual(plain(barsFor(revealed, 'W')), [
    { time: '2020-12-28', open: 10, high: 14, low: 9, close: 13, volume: 300 },
    { time: '2021-01-04', open: 13, high: 16, low: 12, close: 15, volume: 700 }
  ]);
  assert.equal(plain(barsFor(revealed.slice(0, 3), 'W'))[1].close, 14);
});

test('expanded weekly markers map every event to its containing Monday', () => {
  const { markerTime } = loadHelpers();
  assert.equal(markerTime('2021-01-01', 'W'), '2020-12-28');
  assert.equal(markerTime('2021-01-04', 'W'), '2021-01-04');
  assert.equal(markerTime('2021-01-08', 'W'), '2021-01-04');
  assert.equal(markerTime('2021-01-08', 'D'), '2021-01-08');
});

test('expanded modal exposes Daily Weekly and optional 100/250 EMA controls', () => {
  assert.match(html, /id="portcard-expand-timeframe"/);
  assert.match(html, /data-timeframe="D"[^>]*>Daily</);
  assert.match(html, /data-timeframe="W"[^>]*>Weekly</);
  assert.match(html, /id="portcard-expand-ema100"/);
  assert.match(html, /id="portcard-expand-ema250"/);
  assert.match(html, /expandedChartPrefs/);
  assert.match(html, /ema100/);
  assert.match(html, /ema250/);
});

test('expanded chart transforms revealed bars and long EMAs lazily', () => {
  const open = extractFunction(html, 'open');
  const mount = extractFunction(html, '_mountChart');
  const build = extractFunction(html, '_buildChart');
  assert.match(open, /_mountChart/);
  assert.match(mount, /_expandedBarsForTimeframe/);
  assert.match(build, /prefs\.ema100/);
  assert.match(build, /prefs\.ema250/);
  assert.match(build, /p:\s*100/);
  assert.match(build, /p:\s*250/);
});
