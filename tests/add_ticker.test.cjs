const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');
const filters = html.slice(html.indexOf('function applyFilters(){'), html.indexOf('function populateAIFilter()'));
const add = html.slice(html.indexOf('(function() {', html.indexOf('// ============ FETCH TICKER / EXTEND')), html.indexOf('  // Extend to Today button')) + '\n})();';

function harness({ symbol = 'TWST', values = {}, saveError = false, resultMissing = false } = {}) {
  const elements = new Map();
  function el(id) {
    if (!elements.has(id)) elements.set(id, {
      value: values[id] || '', textContent: '', className: '', disabled: false,
      classList: { add() {}, remove() {} }, focus() {},
      listeners: {}, addEventListener(event, fn) { this.listeners[event] = fn; },
    });
    return elements.get(id);
  }
  el('fetch-symbol').value = symbol.toLowerCase();
  el('fetch-start').value = '2025-01-01';
  el('fetch-year').value = '2026';
  const row = { symbol, year: '2025', gain_pct: symbol === 'TWST' ? '661.71' : '289.62' };
  const ctx = {
    document: { getElementById: el }, allRows: [], filtered: [], aiClassByMoveKey: {},
    getMeta: () => ({}), getAnnotationSource: () => 'none', moveKey: r => r.symbol + '_' + r.year,
    applySort() {}, selectRow(index) { ctx.selected = ctx.filtered[index]; },
    setTimeout() { ctx.closing = true; },
    async fetch(url) {
      if (url === '/api/fetch-ticker') return { ok: true, json: async () => ({ bars_added: 400, result_row: resultMissing ? null : row }) };
      assert.equal(url, '/api/add-result');
      return { ok: !saveError, json: async () => saveError ? { error: 'Disk full' } : { ok: true } };
    },
  };
  vm.createContext(ctx);
  vm.runInContext(filters + '\n' + add, ctx);
  return { ctx, el, submit: () => el('fetch-submit-btn').listeners.click() };
}

for (const symbol of ['TWST', 'ILMN']) {
  for (const [filter, value] of Object.entries({ 'f-gain': '1000', 'f-sym': 'NVDA', 'f-year': '2025', 'f-tag': 'EP', 'f-dir': 'long', 'f-rating': 'A', 'f-ai': 'EP', 'f-src': 'human' })) {
    test(`Add ${symbol} 2026 reveals and selects it despite ${filter}`, async () => {
      const h = harness({ symbol, values: { 'f-year': '2026', [filter]: value } });
      await h.submit();
      assert.ok(h.ctx.filtered.some(r => r.symbol === symbol && r.year === '2026'), 'added ticker must appear in sidebar');
      assert.equal(h.ctx.selected?.symbol, symbol);
    });
  }
}

test('compatible filters remain in place and re-adding updates the existing row', async () => {
  const h = harness({ values: { 'f-year': '2026', 'f-gain': '200', 'f-sym': 'TW', 'f-src': 'none' } });
  await h.submit();
  await h.submit();
  assert.equal(h.ctx.allRows.length, 1);
  assert.equal(h.ctx.selected?.symbol, 'TWST');
  assert.equal(h.el('f-gain').value, '200');
  assert.equal(h.el('f-sym').value, 'TW');
  assert.equal(h.el('f-src').value, 'none');
});

test('failed persistence reports an error without adding an unsaved sidebar row', async () => {
  const h = harness({ saveError: true });
  await h.submit();
  assert.equal(h.ctx.allRows.length, 0);
  assert.match(h.el('fetch-status').textContent, /Disk full/);
  assert.equal(h.el('fetch-status').className, 'fetch-status error');
  assert.ok(!h.ctx.closing);
});

test('missing result row cannot report a successful add', async () => {
  const h = harness({ resultMissing: true });
  await h.submit();
  assert.equal(h.el('fetch-status').className, 'fetch-status error');
  assert.ok(!h.ctx.closing);
});
