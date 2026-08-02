const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HTML = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');

function blockIncl(start, end) {
  const i = HTML.indexOf(start);
  const j = HTML.indexOf(end, i);
  assert.ok(i >= 0 && j >= 0, `missing block ${start}`);
  return HTML.slice(i, j + end.length);
}

function blockUpTo(start, end) {
  const i = HTML.indexOf(start);
  const j = HTML.indexOf(end, i);
  assert.ok(i >= 0 && j >= 0, `missing block ${start}`);
  return HTML.slice(i, j);
}

function loadSim() {
  const sandbox = { window: {}, console };
  sandbox.window.calcEMA = function (bars, period) {
    if (bars.length < period) return [];
    const k = 2 / (period + 1);
    let ema = bars.slice(0, period).reduce((sum, bar) => sum + bar.close, 0) / period;
    const out = [{ time: bars[period - 1].time, value: +ema.toFixed(4) }];
    for (let i = period; i < bars.length; i += 1) {
      ema = bars[i].close * k + ema * (1 - k);
      out.push({ time: bars[i].time, value: +ema.toFixed(4) });
    }
    return out;
  };
  sandbox.global = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(blockIncl('const Sim = (function(){', 'window.Sim = Sim;'), sandbox);
  sandbox.Sim = sandbox.window.Sim;
  vm.runInContext(blockUpTo('/* ---------- Sim.StopRules', '/* ---------- Sim.Direction'), sandbox);
  vm.runInContext(blockUpTo('/* ---------- Sim.Direction', '/* ---------- Sim.ShortLocks'), sandbox);
  return sandbox.window.Sim;
}

function bars(rows) {
  return rows.map((row, i) => ({
    time: `2024-01-0${i + 1}`,
    open: row[0], high: row[1], low: row[2], close: row[3], volume: 1000
  }));
}

function make(Sim, direction, stop, stopTriggerMode, stopTrail) {
  return Sim.createSim({
    direction,
    entry: {
      barIdx: 0, date: '2024-01-01', price: 100,
      sizeMode: 'shares', sizeValue: 100, stop,
      stopTriggerMode, stopTrail
    }
  });
}

test('long close-mode stop ignores intraday breach and fills at the later close', () => {
  const Sim = loadSim();
  const data = bars([[100, 102, 99, 100], [100, 101, 90, 98], [98, 99, 92, 94]]);
  const sim = make(Sim, 'long', 95, 'close');
  Sim.advanceTo(sim, data, 1);
  assert.equal(sim.qty, 100);
  Sim.advanceTo(sim, data, 2);
  assert.equal(sim.qty, 0);
  const event = sim.eventsLog.find((item) => item.type === 'stop');
  assert.equal(event.price, 94);
  assert.equal(event.triggerMode, 'close');
  assert.equal(event.stopId, 'stop_initial');
});

test('short close-mode stop ignores intraday breach and fills at the later close', () => {
  const Sim = loadSim();
  const data = bars([[100, 101, 99, 100], [100, 110, 99, 102], [102, 108, 101, 106]]);
  const sim = make(Sim, 'short', 105, 'close');
  Sim.advanceTo(sim, data, 1);
  assert.equal(sim.qty, 100);
  Sim.advanceTo(sim, data, 2);
  assert.equal(sim.qty, 0);
  assert.equal(sim.eventsLog.find((item) => item.type === 'stop').price, 106);
});

test('missing mode remains legacy intraday behavior', () => {
  const Sim = loadSim();
  const data = bars([[100, 102, 99, 100], [100, 101, 90, 98]]);
  const sim = make(Sim, 'long', 95);
  Sim.advanceTo(sim, data, 1);
  assert.equal(sim.qty, 0);
  assert.equal(sim.eventsLog.find((item) => item.type === 'stop').price, 95);
});

test('mixed partial stops evaluate their own trigger modes', () => {
  const Sim = loadSim();
  const data = bars([[100, 102, 99, 100], [100, 102, 99, 101], [101, 102, 94, 98], [98, 99, 92, 94]]);
  const sim = make(Sim, 'long', 80, 'intraday');
  Sim.queueAction(sim, { type: 'movestop', newStop: 95, pct: 0.5, triggerMode: 'intraday' });
  Sim.queueAction(sim, { type: 'movestop', newStop: 95, pct: 0.5, triggerMode: 'close' });
  Sim.advanceTo(sim, data, 1);
  assert.equal(sim.qty, 100);
  Sim.advanceTo(sim, data, 2);
  assert.equal(sim.qty, 50);
  assert.equal(sim.stopLevels.filter((stop) => stop.fired).length, 1);
  Sim.advanceTo(sim, data, 3);
  assert.equal(sim.qty, 0);
  const modes = Array.from(sim.eventsLog.filter((item) => item.type === 'stop'), (item) => item.triggerMode);
  assert.deepEqual(modes, ['intraday', 'close']);
});

test('EMA trail ratchets before a close-mode trigger on the same bar', () => {
  const Sim = loadSim();
  const data = bars([[100, 101, 99, 100], [100, 141, 99, 140], [140, 141, 79, 80]]);
  const sim = make(Sim, 'long', 90, 'close', { type: 'ema', period: 3, k: 0 });
  Sim.advanceTo(sim, data, 2);
  const trailEvent = sim.eventsLog.find((item) => item.type === 'movestop');
  const stopEvent = sim.eventsLog.find((item) => item.type === 'stop');
  assert.equal(trailEvent.newStop, 106.67);
  assert.equal(stopEvent.price, 80);
  assert.ok(sim.eventsLog.indexOf(trailEvent) < sim.eventsLog.indexOf(stopEvent));
});

test('portfolio stop workflows expose an EOD checkbox and serialize close mode', () => {
  for (const id of ['sim-setup-stop-eod', 'sim-newleg-stop-eod', 'sim-add-stop-eod', 'sim-movestop-stop-eod']) {
    assert.match(HTML, new RegExp(`id=["']${id}["']`));
  }
  assert.match(HTML, /stopTriggerMode\s*:/);
  assert.match(HTML, /triggerMode\s*:/);
  assert.match(HTML, /class=["']portsim-row-stop-eod["']/);
  assert.match(HTML, /currentStopTriggerMode/);
  assert.match(HTML, /TriggerMode/);
  assert.match(HTML, /EOD STOP/);
  assert.match(HTML, /triggerMode:\s*s\.triggerMode === 'close'/);
});
