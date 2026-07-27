const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');

const noiseCheckbox = html.match(/<input\b[^>]*\bid=["']portsim-rand-noise["'][^>]*>/i);

if (!noiseCheckbox) {
  console.error('FAIL: portfolio cross-year noise checkbox is missing');
  process.exit(1);
}

if (!/\bchecked(?:\s*=\s*(?:"checked"|'checked'|checked))?(?=\s|\/?>)/i.test(noiseCheckbox[0])) {
  console.error('FAIL: portfolio cross-year noise is not enabled by default');
  process.exit(1);
}

console.log('PASS: portfolio cross-year noise is enabled by default');
