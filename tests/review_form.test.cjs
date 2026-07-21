const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'Big_movers.html'), 'utf8');

function extractFunction(source, name) {
  const start = source.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('Function not found: ' + name);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let i = brace; i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}') {
      depth--;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error('Unclosed function: ' + name);
}

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log('PASS:', name);
  } catch (err) {
    failed++;
    console.error('FAIL:', name, '->', err.message);
  }
}

test('leg review is reduced to simulation-relevant fields', () => {
  const fn = extractFunction(html, '_renderLegSRForm');
  ['Setup type', 'Primary discipline result', 'Technical lesson'].forEach(label => {
    if (!fn.includes(label)) throw new Error('missing ' + label);
  });
  ['Intended hold', 'Entry state', 'Would hold if real', 'At-heat response', 'Thesis'].forEach(label => {
    if (fn.includes(label)) throw new Error('obsolete field remains: ' + label);
  });
});

test('setup type supports a saved custom value', () => {
  if (!/\['custom',\s*'Custom/.test(html)) throw new Error('custom setup option missing');
  if (!/data-srfield["']?\s*:\s*["']setupCustom/.test(html)) throw new Error('custom setup field missing');
});

test('discipline choices cover the known simulation failure modes', () => {
  [
    'fomo_chased_entry', 'loss_avoidance_exit', 'profit_protection_exit',
    'panic_sellout', 'held_past_technical_exit', 'moved_stop_wider',
    'unplanned_add', 'emotional_reentry', 'overtraded'
  ].forEach(code => {
    if (!html.includes("['" + code + "'")) throw new Error('missing discipline code ' + code);
  });
});

test('session reflection uses focused categories and open text without ratings', () => {
  const fn = extractFunction(html, '_renderSessionSRForm');
  ['Dominant pattern', 'Did the previous result affect the next decision?',
   'What did I execute well?', 'Where did discipline weaken?', 'One rule for the next simulation'].forEach(label => {
    if (!fn.includes(label)) throw new Error('missing ' + label);
  });
  ['Emotional score', 'Regime felt', 'If real $', 'Next day action', 'Out of how many'].forEach(label => {
    if (fn.includes(label)) throw new Error('obsolete session field remains: ' + label);
  });
  if (fn.includes('_srRating(')) throw new Error('session ratings should be removed');
});

test('one Save Review action persists schema version 2', () => {
  if (!/id=["']portsim-review-save["'][^>]*>\ud83d\udcbe Save Review</.test(html)) {
    throw new Error('single Save Review action missing');
  }
  const saveFn = extractFunction(html, '_onSave');
  if (!/review\.schemaVersion\s*=\s*2/.test(saveFn)) throw new Error('Save does not persist schema v2');
});

test('Deep CSV contains the new structured and open-text fields', () => {
  const exportFn = extractFunction(html, '_exportDeepCSV');
  [
    'sessionDominantPattern', 'sessionOutcomeCarryover', 'sessionExecutedWell',
    'sessionDisciplineChallenge', 'sessionNextRunRule', 'legSetupCustom',
    'legDisciplineResult', 'legTechnicalLesson'
  ].forEach(column => {
    if (!exportFn.includes("'" + column + "'")) throw new Error('missing CSV column ' + column);
  });
});

test('PDF title defaults to the simulation start date', () => {
  const sandbox = {};
  vm.createContext(sandbox);
  const fn = extractFunction(html, '_printDocumentTitle');
  vm.runInContext(fn + '\nthis.printDocumentTitle = _printDocumentTitle;', sandbox);
  const title = sandbox.printDocumentTitle({ startDate: '2025-01-02', endDate: '2025-03-31' });
  if (title !== '2025-01-02 Portfolio Simulation Review') {
    throw new Error('unexpected PDF title: ' + title);
  }
  const printFn = extractFunction(html, '_onPrint');
  if (!/document\.title\s*=\s*_printDocumentTitle/.test(printFn)) throw new Error('print path does not set the document title');
});

test('review header offers PDF export without a second data-export workflow', () => {
  if (!/id=["']portsim-review-pdf["'][^>]*>\ud83d\udda8 Export PDF</.test(html)) {
    throw new Error('Export PDF action missing');
  }
  if (/id=["']portsim-review-md["']/.test(html)) throw new Error('Markdown action still complicates the review header');
});

console.log(`\nReview form: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
