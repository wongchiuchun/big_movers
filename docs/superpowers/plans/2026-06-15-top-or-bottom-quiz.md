# Top-or-Bottom Quiz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a quiz mode inside `Big_movers.html` that shows an extended price move cut at a "decision bar," asks the user how much of the move is left (5-way), reveals the outcome, scores it, and after a session shows the user's accuracy is no better than dumb baselines.

**Architecture:** Three pure, Node-testable modules (`Quiz.Pool` candidate scanning, `Quiz.Grade` outcome bucketing/scoring, `Quiz.Stats` session aggregation + baselines) authored as marker-delimited IIFE blocks attached to `window.Quiz`, plus a thin DOM/chart integration layer (`Quiz.Ctrl` + `Quiz.UI`). A tiny `/api/stock-list` Flask endpoint exposes the full ~984-ticker universe so sampling is unbiased. The chart is masked by only feeding bars `[start..decisionIdx]` to the existing `candleSeries`, then re-feeding `[start..decisionIdx+H]` on reveal — fully decoupled from the trade-sim engine.

**Tech Stack:** Vanilla JS (single-file webapp), Lightweight Charts, Flask (`Big_movers_server.py`), Node `vm`-based test harness (no package.json; `node tests/*.cjs`).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `Big_movers_server.py` | Add `/api/stock-list` returning ticker filenames | Modify |
| `Big_movers.html` | Add `Quiz.*` modules (Pool/Grade/Stats/Ctrl/UI), quiz panel HTML, launch button | Modify |
| `tests/quiz_pool.test.cjs` | Unit tests for `Quiz.Pool` scan/pick | Create |
| `tests/quiz_grade.test.cjs` | Unit tests for `Quiz.Grade` bucketing/scoring | Create |
| `tests/quiz_stats.test.cjs` | Unit tests for `Quiz.Stats` aggregation/baselines | Create |

### Shared data shapes (used across all tasks)

```
Bar:        { time: 'YYYY-MM-DD', open: number, high: number, low: number, close: number, volume?: number }

Config:     window.Quiz.CONFIG = {
              LOOKFORWARD_H: 21, LOOKBACK_L: 63, RUN_THRESHOLD: 0.35,
              MIN_CONTEXT_BARS: 120, MIN_PRICE: 1.0,
              REMAINING_THRESHOLDS: [0.05, 0.20, 0.45, 0.65]  // 4 cut points -> 5 buckets
            }

Candidate:  { decisionIdx, direction: 'up'|'down', swingIdx, swingPrice, decisionClose, priorRunPct }

Bucket index 0..4 maps to UI answers:
  0 = "It's over"          (the extreme is in now)
  1 = "Almost over"        (one more small leg)
  2 = "Roughly halfway"
  3 = "Early"              (most of the move still ahead)
  4 = "Just getting started"

TrueResult: { remaining: number, bucket: 0..4, forwardExtremeIdx, forwardExtreme }

Round:      { symbol, decisionDate, direction, predictedBucket, trueBucket, credit }
```

---

## Task 1: Add `/api/stock-list` server endpoint

**Files:**
- Modify: `Big_movers_server.py` (add a new route near the other `/api/*` routes, e.g. after `/api/ohlcv`)

- [ ] **Step 1: Add the route**

Find the `collected_stocks` directory constant the existing `/api/ohlcv` handler uses (it iterates candidate dirs and joins `f"{symbol}.csv"`). Add this route alongside the other routes (Flask `@app.route`):

```python
@app.route("/api/stock-list")
def api_stock_list():
    """Return the list of available ticker symbols in collected_stocks/.
    Used by the Top-or-Bottom Quiz to sample the full universe (unbiased),
    not just the big-mover catalogue."""
    d = os.path.join(SCRIPT_DIR, "collected_stocks")
    out = []
    try:
        for fname in os.listdir(d):
            if fname.endswith(".csv"):
                out.append(fname[:-4].upper())
    except FileNotFoundError:
        return jsonify({"error": "collected_stocks directory not found"}), 404
    out.sort()
    return jsonify(out)
```

> Note: `SCRIPT_DIR` is already defined in the file (used by `DRAWINGS_FILE = os.path.join(SCRIPT_DIR, ...)`). Reuse it. If the `/api/ohlcv` handler uses a different directory variable for `collected_stocks`, use that same variable instead.

- [ ] **Step 2: Run the server and verify the endpoint**

Run:
```bash
cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers" && \
python3 Big_movers_server.py >/tmp/quiz_server.log 2>&1 &
sleep 2
curl -s http://localhost:8000/api/stock-list | head -c 200
```
(Use whatever port the server actually binds — check the top of `Big_movers_server.py` / `HOW_TO_RUN.md`. Replace `8000` if different.)

