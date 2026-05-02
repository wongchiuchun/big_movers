// Node-runnable smoke test for the Sim core direction-aware modules.
//
// Strategy: extract three IIFEs (Sim const block, Sim.Direction, Sim.ShortLocks,
// Sim.PortfolioValuation, Sim.StopRules) from Big_movers.html and eval them
// inside a tiny `window` shim, then exercise the merge-gate assertions.
//
// Run: node tests/sim_shorts.test.js
// Exit 0 = all pass, 1 = any fail.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HTML = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');

// Extract from startMarker (inclusive) up to nextMarker (exclusive).
function extractBlockUpTo(src, startMarker, nextMarker){
  const i = src.indexOf(startMarker);
  if (i < 0) throw new Error('startMarker not found: ' + startMarker);
  const j = src.indexOf(nextMarker, i + startMarker.length);
  if (j < 0) throw new Error('nextMarker not found after ' + startMarker);
  return src.slice(i, j);
}
// Extract from startMarker (inclusive) up to endMarker (inclusive).
function extractBlockIncl(src, startMarker, endMarker){
  const i = src.indexOf(startMarker);
  if (i < 0) throw new Error('startMarker not found: ' + startMarker);
  const j = src.indexOf(endMarker, i);
  if (j < 0) throw new Error('endMarker not found after ' + startMarker);
  return src.slice(i, j + endMarker.length);
}

// 1) Sim core: from `const Sim = (function(){` through `window.Sim = Sim;`
const simCore = extractBlockIncl(HTML, 'const Sim = (function(){', 'window.Sim = Sim;');
// 2) Sim.Direction module — up to next /* ---------- block
const directionBlock = extractBlockUpTo(HTML, '/* ---------- Sim.Direction', '/* ---------- Sim.ShortLocks');
// 3) Sim.ShortLocks module
const shortLocksBlock = extractBlockUpTo(HTML, '/* ---------- Sim.ShortLocks', '/* ---------- Sim.PortfolioValuation');
// 4) Sim.PortfolioValuation module
const valuationBlock = extractBlockUpTo(HTML, '/* ---------- Sim.PortfolioValuation', '/* ---------- Sim.UI: modals');

// Build a sandbox with a minimal window
const sandbox = { window: {}, console: console };
sandbox.global = sandbox;
vm.createContext(sandbox);

// Exec in order: core first, then sub-modules attach to window.Sim
try {
  vm.runInContext(simCore, sandbox, { filename: 'simCore.js' });
} catch (e){
  console.error('FATAL: simCore eval failed:', e && e.message);
  process.exit(1);
}
// At this point, sandbox.Sim = the closure. We must alias sandbox.Sim → window.Sim
sandbox.Sim = sandbox.window.Sim;
vm.runInContext(directionBlock, sandbox, { filename: 'direction.js' });
vm.runInContext(shortLocksBlock, sandbox, { filename: 'shortLocks.js' });
vm.runInContext(valuationBlock, sandbox, { filename: 'valuation.js' });

const Sim = sandbox.window.Sim;
const Direction = Sim.Direction;
const ShortLocks = Sim.ShortLocks;
if (!Sim || !Direction || !ShortLocks || !Sim.PortfolioValuation){
  console.error('FATAL: modules not attached. keys:', Object.keys(Sim || {}));
  process.exit(1);
}

let pass = 0, fail = 0;
function approxEq(a, b, eps){ return Math.abs(a - b) <= (eps || 0.01); }
function record(name, fn){
  try {
    fn();
    pass++;
    console.log('  PASS  ' + name);
  } catch (e){
    fail++;
    console.log('  FAIL  ' + name + '  -> ' + (e && e.message ? e.message : e));
  }
}

function buildBars(){
  const baseDate = new Date('2024-01-02');
  function addDays(d, n){ const dt = new Date(d); dt.setUTCDate(dt.getUTCDate()+n); return dt.toISOString().slice(0,10); }
  const closes = [100, 102, 101, 99, 100, 103, 105, 104, 106, 110];
  return closes.map((c, i) => {
    const prev = i === 0 ? c : closes[i-1];
    let open = prev;
    let high = Math.max(open, c) + 1;
    let low  = Math.min(open, c) - 1;
    if (i === 3){ open = 99;  high = 100; low = 97;  }
    if (i === 5){ open = 104; high = 106; low = 102; }
    return { time: addDays(baseDate, i), open, high, low, close: c, volume: 1000000 };
  });
}
function mirrorBars(bars, center){
  return bars.map(b => ({
    time: b.time,
    open:  2*center - b.open,
    high:  2*center - b.low,
    low:   2*center - b.high,
    close: 2*center - b.close,
    volume: b.volume
  }));
}

