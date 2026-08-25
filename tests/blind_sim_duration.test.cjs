const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'Big_movers.html'), 'utf8');

function extractFunction(source, name) {
  const start = source.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('Function not found: ' + name);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index++) {
    if (source[index] === '{') depth++;
    if (source[index] === '}') {
      depth--;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error('Unclosed function: ' + name);
}

function extractConstObject(source, name) {
  const start = source.indexOf('const ' + name + ' =');
  if (start < 0) throw new Error('Constant not found: ' + name);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index++) {
    if (source[index] === '{') depth++;
    if (source[index] === '}') {
      depth--;
      if (depth === 0) return source.slice(start, index + 1) + ';';
    }
  }
  throw new Error('Unclosed constant: ' + name);
}

function loadDurationHelpers() {
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(
    extractConstObject(html, 'DURATION_BANDS') + '\n' +
      extractFunction(html, '_randomBlindDurationBars') + '\n' +
      extractFunction(html, '_blindEndIdx') + '\n' +
      extractFunction(html, '_pickBlindWindow') + '\n' +
      extractFunction(html, '_blindLoadedRowMatches') + '\n' +
      'this.randomBars = _randomBlindDurationBars;\n' +
      'this.endIdx = _blindEndIdx;\n' +
      'this.pickWindow = _pickBlindWindow;\n' +
      'this.loadedRowMatches = _blindLoadedRowMatches;',
    sandbox
  );
  return sandbox;
}

test('blind duration bands include their exact trading-bar boundaries', () => {
  const helpers = loadDurationHelpers();

  assert.equal(helpers.randomBars('4-6', () => 0), 84);
  assert.equal(helpers.randomBars('4-6', () => 0.999999), 126);
  assert.equal(helpers.randomBars('6-12', () => 0), 126);
  assert.equal(helpers.randomBars('6-12', () => 0.999999), 252);
  assert.equal(helpers.randomBars('invalid', () => 0), 84);
});

test('blind duration includes Day 0 in its inclusive end index', () => {
  const helpers = loadDurationHelpers();
  assert.equal(helpers.endIdx(85, 84), 168);
  assert.equal(helpers.endIdx(85, 252), 336);
});

test('blind window picker requires the complete selected duration', () => {
  const helpers = loadDurationHelpers();

  assert.deepEqual(
    { ...helpers.pickWindow(169, 84, 85, null, () => 0) },
    { startIdx: 85, endIdx: 168, durationBars: 84 }
  );
  assert.equal(helpers.pickWindow(168, 84, 85, null, () => 0), null);

  const latest = { ...helpers.pickWindow(200, 84, 85, null, () => 0.999999) };
  assert.deepEqual(latest, { startIdx: 116, endIdx: 199, durationBars: 84 });

  const capped = { ...helpers.pickWindow(220, 84, 85, 100, () => 0.999999) };
  assert.deepEqual(capped, { startIdx: 100, endIdx: 183, durationBars: 84 });
});

test('blind candidate bars must belong to the row that actually loaded', () => {
  const helpers = loadDurationHelpers();

  assert.equal(
    helpers.loadedRowMatches({ symbol: 'NVDA', year: 2023 }, { symbol: 'NVDA', year: '2023' }),
    true
  );
  assert.equal(
    helpers.loadedRowMatches({ symbol: 'NVDA', year: 2023 }, { symbol: 'AMD', year: 2023 }),
    false
  );
  assert.equal(
    helpers.loadedRowMatches({ symbol: 'NVDA', year: 2023 }, { symbol: 'NVDA', year: 2024 }),
    false
  );
  assert.equal(helpers.loadedRowMatches({ symbol: 'NVDA', year: 2023 }, null), false);
});

test('existing Blind modal offers the two random duration bands', () => {
  assert.match(html, /id=["']sim-blind-duration["']/);
  assert.match(html, /value=["']4-6["']/);
  assert.match(html, /value=["']6-12["']/);
  assert.doesNotMatch(html, /id=["']sim-blind-bars["']/);

  const button = html.match(/<button\b[^>]*\bid=["']sim-blind-btn["'][^>]*>/i);
  assert.ok(button, 'Blind button is missing');
  assert.match(button[0], /4–6 months/);
  assert.match(button[0], /6–12 months/);
});

test('existing Blind launch samples once, requires a full window, and uses Sim.Ctrl', () => {
  const launch = extractFunction(html, '_startBlindSelection');
  const applyMask = extractFunction(html, '_applyMask');
  const sampleAt = launch.indexOf('_randomBlindDurationBars(');
  const retryAt = launch.indexOf('for (let attempts');

  assert.ok(sampleAt >= 0 && retryAt > sampleAt, 'duration must be sampled once before candidate retries');
  assert.match(launch, /_pickBlindWindow\(currentBars\.length,\s*durationBars,\s*MIN_CONTEXT,\s*capIdx\)/);
  assert.match(launch, /if \(!_blindLoadedRowMatches\(row,\s*currentMoveRow\)\) continue;/);
  assert.doesNotMatch(launch, /Math\.min\(currentBars\.length\s*-\s*1,\s*pickedStartIdx/);
  assert.match(launch, /Sim\.Ctrl\.startBlindPlayback\(/);
  assert.match(launch, /if \(!started\)/);
  assert.match(launch, /endIdx:\s*pickedEndIdx/);
  assert.match(launch, /Try again\./);
  assert.match(applyMask, /_state\.endIdx\s*-\s*_state\.dayZeroIdx/);
});