Expected: a JSON array starting like `["AAL","AAMRQ","AAOI",...]`. Then stop the server: `kill %1`.

- [ ] **Step 3: Commit**

```bash
git add Big_movers_server.py
git commit -m "feat(quiz): add /api/stock-list endpoint for unbiased ticker sampling"
```

---

## Task 2: `Quiz.CONFIG` + `Quiz.Pool` scan — qualifying decision bars

`Quiz.Pool.scan(bars, config)` returns every bar index that qualifies as a decision bar: enough context behind, enough future ahead, currently extended ≥ threshold over the lookback, near the lookback extreme, above the price floor.

**Files:**
- Modify: `Big_movers.html` (add a new `<script>` IIFE block; place it immediately AFTER the SimBlind module closes, i.e. after the `window.SimBlind = {...}` block near line ~13900. Mark boundaries with comments so the test harness can extract it.)
- Test: `tests/quiz_pool.test.cjs`

- [ ] **Step 1: Write the failing test**

Create `tests/quiz_pool.test.cjs`:

```javascript
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

console.log(`\nQuiz.Pool: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/quiz_pool.test.cjs`
Expected: FAIL — `startMarker not found: /* ===== Quiz.CONFIG + Quiz.Pool ===== */` (the block doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

In `Big_movers.html`, immediately after the `window.SimBlind = { ... };` block (and its closing `})();`), add a new script block:

```html
<script>
/* ===== Quiz.CONFIG + Quiz.Pool ===== */
(function(){
  'use strict';
  window.Quiz = window.Quiz || {};

  window.Quiz.CONFIG = {
    LOOKFORWARD_H: 21,
    LOOKBACK_L: 63,
    RUN_THRESHOLD: 0.35,
    MIN_CONTEXT_BARS: 120,
    MIN_PRICE: 1.0,
    REMAINING_THRESHOLDS: [0.05, 0.20, 0.45, 0.65]
  };

  // Scan a bar series for every qualifying decision bar.
  // Returns Candidate[]: { decisionIdx, direction, swingIdx, swingPrice, decisionClose, priorRunPct }
  function scan(bars, config){
    const cfg = config || window.Quiz.CONFIG;
    const out = [];
    if (!Array.isArray(bars) || bars.length < cfg.MIN_CONTEXT_BARS + cfg.LOOKFORWARD_H + 1) return out;

    const firstIdx = cfg.MIN_CONTEXT_BARS;
    const lastIdx  = bars.length - 1 - cfg.LOOKFORWARD_H;

    for (let i = firstIdx; i <= lastIdx; i++){
      const close = +bars[i].close;
      if (!isFinite(close) || close < cfg.MIN_PRICE) continue;

      // Trailing lookback window [i-L .. i].
      const from = Math.max(0, i - cfg.LOOKBACK_L);
      let lo = Infinity, loIdx = from, hi = -Infinity, hiIdx = from;
      for (let j = from; j <= i; j++){
        const l = +bars[j].low, h = +bars[j].high;
        if (isFinite(l) && l < lo){ lo = l; loIdx = j; }
        if (isFinite(h) && h > hi){ hi = h; hiIdx = j; }
      }
      if (!isFinite(lo) || !isFinite(hi) || lo <= 0) continue;

      // UP: rose from swing low to here, and 'here' is near the window high.
      const upRun = (close - lo) / lo;
      const nearHigh = close >= hi - (hi - lo) * 0.10;
      // DOWN: fell from swing high to here, and 'here' is near the window low.
      const downRun = (hi - close) / hi;
      const nearLow = close <= lo + (hi - lo) * 0.10;

      if (upRun >= cfg.RUN_THRESHOLD && nearHigh && loIdx < i){
        out.push({ decisionIdx: i, direction: 'up', swingIdx: loIdx, swingPrice: lo, decisionClose: close, priorRunPct: upRun });
      } else if (downRun >= cfg.RUN_THRESHOLD && nearLow && hiIdx < i){
        out.push({ decisionIdx: i, direction: 'down', swingIdx: hiIdx, swingPrice: hi, decisionClose: close, priorRunPct: downRun });
      }
    }
    return out;
  }

  // Pick one random qualifying candidate (rngFloat injected for testability).
  function pick(bars, config, rngFloat){
    const rnd = (typeof rngFloat === 'function') ? rngFloat : Math.random;
    const cands = scan(bars, config);
    if (!cands.length) return null;
    return cands[Math.floor(rnd() * cands.length)];
  }

  window.Quiz.Pool = { scan: scan, pick: pick };
})();
/* ===== end Quiz.Pool ===== */
</script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/quiz_pool.test.cjs`
Expected: `Quiz.Pool: 8 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add Big_movers.html tests/quiz_pool.test.cjs
git commit -m "feat(quiz): add Quiz.Pool candidate scanning with unit tests"
```

---

## Task 3: `Quiz.Pool.pick` determinism test

Lock in that `pick` is a thin random selector over `scan` and respects the injected RNG.

**Files:**
- Test: `tests/quiz_pool.test.cjs` (append)

- [ ] **Step 1: Write the failing test (append before the final console.log/exit)**

Add these lines into `tests/quiz_pool.test.cjs`, just before the `console.log(\`\nQuiz.Pool: ...\`)` line:

```javascript
// pick() with rng=0 returns the first candidate; rng->~1 returns the last.
const allCands = Quiz.Pool.scan(bars, cfg);
const firstPick = Quiz.Pool.pick(bars, cfg, () => 0);
const lastPick  = Quiz.Pool.pick(bars, cfg, () => 0.999999);
ok('pick(rng=0) == first candidate', firstPick && firstPick.decisionIdx === allCands[0].decisionIdx);
ok('pick(rng~1) == last candidate', lastPick && lastPick.decisionIdx === allCands[allCands.length-1].decisionIdx);
ok('pick on flat series returns null', Quiz.Pool.pick(flat, cfg, () => 0) === null);
```

- [ ] **Step 2: Run test to verify it passes (implementation already exists from Task 2)**

Run: `node tests/quiz_pool.test.cjs`
Expected: `Quiz.Pool: 11 passed, 0 failed`

> If it fails, the bug is in Task 2's `pick`; fix `pick` (do not weaken the test).

- [ ] **Step 3: Commit**

```bash
git add tests/quiz_pool.test.cjs
git commit -m "test(quiz): assert Quiz.Pool.pick RNG determinism"
```

---

## Task 4: `Quiz.Grade` — true-bucket computation + scoring

`Quiz.Grade.trueBucket(bars, candidate, config)` measures the forward extreme over window `H`, computes the fraction of the move still ahead at the decision bar, and buckets it 0..4. `Quiz.Grade.score(predicted, actual)` gives 1.0 exact / 0.5 adjacent / 0 otherwise.

**Files:**
- Modify: `Big_movers.html` (new IIFE block after the Quiz.Pool block)
- Test: `tests/quiz_grade.test.cjs`

- [ ] **Step 1: Write the failing test**

Create `tests/quiz_grade.test.cjs`:

```javascript
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/quiz_grade.test.cjs`
Expected: FAIL — `end not found: /* ===== end Quiz.Grade ===== */`.

- [ ] **Step 3: Write minimal implementation**

In `Big_movers.html`, immediately after the `/* ===== end Quiz.Pool ===== */` comment's closing `</script>`, add:

```html
<script>
/* ===== Quiz.Grade ===== */
(function(){
  'use strict';
  window.Quiz = window.Quiz || {};

  function bucketFromRemaining(remaining, thresholds){
    const t = thresholds || window.Quiz.CONFIG.REMAINING_THRESHOLDS;
    for (let b = 0; b < t.length; b++){ if (remaining < t[b]) return b; }
    return t.length; // == 4 when 4 thresholds
  }

  // Measure forward extreme over window H and bucket the fraction of move remaining.
  function trueBucket(bars, cand, config){
    const cfg = config || window.Quiz.CONFIG;
    const H = cfg.LOOKFORWARD_H;
    const i = cand.decisionIdx;
    const end = Math.min(bars.length - 1, i + H);
    const close = cand.decisionClose;

    let extreme, extremeIdx = i;
    if (cand.direction === 'up'){
      extreme = -Infinity;
      for (let j = i+1; j <= end; j++){ const h = +bars[j].high; if (isFinite(h) && h > extreme){ extreme = h; extremeIdx = j; } }
      if (!isFinite(extreme)) extreme = close;
    } else {
      extreme = Infinity;
      for (let j = i+1; j <= end; j++){ const l = +bars[j].low; if (isFinite(l) && l < extreme){ extreme = l; extremeIdx = j; } }
      if (!isFinite(extreme)) extreme = close;
    }

    const priorRun = Math.abs(close - cand.swingPrice);
    const futureExt = Math.abs(extreme - close);
    const denom = priorRun + futureExt;
    const remaining = denom > 0 ? (futureExt / denom) : 0;
    return { remaining: remaining, bucket: bucketFromRemaining(remaining, cfg.REMAINING_THRESHOLDS), forwardExtremeIdx: extremeIdx, forwardExtreme: extreme };
  }

  // 1.0 exact, 0.5 adjacent, 0 otherwise.
  function score(predictedBucket, actualBucket){
    const d = Math.abs(predictedBucket - actualBucket);
    if (d === 0) return 1.0;
    if (d === 1) return 0.5;
    return 0;
  }

  window.Quiz.Grade = { trueBucket: trueBucket, score: score, bucketFromRemaining: bucketFromRemaining };
})();
/* ===== end Quiz.Grade ===== */
</script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/quiz_grade.test.cjs`
Expected: `Quiz.Grade: 9 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add Big_movers.html tests/quiz_grade.test.cjs
git commit -m "feat(quiz): add Quiz.Grade true-bucket + scoring with unit tests"
```

---

## Task 5: `Quiz.Stats` — session aggregation + baselines

`Quiz.Stats.summarize(rounds)` returns the user's accuracy plus "always say it's still going" and "random" baselines computed on the same rounds, plus a one-line bias readout. Persistence helpers read/write localStorage.

**Files:**
- Modify: `Big_movers.html` (new IIFE block after Quiz.Grade)
- Test: `tests/quiz_stats.test.cjs`

- [ ] **Step 1: Write the failing test**

Create `tests/quiz_stats.test.cjs`:

```javascript
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/quiz_stats.test.cjs`
Expected: FAIL — `start not found: /* ===== Quiz.Stats ===== */`.

- [ ] **Step 3: Write minimal implementation**

In `Big_movers.html`, after the Quiz.Grade block, add:

```html
<script>
/* ===== Quiz.Stats ===== */
(function(){
  'use strict';
  window.Quiz = window.Quiz || {};
  var LS_KEY = 'quizSessions';
  var BUCKET_LABELS = ["It's over","Almost over","Roughly halfway","Early","Just getting started"];

  function rate(arr, pred){ if (!arr.length) return 0; var n=0; for (var i=0;i<arr.length;i++){ if (pred(arr[i])) n++; } return n/arr.length; }

  function summarize(rounds){
    var rs = rounds || [];
    var exactRate   = rate(rs, function(r){ return r.predictedBucket === r.trueBucket; });
    var within1Rate = rate(rs, function(r){ return Math.abs(r.predictedBucket - r.trueBucket) <= 1; });
    var avgCredit   = rs.length ? rs.reduce(function(s,r){ return s + (r.credit||0); }, 0) / rs.length : 0;

    // Baseline 1: always predict bucket 4 ("just getting started" / it keeps going).
    var bAlwaysExact   = rate(rs, function(r){ return r.trueBucket === 4; });
    var bAlwaysWithin1 = rate(rs, function(r){ return Math.abs(4 - r.trueBucket) <= 1; });

    // Baseline 2: uniform random over 5 buckets. exact = 1/5; within1 = mean over rounds of (#buckets within 1)/5.
    var bRandExact = rs.length ? 0.2 : 0;
    var bRandWithin1 = rs.length ? rs.reduce(function(s,r){
      var t=r.trueBucket, n=0; for (var b=0;b<5;b++){ if (Math.abs(b-t)<=1) n++; } return s + n/5;
    },0)/rs.length : 0;

    // Bias readout: which bucket does the user over-predict most vs how often it was true?
    var predCounts=[0,0,0,0,0], trueCounts=[0,0,0,0,0];
    rs.forEach(function(r){ predCounts[r.predictedBucket]++; trueCounts[r.trueBucket]++; });
    var worstB=0, worstGap=-Infinity;
    for (var b=0;b<5;b++){ var gap=predCounts[b]-trueCounts[b]; if (gap>worstGap){ worstGap=gap; worstB=b; } }
    var biasLine = worstGap > 0
      ? 'You called "' + BUCKET_LABELS[worstB] + '" ' + predCounts[worstB] + '×; it was actually that ' + trueCounts[worstB] + '×.'
      : 'No strong directional bias detected.';

    return {
      roundCount: rs.length,
      exactRate: exactRate, within1Rate: within1Rate, avgCredit: avgCredit,
      baselineAlwaysContinueExact: bAlwaysExact, baselineAlwaysContinueWithin1: bAlwaysWithin1,
      baselineRandomExact: bRandExact, baselineRandomWithin1: bRandWithin1,
      biasLine: biasLine,
      predCounts: predCounts, trueCounts: trueCounts, bucketLabels: BUCKET_LABELS
    };
  }

  function loadSessions(){
    try { var raw = window.localStorage.getItem(LS_KEY); return raw ? JSON.parse(raw) : []; }
    catch(e){ return []; }
  }
  function saveSession(session){
    var all = loadSessions(); all.push(session);
    try { window.localStorage.setItem(LS_KEY, JSON.stringify(all)); } catch(e){}
    return all;
  }

  window.Quiz.Stats = { summarize: summarize, loadSessions: loadSessions, saveSession: saveSession, BUCKET_LABELS: BUCKET_LABELS };
})();
/* ===== end Quiz.Stats ===== */
</script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/quiz_stats.test.cjs`
Expected: `Quiz.Stats: 9 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add Big_movers.html tests/quiz_stats.test.cjs
git commit -m "feat(quiz): add Quiz.Stats aggregation + baselines with unit tests"
```

---

## Task 6: Quiz panel HTML + launch button

Add the launch button and the quiz UI shell (question panel with 5 answer buttons, reveal area, summary area). No behavior yet — just markup that later tasks wire up.

**Files:**
- Modify: `Big_movers.html` — add the launch button next to `id="sim-blind-btn"` (~line 5083); add the quiz panel markup near the other sim modals.

- [ ] **Step 1: Add the launch button**

Find `id="sim-blind-btn"` (~line 5083) and add a sibling button right after it:

```html
<button type="button" id="quiz-btn" class="sim-pill" title="Top-or-Bottom Quiz: can you call the top/bottom?">🎯 Top/Bottom Quiz</button>
```

(Match the surrounding button's existing class names — copy the class string from `sim-blind-btn` so it visually matches.)

- [ ] **Step 2: Add the quiz panel markup**

Find the SimBlind mini-modal markup (search for `id="sim-blind-equity"`, ~line 13463) and add this panel just before that block's container (or alongside the other modal containers):

```html
<div id="quiz-panel" class="quiz-panel" style="display:none;">
  <div class="quiz-bar">
    <span id="quiz-progress" class="quiz-progress">Round 1 / 10</span>
    <span id="quiz-direction" class="quiz-direction"></span>
    <button type="button" id="quiz-exit" class="sim-pill">Exit Quiz</button>
  </div>

  <div id="quiz-question" class="quiz-question">
    <div class="quiz-prompt">This stock has had an extended move. How much is left?</div>
    <div class="quiz-answers">
      <button type="button" class="quiz-ans" data-bucket="0">It's over</button>
      <button type="button" class="quiz-ans" data-bucket="1">Almost over</button>
      <button type="button" class="quiz-ans" data-bucket="2">Roughly halfway</button>
      <button type="button" class="quiz-ans" data-bucket="3">Early</button>
      <button type="button" class="quiz-ans" data-bucket="4">Just getting started</button>
    </div>
  </div>

  <div id="quiz-reveal" class="quiz-reveal" style="display:none;">
    <div id="quiz-reveal-text" class="quiz-reveal-text"></div>
    <button type="button" id="quiz-reveal-ticker" class="sim-pill">Reveal ticker</button>
    <button type="button" id="quiz-next" class="sim-pill sim-pill-active">Next →</button>
  </div>

  <div id="quiz-summary" class="quiz-summary" style="display:none;"></div>
</div>
```

- [ ] **Step 3: Add minimal styles**

Find the existing `.sim-pill` / sim panel CSS (search `.sim-pill`) and add nearby, following the light-theme convention (black text `#000`, light background — per the project's HTML styling rule):

```css
.quiz-panel{ padding:12px; background:var(--bg2, #f7f7f7); color:#000; border-radius:8px; }
.quiz-bar{ display:flex; align-items:center; gap:12px; margin-bottom:10px; }
.quiz-progress{ font-weight:600; }
.quiz-direction{ color:#444; }
.quiz-prompt{ margin-bottom:8px; font-weight:600; color:#000; }
.quiz-answers{ display:flex; flex-wrap:wrap; gap:8px; }
.quiz-ans{ padding:8px 12px; border:1px solid #ccc; background:#fff; color:#000; border-radius:6px; cursor:pointer; }
.quiz-ans:hover{ background:#eee; }
.quiz-ans:disabled{ opacity:0.5; cursor:default; }
.quiz-ans.is-correct{ border-color:#2a8; background:#e6f7ef; }
.quiz-ans.is-chosen-wrong{ border-color:#c33; background:#fbe9e9; }
.quiz-reveal{ margin-top:12px; }
.quiz-reveal-text{ margin-bottom:8px; color:#000; }
.quiz-summary{ margin-top:12px; color:#000; }
```

- [ ] **Step 4: Verify it loads without breaking the page**

Run the server (Task 1 Step 2 command), open `http://localhost:<port>/Big_movers.html` in a browser, confirm the page renders and the `🎯 Top/Bottom Quiz` button is visible. (Full behavior verified in Task 8 via `verify-ui`.)

- [ ] **Step 5: Commit**

```bash
git add Big_movers.html
git commit -m "feat(quiz): add quiz panel markup, launch button, and styles"
```

---

## Task 7: `Quiz.Ctrl` — round lifecycle, data loading, chart masking

Wire the pure modules to the chart and DOM: fetch the ticker universe, pick a random ticker, fetch its OHLCV, scan for a candidate (retry tickers until one qualifies), render the masked chart (bars `[start..decisionIdx]`), capture the answer, reveal (re-feed bars through `decisionIdx+H`), advance rounds, then show the summary.

**Files:**
- Modify: `Big_movers.html` — new IIFE block after Quiz.Stats. Reuse globals: `chart`, `candleSeries`, `currentBars`, `currentSymbol`, `calcEMA` (defined at `Big_movers.html:6229`/`6973`), and the topbar mask element ids used by SimBlind (`ct-sym`, `ct-cond`, `ct-gain`, `ct-range`, `ct-vol`).

- [ ] **Step 1: Add the controller block**

After the Quiz.Stats block, add:

```html
<script>
/* ===== Quiz.Ctrl ===== */
(function(){
  'use strict';
  window.Quiz = window.Quiz || {};
  var TOTAL_ROUNDS_DEFAULT = 10;
  var MAX_TICKER_TRIES = 40;

  var S = null; // session state

  function $(id){ return document.getElementById(id); }

  async function _fetchList(){
    var resp = await fetch('/api/stock-list');
    var data = await resp.json();
    if (data && data.error) throw new Error(data.error);
    return Array.isArray(data) ? data : [];
  }
  async function _fetchBars(sym){
    var resp = await fetch('/api/ohlcv?symbol=' + encodeURIComponent(sym));
    var data = await resp.json();
    if (data && data.error) return null;
    return Array.isArray(data) ? data : null;
  }

  // Pick a ticker whose history yields at least one qualifying candidate.
  async function _drawRound(){
    var list = S.list;
    for (var tries = 0; tries < MAX_TICKER_TRIES; tries++){
      var sym = list[Math.floor(Math.random() * list.length)];
      var bars = await _fetchBars(sym);
      if (!bars) continue;
      var cand = window.Quiz.Pool.pick(bars, window.Quiz.CONFIG, Math.random);
      if (cand) return { symbol: sym, bars: bars, cand: cand };
    }
    return null;
  }

  function _renderMasked(bars, cand){
    var startIdx = Math.max(0, cand.decisionIdx - 160);
    var visible = bars.slice(startIdx, cand.decisionIdx + 1); // up to & incl decision bar
    try { candleSeries.setData(visible.map(function(b){ return { time:b.time, open:+b.open, high:+b.high, low:+b.low, close:+b.close }; })); } catch(e){}
    try {
      if (chart && chart.timeScale) chart.timeScale().fitContent();
    } catch(e){}
    // Mask identity in topbar (mirror SimBlind).
    var sym=$('ct-sym'), cond=$('ct-cond'), gain=$('ct-gain'), range=$('ct-range');
    if (sym) sym.textContent = '🕶 BLIND TICKER';
    if (cond) cond.textContent = '????';
    if (gain) gain.textContent = '';
    if (range) range.textContent = '';
    S._startIdx = startIdx;
  }

  function _renderReveal(){
    var bars = S.round.bars, cand = S.round.cand;
    var end = Math.min(bars.length - 1, cand.decisionIdx + window.Quiz.CONFIG.LOOKFORWARD_H);
    var visible = bars.slice(S._startIdx, end + 1);
    try { candleSeries.setData(visible.map(function(b){ return { time:b.time, open:+b.open, high:+b.high, low:+b.low, close:+b.close }; })); } catch(e){}
    try { if (chart && chart.timeScale) chart.timeScale().fitContent(); } catch(e){}
  }

  function _revealTicker(){
    var sym=$('ct-sym'), cond=$('ct-cond');
    if (sym) sym.textContent = S.round.symbol;
    if (cond) cond.textContent = (S.round.bars[S.round.cand.decisionIdx].time || '').slice(0,4);
  }

  async function _startRound(){
    $('quiz-question').style.display = '';
    $('quiz-reveal').style.display = 'none';
    Array.prototype.forEach.call(document.querySelectorAll('.quiz-ans'), function(b){ b.disabled=false; b.classList.remove('is-correct','is-chosen-wrong'); });
    $('quiz-progress').textContent = 'Round ' + (S.roundIdx+1) + ' / ' + S.totalRounds;
    $('quiz-direction').textContent = 'Loading…';

    var r = await _drawRound();
    if (!r){ $('quiz-direction').textContent = 'Could not find a qualifying chart — try again.'; return; }
    S.round = r;
    S.currentSymbol = r.symbol;
    $('quiz-direction').textContent = r.cand.direction === 'up' ? 'This stock has been RISING.' : 'This stock has been FALLING.';
    _renderMasked(r.bars, r.cand);
  }

  function _answer(predictedBucket){
    var cand = S.round.cand, bars = S.round.bars;
    var truth = window.Quiz.Grade.trueBucket(bars, cand, window.Quiz.CONFIG);
    var credit = window.Quiz.Grade.score(predictedBucket, truth.bucket);
    S.rounds.push({
      symbol: S.round.symbol,
      decisionDate: bars[cand.decisionIdx].time,
      direction: cand.direction,
      predictedBucket: predictedBucket, trueBucket: truth.bucket, credit: credit
    });
    // Lock buttons + mark correctness.
    Array.prototype.forEach.call(document.querySelectorAll('.quiz-ans'), function(b){
      b.disabled = true;
      var bk = +b.getAttribute('data-bucket');
      if (bk === truth.bucket) b.classList.add('is-correct');
      else if (bk === predictedBucket) b.classList.add('is-chosen-wrong');
    });
    _renderReveal();
    var labels = window.Quiz.Stats.BUCKET_LABELS;
    $('quiz-reveal-text').innerHTML =
      'You said <b>' + labels[predictedBucket] + '</b>. Actual: <b>' + labels[truth.bucket] + '</b>. ' +
      'Credit: <b>' + credit.toFixed(1) + '</b>';
    $('quiz-question').style.display = '';
    $('quiz-reveal').style.display = '';
  }

  function _next(){
    S.roundIdx++;
    if (S.roundIdx >= S.totalRounds){ _finish(); return; }
    _startRound();
  }

  function _finish(){
    var summary = window.Quiz.Stats.summarize(S.rounds);
    window.Quiz.Stats.saveSession({ ts: Date.now(), rounds: S.rounds, summary: summary });
    $('quiz-question').style.display = 'none';
    $('quiz-reveal').style.display = 'none';
    var el = $('quiz-summary'); el.style.display = '';
    el.innerHTML = window.Quiz.UI.renderSummary(summary);
  }

  async function start(totalRounds){
    var list;
    try { list = await _fetchList(); } catch(e){ alert('Could not load ticker list: ' + (e && e.message || e)); return; }
    if (!list.length){ alert('No tickers available.'); return; }
    S = { list: list, totalRounds: totalRounds || TOTAL_ROUNDS_DEFAULT, roundIdx: 0, rounds: [], round: null };
    $('quiz-panel').style.display = '';
    $('quiz-summary').style.display = 'none';
    _startRound();
  }
  function exit(){ if (S) S=null; var p=$('quiz-panel'); if (p) p.style.display='none'; }

  window.Quiz.Ctrl = { start: start, exit: exit, _answer: _answer, _next: _next, _revealTicker: _revealTicker };
})();
/* ===== end Quiz.Ctrl ===== */
</script>
```

- [ ] **Step 2: Add `Quiz.UI.renderSummary` + event wiring**

After the Quiz.Ctrl block, add:

```html
<script>
/* ===== Quiz.UI ===== */
(function(){
  'use strict';
  window.Quiz = window.Quiz || {};

  function pct(x){ return (x*100).toFixed(0) + '%'; }

  function renderSummary(s){
    var rows = [
      ['You (exact)', pct(s.exactRate)],
      ['You (within 1)', pct(s.within1Rate)],
      ['"It always keeps going" (exact)', pct(s.baselineAlwaysContinueExact)],
      ['"It always keeps going" (within 1)', pct(s.baselineAlwaysContinueWithin1)],
      ['Random guessing (exact)', pct(s.baselineRandomExact)]
    ];
    var html = '<h3>Session complete — ' + s.roundCount + ' rounds</h3><table class="quiz-score">';
    rows.forEach(function(r){ html += '<tr><td>' + r[0] + '</td><td><b>' + r[1] + '</b></td></tr>'; });
    html += '</table>';
    html += '<p class="quiz-bias">' + s.biasLine + '</p>';
    var beat = s.exactRate <= s.baselineAlwaysContinueExact;
    html += '<p class="quiz-verdict">' + (beat
      ? 'You did <b>no better</b> than always assuming the move keeps going — which is exactly why the EMA stop, not your gut, should decide when you exit.'
      : 'You edged out the naive baseline this session — run more rounds to see if it holds.') + '</p>';
    html += '<button type="button" id="quiz-restart" class="sim-pill sim-pill-active">Play again</button>';
    return html;
  }

  function _wire(){
    var btn = document.getElementById('quiz-btn');
    if (btn && !btn._quizBound){ btn._quizBound = true; btn.addEventListener('click', function(){ window.Quiz.Ctrl.start(10); }); }

    var panel = document.getElementById('quiz-panel');
    if (panel && !panel._quizBound){
      panel._quizBound = true;
      panel.addEventListener('click', function(e){
        var t = e.target;
        if (t.classList && t.classList.contains('quiz-ans') && !t.disabled){ window.Quiz.Ctrl._answer(+t.getAttribute('data-bucket')); return; }
        if (t.id === 'quiz-next'){ window.Quiz.Ctrl._next(); return; }
        if (t.id === 'quiz-reveal-ticker'){ window.Quiz.Ctrl._revealTicker(); return; }
        if (t.id === 'quiz-exit'){ window.Quiz.Ctrl.exit(); return; }
        if (t.id === 'quiz-restart'){ window.Quiz.Ctrl.start(10); return; }
      });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _wire);
  else _wire();

  window.Quiz.UI = { renderSummary: renderSummary };
})();
/* ===== end Quiz.UI ===== */
</script>
```

- [ ] **Step 3: Re-run all pure-core tests (guard against accidental block-marker breakage)**

Run:
```bash
node tests/quiz_pool.test.cjs && node tests/quiz_grade.test.cjs && node tests/quiz_stats.test.cjs
```
Expected: all three print `... passed, 0 failed`.

- [ ] **Step 4: Commit**

```bash
git add Big_movers.html
git commit -m "feat(quiz): wire Quiz.Ctrl round lifecycle + Quiz.UI summary"
```

---

## Task 8: End-to-end UI verification

Drive a full quiz session through the browser and confirm behavior + console cleanliness.

**Files:** none (verification only)

- [ ] **Step 1: Start the server**

Run:
```bash
cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers" && \
python3 Big_movers_server.py >/tmp/quiz_server.log 2>&1 &
sleep 2
```
(Use the correct port from `Big_movers_server.py`.)

- [ ] **Step 2: Verify with the `verify-ui` skill (Playwright MCP)**

Invoke the `verify-ui` skill to drive `http://localhost:<port>/Big_movers.html`:
1. Click `#quiz-btn` → `#quiz-panel` becomes visible, a chart renders, `#quiz-direction` shows "RISING" or "FALLING".
2. Click a `.quiz-ans` button → `#quiz-reveal` appears, buttons disabled, one `.is-correct` highlighted, `#quiz-reveal-text` shows "You said … Actual: … Credit: …", and the chart now shows additional forward bars.
3. Click `#quiz-reveal-ticker` → `#ct-sym` changes from "🕶 BLIND TICKER" to a real symbol.
4. Click `#quiz-next` repeatedly through all 10 rounds → `#quiz-summary` appears with the score table, bias line, and verdict.
5. Read the browser console — expect no uncaught errors.

Expected: all five behaviors pass; console clean.

- [ ] **Step 3: Fix any issues found, re-run pure tests, re-verify**

If `verify-ui` surfaces a bug, fix it in `Big_movers.html`, then re-run `node tests/quiz_pool.test.cjs && node tests/quiz_grade.test.cjs && node tests/quiz_stats.test.cjs` and repeat Step 2 before claiming done.

- [ ] **Step 4: Stop the server and commit any fixes**

```bash
kill %1 2>/dev/null
git add -A && git commit -m "fix(quiz): address UI verification findings" || echo "no fixes needed"
```

---

## Self-Review Notes (completed by plan author)

- **Spec coverage:** §2 placement → Tasks 6–7 (mode in `Big_movers.html`, reuse chart/mask). §2 server `/api/stock-list` → Task 1. §3 components → `Quiz.Pool` (T2–3), `Quiz.Grade` (T4), `Quiz.Stats` (T5), `Quiz.Ctrl` (T7), `Quiz.UI` (T7). §4 selection algorithm + all tunable constants → Task 2 (`Quiz.CONFIG` + `scan`). §5 5-way question → Task 6 markup + Task 7 buckets. §6 fixed-window grading + exact/adjacent scoring + EMA visible → Task 4 (EMA stays on the existing chart series; no separate work needed). §7 reveal (forward bars + extreme + ticker unmask) → Task 7 `_renderReveal`/`_revealTicker`. §8 session, baselines, bias line, localStorage → Task 5 + Task 7 `_finish` + Task 7 UI summary. §9 testing → Tasks 2–5 Node tests + Task 8 verify-ui.
- **Constant alignment:** `Quiz.CONFIG` defaults (`LOOKFORWARD_H 21`, `LOOKBACK_L 63`, `RUN_THRESHOLD 0.35`, `MIN_CONTEXT_BARS 120`, `MIN_PRICE 1.0`, `REMAINING_THRESHOLDS [0.05,0.20,0.45,0.65]`) match the spec §4/§6.
- **Type/name consistency:** Candidate fields (`decisionIdx, direction, swingIdx, swingPrice, decisionClose, priorRunPct`) produced by `Quiz.Pool.scan` are consumed unchanged by `Quiz.Grade.trueBucket` and `Quiz.Ctrl`. Round fields (`predictedBucket, trueBucket, credit, …`) produced by `Quiz.Ctrl._answer` match what `Quiz.Stats.summarize` reads. Bucket indices 0..4 are consistent across Grade, Stats labels, UI markup `data-bucket`, and answer handling.
- **Open verification risk:** Task 7 assumes `candleSeries.setData(...)` re-renders cleanly when fed a sliced range and that `chart.timeScale().fitContent()` reframes — confirmed `candleSeries` and `setData` exist (`Big_movers.html:6229`, many `setData` call sites). If the main chart pipeline overrides data on other events, Task 8 will surface it; fix by routing through the existing render path instead of `setData` directly.
