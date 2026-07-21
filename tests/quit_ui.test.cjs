const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');

let passed = 0;
let failed = 0;
function ok(name, condition) {
  if (condition) {
    passed++;
    console.log('PASS:', name);
  } else {
    failed++;
    console.error('FAIL:', name);
  }
}

ok('topbar exposes Quit button', /id=["']quit-app-btn["']/.test(html));
ok('Quit button lives inside the chart toolbar', /class=["']chart-topbar["'][\s\S]*?id=["']quit-app-btn["']/.test(html));
ok('icon-only Quit button has an accessible label', /id=["']quit-app-btn["'][^>]*aria-label=["']Quit Big Movers["']/.test(html));
ok('Quit button posts to shutdown endpoint', /fetch\(["']\/api\/shutdown["'][\s\S]*method:\s*["']POST["']/.test(html));
ok('Quit request includes the local UI guard header', /["']X-Big-Movers-UI["']\s*:\s*["']1["']/.test(html));
ok('successful shutdown shows a closed message', /Big Movers has closed/.test(html));

console.log(`\nQuit UI: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
