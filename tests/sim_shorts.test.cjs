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
// 2) StopRules module (defined right before Sim.Direction)
const stopRulesBlock = extractBlockUpTo(HTML, '/* ---------- Sim.StopRules', '/* ---------- Sim.Direction');
// 3) Sim.Direction module
const directionBlock = extractBlockUpTo(HTML, '/* ---------- Sim.Direction', '/* ---------- Sim.ShortLocks');
// 4) Sim.ShortLocks module
const shortLocksBlock = extractBlockUpTo(HTML, '/* ---------- Sim.ShortLocks', '/* ---------- Sim.PortfolioValuation');
// 5) Sim.PortfolioValuation module
const valuationBlock = extractBlockUpTo(HTML, '/* ---------- Sim.PortfolioValuation', '/* ---------- Sim.UI: modals');

// Build a sandbox with a minimal window. The trail-stop logic resolves
// `window.calcEMA` at runtime, so we pre-seed a minimal implementation
// matching the in-browser one at Big_movers.html:6671. Without this, every
// _maybeTrailStops candidate returns null and trails never move — making the
// test green on a broken implementation.
const sandbox = { window: {}, console: console };
sandbox.window.calcEMA = function calcEMA(bars, p){
  if (bars.length < p) return [];
  const k = 2/(p+1);
  let e = bars.slice(0, p).reduce((s, b) => s + b.close, 0) / p;
  const out = [{ time: bars[p-1].time, value: parseFloat(e.toFixed(4)) }];
  for (let i = p; i < bars.length; i++){
    e = bars[i].close*k + e*(1-k);
    out.push({ time: bars[i].time, value: parseFloat(e.toFixed(4)) });
  }
  return out;
};
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
vm.runInContext(stopRulesBlock, sandbox, { filename: 'stopRules.js' });
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

console.log('\n=== P7 backward-compat v1 review ===');
record('createSim accepts legacy entry (no direction) → defaults long', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'V1',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 50, stop: 95 }
  });
  // Walk through bars, then close: result should be identical to a fresh long sim.
  Sim.advanceTo(sim, bars, 9);
  Sim.closeAt(sim, bars, bars[9].close);
  // bars[9].close = 110, entry = 100, qty = 50, realized = 50 * (110 - 100) = 500
  if (!approxEq(sim.realizedPnL, 500)) throw new Error('legacy P&L = ' + sim.realizedPnL);
});

record('continueSim archives legs with direction', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'V2',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 100, stop: 98 }
  });
  Sim.advanceTo(sim, bars, 4); // stop at bar 3
  Sim.continueSim(sim);
  if (!sim.legs || sim.legs.length !== 1) throw new Error('legs not archived');
  if (sim.legs[0].direction !== 'long') throw new Error('archived leg direction missing: ' + sim.legs[0].direction);
  if (!sim.legs[0].legId) throw new Error('archived leg legId missing');
});

