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

function extractLastFunction(source, name) {
  const start = source.lastIndexOf('function ' + name + '(');
  if (start < 0) throw new Error('Function not found: ' + name);
  return extractFunction(source.slice(start), name);
}

function loadFunctions(names, extras = {}) {
  const sandbox = { ...extras };
  vm.createContext(sandbox);
  const source = names.map(name => extractFunction(html, name)).join('\n')
    + '\n' + names.map(name => `this.${name} = ${name};`).join('\n');
  vm.runInContext(source, sandbox);
  return sandbox;
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('Stats trade records retain every partial-exit event', () => {
  const { _extractTradesFromSim } = loadFunctions(['_extractTradesFromSim']);
  const eventsLog = [
    {
      barIdx: 1, date: '2025-01-03', type: 'entry', qty: 100, price: 100,
      direction: 'long', legId: 'leg-1', note: 'entry'
    },
    {
      barIdx: 2, date: '2025-01-06', type: 'sell', qty: 25, price: 120,
      direction: 'long', legId: 'leg-1', note: 'partial'
    },
    {
      barIdx: 3, date: '2025-01-07', type: 'close', qty: 75, price: 130,
      direction: 'long', legId: 'leg-1', note: 'final'
    }
  ];
  const sim = {
    between: true,
    legs: [{
      direction: 'long',
      legId: 'leg-1',
      entry: { barIdx: 1, date: '2025-01-03', price: 100, stop: 95 },
      shares0: 100,
      initialRisk: 500,
      realizedPnL: 2750,
      rMultiple: 5.5,
      mfe: 3000,
      mae: -200,
      exitBarIdx: 3,
      exitReason: 'close',
      eventsLog
    }]
  };
  const bars = [
    { time: '2025-01-02', close: 98 },
    { time: '2025-01-03', close: 100 },
    { time: '2025-01-06', close: 120 },
    { time: '2025-01-07', close: 130 }
  ];

  const trades = _extractTradesFromSim(sim, bars, { symbol: 'TEST' });

  assert.equal(trades.length, 1);
  assert.ok(Array.isArray(trades[0].eventsLog), 'trade record is missing eventsLog');
  assert.deepEqual(plain(trades[0].eventsLog), eventsLog);
});

test('session review reconstruction uses the persisted execution log', () => {
  const { _synthMetaFromSession } = loadFunctions(['_synthMetaFromSession']);
  const eventsLog = [
    {
      type: 'sell', date: '2025-01-06', qty: 25, price: 120,
      direction: 'long', legId: 'leg-1'
    },
    {
      type: 'close', date: '2025-01-07', qty: 75, price: 130,
      direction: 'long', legId: 'leg-1'
    }
  ];
  const session = {
    initialEquity: 100000,
    finalEquity: 102750,
    sessionPnL: 2750,
    simStartDate: '2025-01-02',
    simEndDate: '2025-01-07',
    indexName: 'SPX'
  };
  const trades = [{
    symbol: 'TEST',
    legIndex: 1,
    direction: 'long',
    legId: 'leg-1',
    entryDate: '2025-01-03',
    entryPrice: 100,
    qty: 100,
    stopAtEntry: 95,
    initialRisk: 500,
    exitDate: '2025-01-07',
    exitPrice: 130,
    exitReason: 'close',
    realizedPnL: 2750,
    rMultiple: 5.5,
    eventsLog
  }];

  const meta = _synthMetaFromSession(session, trades);

  assert.deepEqual(plain(meta.basket[0].legs[0].eventsLog), eventsLog);
});

test('legacy Stats trades still synthesize a final-exit marker', () => {
  const { _synthMetaFromSession } = loadFunctions(['_synthMetaFromSession']);
  const meta = _synthMetaFromSession(
    {
      initialEquity: 100000,
      finalEquity: 100500,
      sessionPnL: 500,
      simStartDate: '2025-01-02',
      simEndDate: '2025-01-07'
    },
    [{
      symbol: 'OLD',
      legIndex: 1,
      entryDate: '2025-01-03',
      entryPrice: 100,
      qty: 100,
      exitDate: '2025-01-07',
      exitPrice: 105,
      exitReason: 'close',
      realizedPnL: 500
    }]
  );

  assert.deepEqual(plain(meta.basket[0].legs[0].eventsLog), [
    { type: 'close', date: '2025-01-07', price: 105, qty: 100 }
  ]);
});

test('partial short exits are labeled as covers in chart review', () => {
  const { _markersFromLegs } = loadFunctions(
    ['_markersFromLegs'],
    { _r2: value => Math.round((Number(value) || 0) * 100) / 100 }
  );
  const markers = _markersFromLegs([{
    idx: 1,
    direction: 'short',
    entryDate: '2025-01-03',
    entryPrice: 100,
    shares: 100,
    eventsLog: [{
      type: 'sell',
      date: '2025-01-06',
      qty: 25,
      price: 90,
      direction: 'short',
      legId: 'short-1'
    }]
  }]);

  assert.equal(markers.find(marker => marker.time === '2025-01-06').text, 'COVER 25@90');
});

test('shared portfolio metrics match the Stats dashboard definitions', () => {
  assert.match(html, /function _computePortfolioMetrics\(/, 'shared metric calculator is missing');
  const functions = loadFunctions(
    ['_extractTradesFromSim', '_deployedPortfolio', '_aggSession', '_computePortfolioMetrics'],
    {
      window: {
        PortSim: {
          Positions: {
            curve() {
              return [
                { equity: 100, cash: 75, openCount: 1 },
                { equity: 100, cash: 50, openCount: 1 },
                { equity: 100, cash: 25, openCount: 1 }
              ];
            }
          }
        }
      }
    }
  );
  const bars = [
    { time: '2025-01-02', close: 100 },
    { time: '2025-01-03', close: 110 }
  ];
  function closedSim(realizedPnL, legId) {
    return {
      between: true,
      legs: [{
        direction: 'long',
        legId,
        entry: { barIdx: 0, date: '2025-01-02', price: 100, stop: 95 },
        shares0: 10,
        initialRisk: 50,
        realizedPnL,
        rMultiple: realizedPnL / 50,
        mfe: Math.max(0, realizedPnL),
        mae: Math.min(0, realizedPnL),
        exitBarIdx: 1,
        exitReason: 'close',
        eventsLog: [{
          barIdx: 1,
          date: '2025-01-03',
          type: 'close',
          qty: 10,
          price: realizedPnL > 0 ? 110 : 95,
          direction: 'long',
          legId
        }]
      }]
    };
  }

  const metrics = functions._computePortfolioMetrics({
    basket: [
      { symbol: 'WIN', sim: closedSim(100, 'win-1'), bars },
      { symbol: 'LOSS', sim: closedSim(-50, 'loss-1'), bars }
    ]
  });

  assert.equal(metrics.tradeRows.length, 2);
  assert.equal(metrics.tradeCount, 2);
  assert.equal(metrics.winCount, 1);
  assert.equal(metrics.winRate, 50);
  assert.equal(metrics.avgPctDeployed, 50);
  assert.equal(metrics.peakPctDeployed, 75);
});

test('deployment keeps the Stats dashboard zero clamp for short cash accounting', () => {
  const { _deployedPortfolio } = loadFunctions(
    ['_deployedPortfolio'],
    {
      window: {
        PortSim: {
          Positions: {
            curve() {
              return [{ equity: 100, cash: 125, openCount: 1 }];
            }
          }
        }
      }
    }
  );

  assert.deepEqual(plain(_deployedPortfolio()), {
    avg: 0,
    peak: 0,
    idlePct: 0
  });
});

test('end summary and Stats persistence use the same portfolio metrics', () => {
  const summaryFn = extractLastFunction(html, '_showSummary');
  assert.match(summaryFn, /window\.SimStats\.computePortfolioMetrics\(/);
  assert.match(summaryFn, /Win rate/);
  assert.match(summaryFn, /Avg capital deployed/);
  assert.match(summaryFn, /Peak capital deployed/);

  const addStatsFn = extractFunction(html, 'addCurrentPortfolio');
  assert.match(addStatsFn, /_computePortfolioMetrics\(payload\)/);
});