// ---- P0 module presence ----
console.log('=== P0 modules ===');
record('Sim.Direction adapter exposed', () => {
  if (Direction.sign('long') !== 1)  throw new Error('long sign');
  if (Direction.sign('short') !== -1) throw new Error('short sign');
});
record('Sim.ShortLocks adapter exposed', () => {
  if (typeof ShortLocks.applyOpen !== 'function') throw new Error('applyOpen');
});
record('Sim.PortfolioValuation adapter exposed', () => {
  if (typeof Sim.PortfolioValuation.computeEquity !== 'function') throw new Error('computeEquity');
});

// ---- P1 sim core direction ----
console.log('\n=== P1 sim core direction ===');
record('Short initial risk = shares * (stop - entry)', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'TEST', direction: 'short',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 100, stop: 102 }
  });
  if (!approxEq(sim.initialRisk, 200)) throw new Error('expected 200, got ' + sim.initialRisk);
  if (!sim.legId) throw new Error('legId not minted');
  if (sim.direction !== 'short') throw new Error('direction not stored');
});

record('Short stop fires on gap-up: fill = max(open, stop)', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'TEST', direction: 'short',
    entry: { barIdx: 4, date: bars[4].time, price: 100, sizeMode: 'shares', sizeValue: 100, stop: 103.5 }
  });
  const r = Sim.advanceTo(sim, bars, 5);
  const stopEv = (r.eventsFired || []).find(e => e.type === 'stop');
  if (!stopEv) throw new Error('stop did not fire');
  if (!approxEq(stopEv.price, 104)) throw new Error('fill expected 104, got ' + stopEv.price);
});

record('Multi-stop partial cover ordering (short)', () => {
  const bars = [
    { time: '2024-01-01', open: 100, high: 100, low: 100, close: 100, volume: 1 },
    { time: '2024-01-02', open: 100, high: 100, low: 100, close: 100, volume: 1 },
    { time: '2024-01-03', open: 100.5, high: 104, low: 100, close: 103.5, volume: 1 }
  ];
  const sim = Sim.createSim({
    moveKey: 'TEST', direction: 'short',
    entry: { barIdx: 0, date: bars[0].time, price: 99, sizeMode: 'shares', sizeValue: 100, stop: 105 }
  });
  Sim.queueAction(sim, { type: 'movestop', newStop: 101, pct: 0.5 });
  Sim.queueAction(sim, { type: 'movestop', newStop: 103, pct: 0.5 });
  Sim.advanceTo(sim, bars, 1);
  const r = Sim.advanceTo(sim, bars, 2);
  const stopEvs = (r.eventsFired || []).filter(e => e.type === 'stop');
  if (stopEvs.length < 1) throw new Error('no stop events');
  if (!approxEq(stopEvs[0].price, 101)) throw new Error('first stop fill expected 101, got ' + stopEvs[0].price);
});

record('Short manual close P&L = (avg - fill) * qty', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'TEST', direction: 'short',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 100, stop: 105 }
  });
  Sim.advanceTo(sim, bars, 2);
  Sim.closeAt(sim, bars, 90);
  if (!approxEq(sim.realizedPnL, 1000)) throw new Error('expected 1000, got ' + sim.realizedPnL);
});

record('Short end-bar force close uses cover semantics', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'TEST', direction: 'short',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 100, stop: 110, endBarIdx: 5 }
  });
  Sim.advanceTo(sim, bars, 5);
  if (!sim.closed) throw new Error('not closed');
  if (!approxEq(sim.realizedPnL, -300)) throw new Error('expected -300, got ' + sim.realizedPnL);
});

record('Long-on-mirrored == Short-on-original (absolute distance)', () => {
  const bars = buildBars();
  const center = 100;
  const mirrored = mirrorBars(bars, center);
  const simShort = Sim.createSim({
    moveKey: 'A', direction: 'short',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 50, stop: 102 }
  });
  Sim.advanceTo(simShort, bars, 2);
  Sim.closeAt(simShort, bars, bars[2].close);
  const simLong = Sim.createSim({
    moveKey: 'A', direction: 'long',
    entry: { barIdx: 0, date: mirrored[0].time, price: 100, sizeMode: 'shares', sizeValue: 50, stop: 98 }
  });
  Sim.advanceTo(simLong, mirrored, 2);
  Sim.closeAt(simLong, mirrored, mirrored[2].close);
  if (!approxEq(simShort.realizedPnL, simLong.realizedPnL, 0.05))
    throw new Error('short=' + simShort.realizedPnL + ' vs long-mirror=' + simLong.realizedPnL);
});

// ---- P6 ----
console.log('\n=== P6 ShortLocks + equity ===');
record('Step-back undo restores shortLocks deep-cloned', () => {
  const locks = {};
  ShortLocks.applyOpen(locks, 'leg_1', 100, 50);
  const snap = JSON.parse(JSON.stringify(locks));
  ShortLocks.applyCover(locks, 'leg_1', 50, 45);
  if (locks.leg_1.shares !== 50) throw new Error('cover did not reduce shares');
  const restored = JSON.parse(JSON.stringify(snap));
  if (restored.leg_1.shares !== 100) throw new Error('snap did not preserve original shares');
  if (restored.leg_1.proceeds !== 5000) throw new Error('snap did not preserve proceeds');
  ShortLocks.applyCover(locks, 'leg_1', 50, 40);
  if (snap.leg_1.shares !== 100) throw new Error('snap aliased live locks');
});

