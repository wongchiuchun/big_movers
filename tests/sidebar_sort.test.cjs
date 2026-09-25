const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');
const code = html.slice(html.indexOf('function applySort(){'), html.indexOf("['f-gain','f-sym','f-year'].forEach"));

function sort(rows, sortCol = 'year', sortDir = 1) {
  const ctx = { filtered: rows.map(r => ({...r})), sortCol, sortDir,
    currentMoveRow: null, document: { getElementById: () => ({}) }, renderTable() {} };
  vm.createContext(ctx);
  vm.runInContext(code + '\napplySort();', ctx);
  return ctx.filtered;
}

test('year sort places updated TWST and appended ILMN alphabetically within 2026', () => {
  const rows = ['ACHC', 'TWST', 'NBIS', 'ILAG', 'IMC', 'TWLO', 'TXG', 'ZTG', 'ILMN']
    .map(symbol => ({ symbol, year: '2026' }));
  assert.deepEqual(sort(rows).map(r => r.symbol),
    ['ACHC', 'ILAG', 'ILMN', 'IMC', 'NBIS', 'TWLO', 'TWST', 'TXG', 'ZTG']);
});

test('year direction changes year groups while symbols remain alphabetical', () => {
  const rows = [{year:'2025', symbol:'ZZZ'}, {year:'2026', symbol:'TWST'}, {year:'2026', symbol:'ILMN'}];
  assert.deepEqual(sort(rows, 'year', -1).map(r => r.symbol), ['ILMN', 'TWST', 'ZZZ']);
});

test('explicit gain sorting still ranks gains', () => {
  const rows = [{symbol:'ILMN', gain_pct:'289.62'}, {symbol:'TWST', gain_pct:'661.71'}];
  assert.deepEqual(sort(rows, 'gain_pct', -1).map(r => r.symbol), ['TWST', 'ILMN']);
});

test('initial sort indicator matches ascending year sort', () => {
  assert.match(html, /data-col="year" class="sort-asc"/);
  assert.doesNotMatch(html, /data-col="gain_pct" class="sort-desc"/);
});
