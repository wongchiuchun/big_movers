// Node-runnable unit test for Quiz.Stats.
// Run: node tests/quiz_stats.test.cjs
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const HTML = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');
function extractBlockIncl(src, s, e){
  const i = src.indexOf(s); if (i<0) throw new Error('start not found: '+s);
  const j = src.indexOf(e, i); if (j<0) throw new Error('end not found: '+e);
  return src.slice(i, j + e.length);
}
const block = extractBlockIncl(HTML, '/* ===== Quiz.Stats ===== */', '/* ===== end Quiz.Stats ===== */');
// Provide a localStorage shim so the module loads in Node.
const store = {};
const sandbox = { window: { localStorage: {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k,v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; }
}}, console: console };
vm.runInNewContext(block, sandbox);
const Quiz = sandbox.window.Quiz;

let pass=0, fail=0;
function ok(name, cond){ if(cond){pass++;} else {fail++; console.error('FAIL:', name);} }

// 5 rounds. User always predicts 0 ("it's over"). True buckets: [4,4,3,4,2].
// User exact matches: 0/5. within1 (|pred-true|<=1): 0/5.
// Baseline "always 4": exact = matches where true==4 => 3/5. within1 => true>=3 => 4/5.
const rounds = [
  { symbol:'A', decisionDate:'2010-01-01', direction:'up', predictedBucket:0, trueBucket:4, credit:0 },
  { symbol:'B', decisionDate:'2010-01-02', direction:'up', predictedBucket:0, trueBucket:4, credit:0 },
  { symbol:'C', decisionDate:'2010-01-03', direction:'up', predictedBucket:0, trueBucket:3, credit:0 },
  { symbol:'D', decisionDate:'2010-01-04', direction:'up', predictedBucket:0, trueBucket:4, credit:0 },
  { symbol:'E', decisionDate:'2010-01-05', direction:'up', predictedBucket:0, trueBucket:2, credit:0 },
];
const s = Quiz.Stats.summarize(rounds);
ok('user exactRate 0', Math.abs(s.exactRate - 0) < 1e-9);
ok('user within1Rate 0', Math.abs(s.within1Rate - 0) < 1e-9);
ok('baseline always-continue exactRate 3/5', Math.abs(s.baselineAlwaysContinueExact - 0.6) < 1e-9);
ok('baseline always-continue within1 4/5', Math.abs(s.baselineAlwaysContinueWithin1 - 0.8) < 1e-9);
ok('baseline random exactRate 0.2', Math.abs(s.baselineRandomExact - 0.2) < 1e-9);
ok('bias line mentions over-calling tops', /top|over|0/i.test(s.biasLine));
ok('roundCount = 5', s.roundCount === 5);

// Persistence round-trips a session.
Quiz.Stats.saveSession({ ts: 123, rounds: rounds, summary: s });
const loaded = Quiz.Stats.loadSessions();
ok('loadSessions returns the saved one', loaded.length === 1 && loaded[0].ts === 123);

console.log(`\nQuiz.Stats: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