record('ShortLocks.applyOpen + applyCover P&L round-trip', () => {
  const locks = {};
  ShortLocks.applyOpen(locks, 'lg_x', 100, 100);
  if (!approxEq(locks.lg_x.proceeds, 10000)) throw new Error('open proceeds wrong');
  const r = ShortLocks.applyCover(locks, 'lg_x', 50, 90);
  if (!approxEq(r.realized, 500)) throw new Error('cover realized ' + r.realized + ', want 500');
  if (locks.lg_x.shares !== 50) throw new Error('cover shares wrong');
  if (!approxEq(locks.lg_x.proceeds, 5000)) throw new Error('cover proceeds wrong');
});

record('Equity-equivalence: $100k + 1L + 1S marks correctly at open & rally', () => {
  const state = { cash: 100000, shortLocks: {} };
  state.cash -= 50;
  ShortLocks.applyOpen(state.shortLocks, 'lg_s', 1, 50);
  const basket = [
    { sim: { qty: 1, direction: 'long',  avgCost: 50 }, lastCloseSeen: 50 },
    { sim: { qty: 1, direction: 'short', avgCost: 50 }, lastCloseSeen: 50 }
  ];
  const eq1 = Sim.PortfolioValuation.computeEquity(state, basket);
  if (!approxEq(eq1, 100000)) throw new Error('eq@open = ' + eq1);
  basket[0].lastCloseSeen = 60; basket[1].lastCloseSeen = 60;
  const eq2 = Sim.PortfolioValuation.computeEquity(state, basket);
  if (!approxEq(eq2, 100000)) throw new Error('eq@60 = ' + eq2);
});

// ---- P7 backward-compat ----
console.log('\n=== P7 backward-compat ===');
record('createSim defaults missing direction to long', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'OLD',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 100, stop: 98 }
  });
  if (sim.direction !== 'long') throw new Error('default not long');
  if (!approxEq(sim.initialRisk, 200)) throw new Error('legacy long initialRisk wrong');
});

record('Long sim (legacy path) realizedPnL = -200 stops at bar 3', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'OLD',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 100, stop: 98 }
  });
  Sim.advanceTo(sim, bars, 4);
  if (!sim.stoppedOut) throw new Error('not stopped');
  if (!approxEq(sim.realizedPnL, -200)) throw new Error('expected -200, got ' + sim.realizedPnL);
});

console.log('\n=== Direction adapter unit checks ===');
record('Direction.stopFires', () => {
  const bar = { open: 100, high: 102, low: 98, close: 100 };
  if (Direction.stopFires('long', bar, 99) !== true) throw new Error('long@99');
  if (Direction.stopFires('long', bar, 97) !== false) throw new Error('long@97');
  if (Direction.stopFires('short', bar, 101) !== true) throw new Error('short@101');
  if (Direction.stopFires('short', bar, 103) !== false) throw new Error('short@103');
});
record('Direction.fillAtStop', () => {
  const bar = { open: 99, high: 102, low: 97, close: 100 };
  if (Direction.fillAtStop('long', bar, 98) !== 98) throw new Error('long fill');
  const bar2 = { open: 104, high: 106, low: 102, close: 105 };
  if (Direction.fillAtStop('short', bar2, 103.5) !== 104) throw new Error('short fill');
});
record('Direction.ratchet', () => {
  if (Direction.ratchet('long', 100, 102) !== 102) throw new Error('long up');
  if (Direction.ratchet('long', 100, 98) !== 100) throw new Error('long reject');
  if (Direction.ratchet('short', 100, 98) !== 98) throw new Error('short down');
  if (Direction.ratchet('short', 100, 102) !== 100) throw new Error('short reject');
});
record('Direction.sortStopsForFire', () => {
  const stops = [{price:100},{price:95},{price:105}];
  const sl = Direction.sortStopsForFire('long', stops).map(s=>s.price);
  if (sl[0] !== 105) throw new Error('long sort');
  const ss = Direction.sortStopsForFire('short', stops).map(s=>s.price);
  if (ss[0] !== 95) throw new Error('short sort');
});
record('Direction.stopValidates', () => {
  if (Direction.stopValidates('long', 100, 98) !== true) throw new Error('long ok');
  if (Direction.stopValidates('long', 100, 102) !== false) throw new Error('long bad');
  if (Direction.stopValidates('short', 100, 102) !== true) throw new Error('short ok');
  if (Direction.stopValidates('short', 100, 98) !== false) throw new Error('short bad');
});

console.log('\n=== Total: ' + pass + ' passed, ' + fail + ' failed ===');
process.exit(fail === 0 ? 0 : 1);
