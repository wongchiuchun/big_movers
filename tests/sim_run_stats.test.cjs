const fs = require('fs');
const path = require('path');
const vm = require('vm');

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

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log('PASS:', name);
  } catch (err) {
    failed++;
    console.error('FAIL:', name, '->', err.message);
  }
}

let metricItems;
try {
  const sandbox = {
    _fmt$Signed(value) {
      if (!Number.isFinite(value)) return '—';
      return (value >= 0 ? '+' : '−') + '$' + Math.abs(Math.round(value)).toLocaleString('en-US');
    },
    _fmtPct(value, decimals) {
      if (value == null || !Number.isFinite(value)) return '—';
      return (value >= 0 ? '+' : '') + value.toFixed(decimals == null ? 2 : decimals) + '%';
    }
  };
  vm.createContext(sandbox);
  const fn = extractFunction(html, '_sessionRunMetricItems');
  vm.runInContext(fn + '\nthis.metricItems = _sessionRunMetricItems;', sandbox);
  metricItems = sandbox.metricItems;
} catch (err) {
  console.error('FATAL:', err.message);
  process.exit(1);
}

const session = {
  sessionPnL: 12345.67,
  totalReturnPct: 12.36,
  tradeCount: 10,
  winCount: 6,
  lossCount: 4,
  winRate: 60,
  profitFactor: 2.25,
  avgPctDeployed: 63.4,
  peakPctDeployed: 92.1,
  idlePctOfTime: 14.8,
  indexName: 'SPX',
  indexReturnPct: 8
};

test('one completed run exposes all requested metrics', () => {
  const byLabel = Object.fromEntries(metricItems(session).map(item => [item.label, item]));
  const expected = {
    'Return': '+12.4%',
    'Net P&L': '+$12,346',
    'Win Rate': '60.0%',
    'Profit Factor': '2.25',
    'Avg Deployed': '63.4%',
    'Peak Deployed': '92.1%',
    'Idle Time': '14.8%',
    'Trades': '10',
    'Alpha vs SPX': '+4.4%'
  };
  for (const [label, value] of Object.entries(expected)) {
    if (!byLabel[label]) throw new Error('missing ' + label);
    if (byLabel[label].value !== value) {
      throw new Error(label + ': expected ' + value + ', got ' + byLabel[label].value);
    }
  }
});

test('run metrics keep useful win/loss context', () => {
  const trades = metricItems(session).find(item => item.label === 'Trades');
  if (!trades || trades.sub !== '6W · 4L') throw new Error('missing W/L breakdown');
});

test('missing legacy metrics render as unavailable', () => {
  const byLabel = Object.fromEntries(metricItems({ tradeCount: 0 }).map(item => [item.label, item]));
  ['Return', 'Win Rate', 'Profit Factor', 'Avg Deployed'].forEach(label => {
    if (byLabel[label].value !== '—') throw new Error(label + ' should be unavailable');
  });
});

test('session expansion renders the run metric cards before leg detail', () => {
  const detailFn = extractFunction(html, '_buildSessionDetailRow');
  if (!/_renderSessionRunMetrics\(inner,\s*session\)/.test(detailFn)) {
    throw new Error('run metrics are not wired into session expansion');
  }
  if (!/sim-stats-run-metrics/.test(html)) {
    throw new Error('run metric grid styling is missing');
  }
});

test('calendar days retain the IDs of every run logged that day', () => {
  const sandbox = {};
  vm.createContext(sandbox);
  const fn = extractFunction(html, '_calcCalendarModel');
  vm.runInContext(fn + '\nthis.calcCalendarModel = _calcCalendarModel;', sandbox);
  const ts = new Date(2026, 6, 21, 9, 30).getTime();
  const model = sandbox.calcCalendarModel([
    { id: 'session-a', ts, sessionPnL: 100, symbol: 'Basket (3)', tradeCount: 2, winCount: 1, lossCount: 1 },
    { id: 'session-b', ts: ts + 1000, sessionPnL: -20, symbol: 'NVDA', tradeCount: 1, winCount: 0, lossCount: 1 }
  ]);
  if (model.days.length !== 1) throw new Error('same-day runs should share one calendar day');
  const ids = model.days[0].sessionIds || [];
  if (ids.join(',') !== 'session-a,session-b') throw new Error('calendar day lost run IDs: ' + ids.join(','));
});

test('calendar day click opens the run-stats popup', () => {
  const renderFn = extractFunction(html, '_renderCalendar');
  if (!/onDayClick\s*:\s*_openCalendarRunStats/.test(renderFn)) {
    throw new Error('calendar renderer does not open run stats');
  }
  if (!/id=["']sim-calendar-runs-modal["']/.test(html)) {
    throw new Error('calendar run-stats modal is missing');
  }
  const popupFn = extractFunction(html, '_openCalendarRunStats');
  if (!/_renderSessionRunMetrics\(/.test(popupFn)) {
    throw new Error('popup does not reuse the per-run metric cards');
  }
});

console.log(`\nPer-run stats: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
