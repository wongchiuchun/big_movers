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

test('range geometry normalizes visual bounds without changing endpoint identity', () => {
  const { getRangeGeometry } = loadFunctions(['getRangeGeometry']);

  assert.deepEqual(plain(getRangeGeometry(30, 40, 10, 15)), {
    x1: 30,
    y1: 40,
    x2: 10,
    y2: 15,
    left: 10,
    top: 15,
    right: 30,
    bottom: 40,
    width: 20,
    height: 25
  });
});

test('price range preserves direction and handles a zero starting price', () => {
  const { calculatePriceRange } = loadFunctions(['calculatePriceRange']);

  assert.deepEqual(plain(calculatePriceRange(10, 12.5)), {
    change: 2.5,
    percentage: 25,
    direction: 'gain'
  });
  assert.deepEqual(plain(calculatePriceRange(20, 15)), {
    change: -5,
    percentage: -25,
    direction: 'loss'
  });
  assert.deepEqual(plain(calculatePriceRange(0, 5)), {
    change: 5,
    percentage: null,
    direction: 'gain'
  });
});

test('nearest timeframe bar accepts BusinessDay anchors and breaks ties earlier', () => {
  const { drawingTimeToMs, nearestBarIndex } = loadFunctions([
    'drawingTimeToMs',
    'nearestBarIndex'
  ]);
  const bars = [
    { time: '2026-01-01' },
    { time: '2026-01-03' },
    { time: '2026-01-05' }
  ];

  assert.equal(nearestBarIndex(bars, { year: 2026, month: 1, day: 2 }), 0);
  assert.equal(nearestBarIndex(bars, { year: 2026, month: 1, day: 5 }), 2);
});

test('date range counts active-timeframe bars inclusively in either direction', () => {
  const { drawingTimeToMs, nearestBarIndex, countBarsInRange } = loadFunctions([
    'drawingTimeToMs',
    'nearestBarIndex',
    'countBarsInRange'
  ]);
  const daily = [1, 2, 3, 4, 5].map(day => ({ time: `2026-01-0${day}` }));
  const weekly = ['2026-01-05', '2026-01-12', '2026-01-19', '2026-01-26']
    .map(time => ({ time }));
  const monthly = ['2026-01-01', '2026-02-01', '2026-03-01']
    .map(time => ({ time }));

  assert.equal(countBarsInRange(daily, '2026-01-03', '2026-01-03'), 1);
  assert.equal(countBarsInRange(daily, '2026-01-02', '2026-01-04'), 3);
  assert.equal(countBarsInRange(daily, '2026-01-04', '2026-01-02'), 3);
  assert.equal(countBarsInRange(weekly, '2026-01-06', '2026-01-26'), 4);
  assert.equal(countBarsInRange(monthly, '2026-01-15', '2026-03-01'), 3);
  assert.equal(countBarsInRange([], '2026-01-01', '2026-01-02'), 0);
});

test('toolbar replaces the temporary measure tool with separate range tools', () => {
  assert.match(html, /\bid="tool-price-range"/);
  assert.match(html, /\bid="tool-date-range"/);
  assert.doesNotMatch(html, /\bid="tool-measure"/);
  assert.match(html, /const TOOLS=\['pan','arrow','circle','hline','line','ray','seg','text','note','price-range','date-range'\]/);
  assert.match(html, /'p':'price-range'/);
  assert.match(html, /'m':'date-range'/);
  assert.match(html, /\.draw-toolbar\.collapsed #tool-price-range/);
  assert.match(html, /\.draw-toolbar\.collapsed #tool-date-range/);
});

test('legacy transient measure state and renderer are removed', () => {
  assert.doesNotMatch(html, /\bmeasureStart\b/);
  assert.doesNotMatch(html, /\bmeasureEnd\b/);
  assert.doesNotMatch(html, /function drawMeasure\(/);
  assert.doesNotMatch(html, /drawTool==='measure'/);
});
