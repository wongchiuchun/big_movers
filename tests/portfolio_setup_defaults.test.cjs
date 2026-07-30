const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'Big_movers.html'), 'utf8');

test('portfolio setup loads the local balanced-basket module', () => {
  assert.match(html, /<script src="portfolio_basket\.js"><\/script>/);
  assert.doesNotMatch(html, /<script[^>]+src=["']https?:\/\/[^"']+portfolio_basket/i);
});

test('portfolio randomizer defaults to six balanced tickers', () => {
  const countInput = html.match(/<input\b[^>]*\bid=["']portsim-rand-count["'][^>]*>/i);
  assert.ok(countInput, 'random ticker count input is missing');
  assert.match(countInput[0], /\bvalue=["']6["']/i);

  const balancedCheckbox = html.match(/<input\b[^>]*\bid=["']portsim-rand-noise["'][^>]*>/i);
  assert.ok(balancedCheckbox, 'balanced basket checkbox is missing');
  assert.match(
    balancedCheckbox[0],
    /\bchecked(?:\s*=\s*(?:"checked"|'checked'|checked))?(?=\s|\/?>)/i
  );
  assert.match(html, /Balanced basket/i);
  assert.doesNotMatch(html, /Cross-year noise/i);
});