console.log('\n=== P2 StopRules direction-aware ===');
const StopRules = Sim.StopRules;
record('pctOffset: long shrinks, short grows', () => {
  const long = StopRules.pctOffset('long', 100, 5);
  const short = StopRules.pctOffset('short', 100, 5);
  if (!approxEq(long, 95)) throw new Error('long pctOffset = ' + long);
  if (!approxEq(short, 105)) throw new Error('short pctOffset = ' + short);
});
record('swingOpposite: long uses min(low), short uses max(high)', () => {
  const bars = [
    { time: '2024-01-01', open: 100, high: 105, low: 95, close: 100, volume: 1 },
    { time: '2024-01-02', open: 100, high: 110, low: 90, close: 100, volume: 1 },
    { time: '2024-01-03', open: 100, high: 102, low: 98, close: 100, volume: 1 },
    // entry bar (idx=3): not included in swing window
    { time: '2024-01-04', open: 100, high: 100, low: 100, close: 100, volume: 1 }
  ];
  // Long swing window 3 bars before idx=3 → min low = 90, minus 0.05 = 89.95
  const long = StopRules.swingOpposite('long', bars, 3, 3, 0.05);
  if (!approxEq(long, 89.95)) throw new Error('long swing = ' + long);
  // Short swing → max high = 110, plus 0.05 = 110.05
  const short = StopRules.swingOpposite('short', bars, 3, 3, 0.05);
  if (!approxEq(short, 110.05)) throw new Error('short swing = ' + short);
});
record('atrOffset: long subtracts, short adds', () => {
  const bars = [];
  for (let i = 0; i < 20; i++){
    bars.push({ time: '2024-01-' + String(i+1).padStart(2,'0'), open: 100, high: 105, low: 95, close: 100, volume: 1 });
  }
  // Without window.calcATR, falls through to simple-mean ATR. TR ~10 each bar.
  const long = StopRules.atrOffset('long', 100, bars, 19, 1.5, 14);
  const short = StopRules.atrOffset('short', 100, bars, 19, 1.5, 14);
  // Whatever atrAt returns, long should be < 100 < short.
  if (!(isFinite(long) && long < 100)) throw new Error('long atrOffset not less than entry: ' + long);
  if (!(isFinite(short) && short > 100)) throw new Error('short atrOffset not greater than entry: ' + short);
  // Symmetry: |long - 100| ≈ |short - 100|
  if (!approxEq(Math.abs(long - 100), Math.abs(short - 100), 0.02)) throw new Error('asymmetric: ' + long + ' / ' + short);
});

console.log('\n=== Bugfix regression tests (post-P8) ===');

record('EMA trail (long): stop ratchets UP as price rises', () => {
  // Strictly rising bars so the EMA also rises.
  const closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112];
  const bars = closes.map((c, i) => {
    const baseDate = new Date('2024-01-02');
    const dt = new Date(baseDate); dt.setUTCDate(dt.getUTCDate() + i);
    return { time: dt.toISOString().slice(0,10), open: c-0.5, high: c+0.5, low: c-1, close: c, volume: 1000000 };
  });
  const sim = Sim.createSim({
    moveKey: 'TRAIL_LONG',
    direction: 'long',
    entry: {
      barIdx: 5, date: bars[5].time, price: 105,
      sizeMode: 'shares', sizeValue: 100, stop: 100,
      stopTrail: { type: 'ema', period: 5, k: 0 }
    }
  });
  if (!sim.stopLevels[0].trail) throw new Error('initial stop missing trail spec');
  const initialStop = sim.stopLevels[0].price;
  Sim.advanceTo(sim, bars, 12); // walk 7 bars forward
  const finalStop = sim.stopLevels[0].price;
  if (!(finalStop > initialStop + 0.5)) {
    throw new Error('long trail did not move up enough: ' + initialStop + ' → ' + finalStop);
  }
});

record('EMA trail (short): stop ratchets DOWN as price falls', () => {
  // Strictly falling bars so the EMA also falls.
  const closes = [120, 119, 118, 117, 116, 115, 114, 113, 112, 111, 110, 109, 108];
  const bars = closes.map((c, i) => {
    const baseDate = new Date('2024-01-02');
    const dt = new Date(baseDate); dt.setUTCDate(dt.getUTCDate() + i);
    return { time: dt.toISOString().slice(0,10), open: c+0.5, high: c+1, low: c-0.5, close: c, volume: 1000000 };
  });
  const sim = Sim.createSim({
    moveKey: 'TRAIL_SHORT',
    direction: 'short',
    entry: {
      barIdx: 5, date: bars[5].time, price: 115,
      sizeMode: 'shares', sizeValue: 100, stop: 120,
      stopTrail: { type: 'ema', period: 5, k: 0 }
    }
  });
  if (!sim.stopLevels[0].trail) throw new Error('initial stop missing trail spec');
  const initialStop = sim.stopLevels[0].price;
  Sim.advanceTo(sim, bars, 12);
  const finalStop = sim.stopLevels[0].price;
  if (!(finalStop < initialStop - 0.5)) {
    throw new Error('short trail did not move down enough: ' + initialStop + ' → ' + finalStop);
  }
});

