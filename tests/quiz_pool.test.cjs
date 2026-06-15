// Node-runnable unit test for Quiz.Pool (candidate scanning).
// Run: node tests/quiz_pool.test.cjs   (exit 0 = pass, 1 = fail)
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HTML = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');

function extractBlockIncl(src, startMarker, endMarker){
  const i = src.indexOf(startMarker);
  if (i < 0) throw new Error('startMarker not found: ' + startMarker);
  const j = src.indexOf(endMarker, i);
  if (j < 0) throw new Error('endMarker not found after ' + startMarker);
  return src.slice(i, j + endMarker.length);
}

// Quiz module spans from the CONFIG marker through the Pool export marker.
const block = extractBlockIncl(
  HTML,
  '/* ===== Quiz.CONFIG + Quiz.Pool ===== */',
  '/* ===== end Quiz.Pool ===== */'
);

const sandbox = { window: {}, console: console };
vm.runInNewContext(block, sandbox);
const Quiz = sandbox.window.Quiz;

let pass = 0, fail = 0;
function ok(name, cond){ if (cond){ pass++; } else { fail++; console.error('FAIL:', name); } }

// Build a synthetic series: 130 flat bars (context) then a 40-bar steady +50% ramp,
// then 30 flat bars (forward room). Decision bars inside the ramp tail should qualify 'up'.
function makeBars(){
  const bars = [];
  let d = new Date(Date.UTC(2010, 0, 1));
  const push = (px) => {
    const t = d.toISOString().slice(0,10);
    bars.push({ time: t, open: px, high: px*1.01, low: px*0.99, close: px });
    d.setUTCDate(d.getUTCDate()+1);
  };
  for (let i=0;i<130;i++) push(10);            // flat context at $10
  for (let i=1;i<=40;i++) push(10 * (1 + 0.5*(i/40))); // ramp 10 -> 15 (+50%)
  for (let i=0;i<30;i++) push(15);             // flat forward room
  return bars;
}

const bars = makeBars();
const cfg = Quiz.CONFIG;
const cands = Quiz.Pool.scan(bars, cfg);

ok('returns an array', Array.isArray(cands));
ok('finds at least one candidate', cands.length > 0);
ok('candidate direction is up', cands.every(c => c.direction === 'up'));
ok('decisionIdx has >= MIN_CONTEXT_BARS behind', cands.every(c => c.decisionIdx >= cfg.MIN_CONTEXT_BARS));
ok('decisionIdx has >= LOOKFORWARD_H ahead', cands.every(c => c.decisionIdx <= bars.length-1-cfg.LOOKFORWARD_H));
ok('priorRunPct >= RUN_THRESHOLD', cands.every(c => c.priorRunPct >= cfg.RUN_THRESHOLD));

// A series that never moves >5% should yield zero candidates.
const flat = [];
{ let d = new Date(Date.UTC(2010,0,1));
  for (let i=0;i<220;i++){ const t=d.toISOString().slice(0,10); flat.push({time:t,open:10,high:10.1,low:9.9,close:10}); d.setUTCDate(d.getUTCDate()+1);} }
ok('flat series yields no candidates', Quiz.Pool.scan(flat, cfg).length === 0);

// Penny stock (below MIN_PRICE) should be filtered out even with a big % run.
const penny = makeBars().map(b => ({...b, open:b.open*0.05, high:b.high*0.05, low:b.low*0.05, close:b.close*0.05}));
ok('sub-$1 series filtered by MIN_PRICE', Quiz.Pool.scan(penny, cfg).length === 0);

// pick() with rng=0 returns the first candidate; rng->~1 returns the last.
const allCands = Quiz.Pool.scan(bars, cfg);
const firstPick = Quiz.Pool.pick(bars, cfg, () => 0);
const lastPick  = Quiz.Pool.pick(bars, cfg, () => 0.999999);
ok('pick(rng=0) == first candidate', firstPick && firstPick.decisionIdx === allCands[0].decisionIdx);
ok('pick(rng~1) == last candidate', lastPick && lastPick.decisionIdx === allCands[allCands.length-1].decisionIdx);
ok('pick on flat series returns null', Quiz.Pool.pick(flat, cfg, () => 0) === null);

console.log(`\nQuiz.Pool: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
