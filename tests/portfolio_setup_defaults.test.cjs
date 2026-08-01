const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

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

test('extended timeframe is optional and reaches both randomization paths', () => {
  const extendedCheckbox = html.match(
    /<input\b[^>]*\bid=["']portsim-rand-extended["'][^>]*>/i
  );
  assert.ok(extendedCheckbox, 'extended timeframe checkbox is missing');
  assert.doesNotMatch(extendedCheckbox[0], /\bchecked\b/i);
  assert.match(html, /Extended timeframe/i);
  assert.match(html, /6–9 month/i);

  const handler = extractFunction(html, 'handleRandomize');
  assert.match(handler, /_makeRandomWindow\(year, rng, extendedOn\)/);
  assert.match(handler, /extended:\s*extendedOn/);
});
