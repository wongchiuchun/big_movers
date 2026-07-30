const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

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

function loadFunctions(names) {
  const sandbox = {};
  vm.createContext(sandbox);
  const source = names.map(name => extractFunction(html, name)).join('\n')
    + '\n' + names.map(name => `this.${name} = ${name};`).join('\n');
  vm.runInContext(source, sandbox);
  return sandbox;
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('circle geometry uses the centre-to-edge pixel distance as radius', () => {
  const { getCircleGeometry } = loadFunctions(['getCircleGeometry']);

  assert.deepEqual(
    plain(getCircleGeometry(10, 20, 13, 24)),
    { cx: 10, cy: 20, edgeX: 13, edgeY: 24, radius: 5 }
  );
});

test('circle hit classification distinguishes resize handle and whole circle', () => {
  const { getCircleGeometry, getCircleHitPart } = loadFunctions([
    'getCircleGeometry',
    'getCircleHitPart'
  ]);
  const geometry = getCircleGeometry(100, 100, 120, 100);

  assert.equal(getCircleHitPart(120, 100, geometry, 8, 10), 'radius');
  assert.equal(getCircleHitPart(100, 100, geometry, 8, 10), 'whole');
  assert.equal(getCircleHitPart(100, 120, geometry, 8, 10), 'whole');
  assert.equal(getCircleHitPart(108, 108, geometry, 8, 10), null);
});

test('circle toolbar exposes persistent palette, width, style, and shortcut settings', () => {
  assert.match(html, /\bid="tool-circle"/);
  assert.match(html, /\bid="cfg-circle"/);
  assert.match(html, /\bid="popup-circle"/);
  assert.match(html, /\bid="circle-color"[^>]*\bvalue="#2196f3"/);
  assert.match(html, /\bid="circle-width"/);
  assert.match(html, /\bid="circle-style"/);
  for (const color of ['#2196f3', '#ff6b35', '#f5c842']) {
    assert.match(html, new RegExp(`circle-color-swatch[^>]+data-color="${color}"`));
  }
  assert.match(html, /circle:\{color:'#2196f3',width:2,style:'solid'\}/);
  assert.match(html, /function syncCircleColorUI\(/);
  assert.match(html, /\['arrow','circle','hline','line','ray','seg','text','note'\]/);
  assert.match(html, /const TOOLS=\['pan','arrow','circle','hline','line','ray','seg','text','note','measure'\]/);
  assert.match(html, /'c':'circle'/);
});

test('circle placement, rendering, hit testing, and editing use the two anchors', () => {
  const preview = extractFunction(html, 'drawPreview');
  const drawOne = extractFunction(html, 'drawOne');
  const setupEvents = extractFunction(html, 'setupChartEvents');
  const hitPart = extractFunction(html, 'getHitPart');
  const applyDrag = extractFunction(html, 'applyDrag');

  assert.match(html, /const MIN_CIRCLE_RADIUS=4;/);
  assert.match(preview, /drawTool==='circle'/);
  assert.match(preview, /getCircleGeometry\(x1,y1,previewMouseX,previewMouseY\)/);
  assert.match(preview, /ctx2\.arc\(geometry\.cx,geometry\.cy,geometry\.radius,0,Math\.PI\*2\)/);

  assert.match(drawOne, /else if\(d\.type==='circle'\)/);
  assert.match(drawOne, /getCircleGeometry\(x1,y1,x2,y2\)/);
  assert.match(drawOne, /ctx2\.arc\(geometry\.cx,geometry\.cy,geometry\.radius,0,Math\.PI\*2\)/);
  assert.match(drawOne, /if\(sel\)\{/);

  assert.match(setupEvents, /drawTool==='circle'/);
  assert.match(setupEvents, /geometry\.radius<MIN_CIRCLE_RADIUS/);
  assert.match(
    setupEvents,
    /type:'circle',p1:pendingP1,p2:\{price,time\},color:drawColor,width:drawWidth,style:drawLineStyle/
  );

  assert.match(hitPart, /if\(d\.type==='circle'\)/);
  assert.match(hitPart, /_drawingExceedsCutoff\(d,cutoff\)/);
  assert.match(hitPart, /getCircleHitPart\(mx,my,geometry,THRESH,ENDPOINT_THRESH\)/);

  assert.match(applyDrag, /if\(part==='radius'\)/);
  assert.match(applyDrag, /d\.p2=\{\.\.\.d\.p2,price:toPrice\(o\.p2\.price,dy\),time:toTime\(o\.p2\.time,dx\)\}/);
  assert.match(applyDrag, /d\.p1=\{\.\.\.d\.p1,price:toPrice\(o\.p1\.price,dy\),time:toTime\(o\.p1\.time,dx\)\}/);
});
