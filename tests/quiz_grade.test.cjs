// Node-runnable unit test for Quiz.Grade.
// Run: node tests/quiz_grade.test.cjs
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HTML = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');
function extractBlockIncl(src, s, e){
  const i = src.indexOf(s); if (i<0) throw new Error('start not found: '+s);
  const j = src.indexOf(e, i); if (j<0) throw new Error('end not found: '+e);
  return src.slice(i, j + e.length);
}
// Grade needs the CONFIG (defined in the Pool block) + the Grade block.
const poolBlock  = extractBlockIncl(HTML, '/* ===== Quiz.CONFIG + Quiz.Pool ===== */', '/* ===== end Quiz.Pool ===== */');
const gradeBlock = extractBlockIncl(HTML, '/* ===== Quiz.Grade ===== */', '/* ===== end Quiz.Grade ===== */');
const sandbox = { window: {}, console: console };
vm.runInNewContext(poolBlock + '\n' + gradeBlock, sandbox);
const Quiz = sandbox.window.Quiz;

let pass=0, fail=0;
function ok(name, cond){ if(cond){pass++;} else {fail++; console.error('FAIL:', name);} }

const cfg = Object.assign({}, Quiz.CONFIG, { LOOKFORWARD_H: 10 });

function flatBar(t, px){ return { time:t, open:px, high:px, low:px, close:px }; }
function series(prices){
  let d = new Date(Date.UTC(2010,0,1));
  return prices.map(px => { const t=d.toISOString().slice(0,10); d.setUTCDate(d.getUTCDate()+1); return flatBar(t, px); });
}

// UP candidate at idx where priorRun = 100->150 (+50% => priorRun magnitude 50 in $).
// Case A: forward extreme barely moves (151) => remaining ~0 => bucket 0 ("it's over").
{
  const prices = [];
  for (let i=0;i<5;i++) prices.push(100);
  prices.push(150);                 // decision bar (idx 5), close 150, prior swingLow 100
  for (let i=0;i<10;i++) prices.push(151); // forward extreme 151
  const bars = series(prices);
  const cand = { decisionIdx:5, direction:'up', swingIdx:0, swingPrice:100, decisionClose:150, priorRunPct:0.5 };
  const r = Quiz.Grade.trueBucket(bars, cand, cfg);
  ok('A remaining ~0', r.remaining < 0.05);
  ok('A bucket == 0', r.bucket === 0);
}

// Case B: forward extreme runs to 250 => futureExt 100 vs priorRun 50 => remaining = 100/150 = 0.667 => bucket 4.
{
  const prices = [];
  for (let i=0;i<5;i++) prices.push(100);
  prices.push(150);
  for (let i=1;i<=10;i++) prices.push(150 + (100*i/10)); // ramps to 250
  const bars = series(prices);
  const cand = { decisionIdx:5, direction:'up', swingIdx:0, swingPrice:100, decisionClose:150, priorRunPct:0.5 };
  const r = Quiz.Grade.trueBucket(bars, cand, cfg);
  ok('B remaining ~0.667', Math.abs(r.remaining - (100/150)) < 0.02);
  ok('B bucket == 4', r.bucket === 4);
}

// DOWN candidate: swingHigh 200, decisionClose 100 (-50%). Forward low 50 => futureExt 50, priorRun 100 => remaining 0.333 => bucket 2.
{
  const prices = [];
  for (let i=0;i<5;i++) prices.push(200);
  prices.push(100);
  for (let i=1;i<=10;i++) prices.push(100 - (50*i/10)); // ramps down to 50
  const bars = series(prices);
  const cand = { decisionIdx:5, direction:'down', swingIdx:0, swingPrice:200, decisionClose:100, priorRunPct:0.5 };
  const r = Quiz.Grade.trueBucket(bars, cand, cfg);
  ok('C down remaining ~0.333', Math.abs(r.remaining - (50/150)) < 0.02);
  ok('C down bucket == 2', r.bucket === 2);
}

// Scoring.
ok('score exact = 1.0', Quiz.Grade.score(3,3) === 1.0);
ok('score adjacent = 0.5', Quiz.Grade.score(2,3) === 0.5 && Quiz.Grade.score(4,3) === 0.5);
ok('score far = 0', Quiz.Grade.score(0,3) === 0);

console.log(`\nQuiz.Grade: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