record('startNewLeg propagates stopTrail (covers new-leg modal regression)', () => {
  const bars = buildBars();
  const sim = Sim.createSim({
    moveKey: 'NEWLEG_TRAIL',
    entry: { barIdx: 0, date: bars[0].time, price: 100, sizeMode: 'shares', sizeValue: 100, stop: 98 }
  });
  Sim.advanceTo(sim, bars, 4); // stop fires bar 3
  Sim.continueSim(sim);
  Sim.startNewLeg(sim, {
    barIdx: 5, date: bars[5].time,
    price: bars[5].close, stop: bars[5].close - 5,
    sizeMode: 'shares', sizeValue: 100,
    direction: 'long',
    stopTrail: { type: 'ema', period: 5, k: 0 }
  });
  if (!sim.stopLevels[0].trail) throw new Error('new-leg stop trail not set');
  if (sim.stopLevels[0].trail.type !== 'ema') throw new Error('trail type wrong: ' + sim.stopLevels[0].trail.type);
  if (sim.stopLevels[0].trail.period !== 5) throw new Error('trail period wrong: ' + sim.stopLevels[0].trail.period);
});

record('Short full-close math: cash gets realized only, NOT cover cost', () => {
  // Simulate the PortSim cash bookkeeping. Open 100sh short at $100 on $100k
  // initial cash; cover at $90. Cash should rise by $1000 (the realized P&L),
  // NOT by $9000 (the cover cost). The original bug routed all closes through
  // creditManualClose which treats every close as a long-style sale.
  const locks = {};
  const cashBefore = 100000;
  ShortLocks.applyOpen(locks, 'leg1', 100, 100);
  // applyOpen: cash UNCHANGED, lock.proceeds = $10k.
  if (!approxEq(locks.leg1.proceeds, 10000)) throw new Error('proceeds = ' + locks.leg1.proceeds);
  // Full close at $90:
  const r = ShortLocks.applyClose(locks, 'leg1', 90);
  if (!approxEq(r.realized, 1000)) throw new Error('realized = ' + r.realized + ', expected +1000');
  if (!approxEq(r.releaseCash, 1000)) throw new Error('releaseCash should equal realized');
  // After full close, lock removed.
  if (locks.leg1) throw new Error('lock not removed after full close');
  // Cash math the wrapper performs: cashBefore + r.realized = 101000.
  // (The buggy path would have done cashBefore + 100*90 = 109000.)
  const cashAfter = cashBefore + r.realized;
  if (!approxEq(cashAfter, 101000)) throw new Error('cashAfter = ' + cashAfter);
});

record('Short partial cover: proceeds release proportionally', () => {
  const locks = {};
  ShortLocks.applyOpen(locks, 'leg1', 100, 100);
  const r1 = ShortLocks.applyCover(locks, 'leg1', 50, 90);
  // 50/100 of proceeds = $5000 released; cover cost = 50*90 = $4500; realized = +$500.
  if (!approxEq(r1.realized, 500)) throw new Error('partial realized = ' + r1.realized);
  // Lock should still hold the other half.
  if (!locks.leg1) throw new Error('lock dropped prematurely');
  if (!approxEq(locks.leg1.shares, 50)) throw new Error('lock shares = ' + locks.leg1.shares);
  if (!approxEq(locks.leg1.proceeds, 5000)) throw new Error('lock proceeds = ' + locks.leg1.proceeds);
  // Now close the rest at $80 → +$1000 more realized.
  const r2 = ShortLocks.applyClose(locks, 'leg1', 80);
  if (!approxEq(r2.realized, 1000)) throw new Error('final realized = ' + r2.realized);
  if (locks.leg1) throw new Error('lock not removed after final close');
});

console.log('\n=== Total: ' + pass + ' passed, ' + fail + ' failed ===');
process.exit(fail === 0 ? 0 : 1);
