const assert = require('node:assert/strict');
const test = require('node:test');

const Basket = require('../portfolio_basket.cjs');

function key(composition) {
  return `${composition.mover}/${composition.anchor}/${composition.noise}`;
}

function symbols(prefix, count, extra = {}) {
  return Array.from({ length: count }, (_, index) => ({
    symbol: `${prefix}${index + 1}`,
    ...extra
  }));
}

test('valid compositions obey the reviewed constraints for sizes 1-10', () => {
  for (let size = 1; size <= 10; size++) {
    const compositions = Basket.validCompositions(size);
    assert.ok(compositions.length > 0, `size ${size} has no compositions`);

    for (const composition of compositions) {
      assert.equal(
        composition.mover + composition.anchor + composition.noise,
        size
      );
      if (size === 1) {
        assert.deepEqual(composition, { mover: 1, anchor: 0, noise: 0 });
      } else if (size === 2) {
        assert.deepEqual(composition, { mover: 1, anchor: 1, noise: 0 });
      } else {
        assert.ok(composition.mover >= Math.ceil(0.25 * size));
        assert.ok(composition.mover <= Math.floor(0.50 * size));
        assert.ok(composition.anchor >= Math.max(1, Math.round(0.20 * size)));
        assert.ok(
          composition.anchor <= Math.min(3, Math.max(1, Math.floor(0.40 * size)))
        );
        assert.ok(composition.noise >= 1);
      }
    }
  }

  assert.deepEqual(
    Basket.validCompositions(6).map(key).sort(),
    ['2/1/3', '2/2/2', '3/1/2', '3/2/1'].sort()
  );
});

test('valid compositions exactly match the reviewed triples for every size', () => {
  const expected = {
    1: ['1/0/0'],
    2: ['1/1/0'],
    3: ['1/1/1'],
    4: ['1/1/2', '2/1/1'],
    5: ['2/1/2', '2/2/1'],
    6: ['2/1/3', '2/2/2', '3/1/2', '3/2/1'],
    7: ['2/1/4', '2/2/3', '3/1/3', '3/2/2'],
    8: ['2/2/4', '2/3/3', '3/2/3', '3/3/2', '4/2/2', '4/3/1'],
    9: ['3/2/4', '3/3/3', '4/2/3', '4/3/2'],
    10: ['3/2/5', '3/3/4', '4/2/4', '4/3/3', '5/2/3', '5/3/2']
  };

  for (let size = 1; size <= 10; size++) {
    assert.deepEqual(Basket.validCompositions(size).map(key), expected[size]);
  }
});

test('all valid compositions are reachable across many seeds', () => {
  for (let size = 1; size <= 10; size++) {
    const expected = new Set(Basket.validCompositions(size).map(key));
    const reached = new Set();
    for (let seed = 0; seed < 5000 && reached.size < expected.size; seed++) {
      reached.add(key(Basket.orderedCompositions(size, seed)[0]));
    }
    assert.deepEqual(reached, expected, `not every size-${size} triple was reachable`);
  }
});

test('balanced compositions receive twice the first-choice weight of boundaries', () => {
  let balanced = 0;
  let boundary = 0;
  for (let seed = 0; seed < 12000; seed++) {
    const first = Basket.orderedCompositions(6, seed)[0];
    if (key(first) === '2/2/2') balanced++;
    else boundary++;
  }

  const balancedShare = balanced / (balanced + boundary);
  assert.ok(
    balancedShare > 0.35 && balancedShare < 0.45,
    `expected roughly 2/(2+1+1+1), got ${balancedShare}`
  );
});

test('one seed reproduces composition selection and final card order', () => {
  const options = {
    size: 6,
    seed: 'reproducible-run',
    movers: symbols('M', 5),
    anchors: [
      ...symbols('G', 4, { group: 'growth' }),
      ...symbols('B', 4, { group: 'broad' })
    ],
    noise: symbols('N', 6),
    manifestSymbols: ['G1', 'G2', 'G3', 'G4', 'B1', 'B2', 'B3', 'B4']
  };

  const first = Basket.selectBasket(options);
  const second = Basket.selectBasket(options);
  assert.deepEqual(second, first);
});

test('basket selection tries every valid triple against full role constraints', () => {
  assert.notDeepEqual(
    Basket.orderedCompositions(6, 'try-the-whole-window')[0],
    { mover: 3, anchor: 2, noise: 1 },
    'the test seed must make at least one unfillable triple run first'
  );
  const result = Basket.selectBasket({
    size: 6,
    seed: 'try-the-whole-window',
    movers: symbols('M', 3),
    anchors: [
      { symbol: 'G1', group: 'growth' },
      { symbol: 'B1', group: 'broad' }
    ],
    noise: symbols('N', 1),
    manifestSymbols: ['G1', 'B1']
  });

  assert.ok(result);
  assert.deepEqual(result.composition, { mover: 3, anchor: 2, noise: 1 });
  assert.equal(result.rows.length, 6);
});

test('basket selection reaches a fillable composition even when it is last in the seeded order', () => {
  const target = '3/2/1';
  let lastSeed = null;
  for (let seed = 0; seed < 10000; seed++) {
    const order = Basket.orderedCompositions(6, seed).map(key);
    if (order[order.length - 1] === target) {
      lastSeed = seed;
      break;
    }
  }
  assert.notEqual(lastSeed, null, 'expected to find a seed with the target last');

  const result = Basket.selectBasket({
    size: 6,
    seed: lastSeed,
    movers: symbols('M', 3),
    anchors: [
      { symbol: 'G1', group: 'growth' },
      { symbol: 'B1', group: 'broad' }
    ],
    noise: symbols('N', 1),
    manifestSymbols: ['G1', 'B1']
  });

  assert.ok(result);
  assert.equal(key(result.composition), target);
});

test('mover selection backtracks when an overlap would falsely exhaust anchors', () => {
  for (let seed = 0; seed < 100; seed++) {
    const result = Basket.selectRoles({
      composition: { mover: 1, anchor: 1, noise: 1 },
      seed,
      movers: [{ symbol: 'DUAL' }, { symbol: 'M2' }],
      anchors: [{ symbol: 'DUAL', group: 'growth' }],
      noise: [{ symbol: 'N1' }],
      manifestSymbols: ['DUAL']
    });

    assert.ok(result, `seed ${seed} produced a false capacity failure`);
    assert.equal(result.roles.M2, 'mover');
    assert.equal(result.roles.DUAL, 'anchor');
    assert.equal(result.roles.N1, 'noise');
  }
});

test('mover takes precedence over anchor for overlapping symbols', () => {
  const result = Basket.selectRoles({
    composition: { mover: 1, anchor: 2, noise: 1 },
    seed: 'overlap',
    movers: [{ symbol: 'DUAL' }],
    anchors: [
      { symbol: 'DUAL', group: 'growth' },
      { symbol: 'G2', group: 'growth' },
      { symbol: 'B1', group: 'broad' }
    ],
    noise: [{ symbol: 'N1' }],
    manifestSymbols: ['DUAL', 'G2', 'B1']
  });

  assert.ok(result);
  assert.equal(result.roles.DUAL, 'mover');
  assert.equal(result.rows.filter(row => row.symbol === 'DUAL').length, 1);
  assert.equal(Object.values(result.roles).filter(role => role === 'anchor').length, 2);
});

test('three anchors try the opposite 2:1 split before failing', () => {
  const randomValues = [0.75, 0.1];
  const result = Basket.selectRoles({
    composition: { mover: 1, anchor: 3, noise: 1 },
    rng: () => randomValues.shift() ?? 0,
    movers: [{ symbol: 'M1' }],
    anchors: [
      { symbol: 'G1', group: 'growth' },
      { symbol: 'B1', group: 'broad' },
      { symbol: 'B2', group: 'broad' }
    ],
    noise: [{ symbol: 'N1' }],
    manifestSymbols: ['G1', 'B1', 'B2']
  });

  assert.ok(result);
  const selectedAnchors = result.rows.filter(
    row => result.roles[row.symbol] === 'anchor'
  );
  assert.equal(selectedAnchors.filter(row => row.group === 'growth').length, 1);
  assert.equal(selectedAnchors.filter(row => row.group === 'broad').length, 2);
});

test('one anchor falls back only when the randomly preferred group is empty', () => {
  const result = Basket.selectRoles({
    composition: { mover: 1, anchor: 1, noise: 0 },
    rng: () => 0.1,
    movers: [{ symbol: 'M1' }],
    anchors: [{ symbol: 'B1', group: 'broad' }],
    manifestSymbols: ['B1']
  });

  assert.ok(result);
  assert.equal(result.roles.B1, 'anchor');
});

test('two anchors require one candidate from each group', () => {
  const base = {
    composition: { mover: 1, anchor: 2, noise: 0 },
    seed: 'two-groups',
    movers: [{ symbol: 'M1' }],
    manifestSymbols: ['G1', 'G2', 'B1']
  };
  assert.equal(
    Basket.selectRoles({
      ...base,
      anchors: [
        { symbol: 'G1', group: 'growth' },
        { symbol: 'G2', group: 'growth' }
      ]
    }),
    null
  );

  const result = Basket.selectRoles({
    ...base,
    anchors: [
      { symbol: 'G1', group: 'growth' },
      { symbol: 'B1', group: 'broad' }
    ]
  });
  assert.ok(result);
  assert.equal(result.roles.G1, 'anchor');
  assert.equal(result.roles.B1, 'anchor');
});

test('selection deduplicates candidates, excludes all manifest anchors from noise, and never returns partial baskets', () => {
  const options = {
    composition: { mover: 1, anchor: 1, noise: 2 },
    seed: 42,
    movers: [{ symbol: 'M1' }, { symbol: 'M1' }],
    anchors: [{ symbol: 'A1', group: 'growth' }],
    noise: [
      { symbol: 'A1' },
      { symbol: 'HIDDEN_ANCHOR' },
      { symbol: 'N1' },
      { symbol: 'N1' }
    ],
    manifestSymbols: ['A1', 'HIDDEN_ANCHOR']
  };

  assert.equal(Basket.selectRoles(options), null);
});

test('anchor is eligible only when window start is inside an interval', () => {
  const row = {
    eligibility: [
      { from: '2018-01-01', to: '2020-12-31' },
      { from: '2023-01-01', to: null }
    ]
  };
  assert.equal(Basket.isAnchorEligible(row, '2017-12-31'), false);
  assert.equal(Basket.isAnchorEligible(row, '2018-01-01'), true);
  assert.equal(Basket.isAnchorEligible(row, '2020-12-31'), true);
  assert.equal(Basket.isAnchorEligible(row, '2021-06-01'), false);
  assert.equal(Basket.isAnchorEligible(row, '2024-01-01'), true);
});

test('coverage requires four calendar months of context through the window end', () => {
  const enough = [
    { time: '2019-09-15', close: 10 },
    { time: '2020-06-30', close: 12 }
  ];
  assert.equal(
    Basket.hasWindowCoverage(enough, '2020-01-15', '2020-06-30'),
    true
  );
  assert.equal(
    Basket.hasWindowCoverage(enough.slice(1), '2020-01-15', '2020-06-30'),
    false
  );
  assert.equal(
    Basket.hasWindowCoverage(enough, '2020-01-15', '2020-07-01'),
    false
  );
  assert.equal(
    Basket.hasWindowCoverage(
      [
        { time: '2019-09-30', close: 10 },
        { time: '2020-05-31', close: 12 }
      ],
      '2020-01-31',
      '2020-05-31'
    ),
    true,
    'month subtraction clamps to the final day of a shorter month'
  );
});

function liquidBars(count, startDay = 1, close = 10, volume = 3000000) {
  return Array.from({ length: count }, (_, index) => ({
    time: `2020-01-${String(startDay + index).padStart(2, '0')}`,
    close,
    volume
  }));
}

test('noise needs 20 bars, a $5 final close, and $20m median dollar volume', () => {
  const start = '2020-03-01';
  assert.equal(Basket.noiseLiquidity(liquidBars(19), start), false);
  assert.equal(Basket.noiseLiquidity(liquidBars(20, 1, 4.99), start), false);
  assert.equal(Basket.noiseLiquidity(liquidBars(20, 1, 10, 1999999), start), false);
  assert.equal(Basket.noiseLiquidity(liquidBars(20), start), true);

  const exactlyAtThreshold = liquidBars(20, 1, 5, 4000000);
  assert.equal(Basket.noiseLiquidity(exactlyAtThreshold, start), true);
});

test('noise liquidity uses at most the latest 60 pre-window bars', () => {
  const oldIlliquid = Array.from({ length: 20 }, (_, index) => ({
    time: `2019-10-${String(index + 1).padStart(2, '0')}`,
    close: 1,
    volume: 1
  }));
  const recentLiquid = Array.from({ length: 60 }, (_, index) => ({
    time: `2020-01-${String(index + 1).padStart(2, '0')}`,
    close: 10,
    volume: 3000000
  }));
  assert.equal(
    Basket.noiseLiquidity([...oldIlliquid, ...recentLiquid], '2020-04-01'),
    true
  );
});

test('noise liquidity ignores every bar on or after the hidden start', () => {
  const before = liquidBars(20);
  const quietHiddenWindow = [
    { time: '2020-03-01', close: 0.01, volume: 0 },
    { time: '2020-03-02', close: 0.01, volume: 0 }
  ];
  const explosiveHiddenWindow = [
    { time: '2020-03-01', close: 10000, volume: 999999999 },
    { time: '2020-03-02', close: 20000, volume: 999999999 }
  ];

  assert.equal(Basket.noiseLiquidity([...before, ...quietHiddenWindow], '2020-03-01'), true);
  assert.equal(Basket.noiseLiquidity([...before, ...explosiveHiddenWindow], '2020-03-01'), true);
});

test('generation reconciliation preserves roles and marks setup edits modified', () => {
  const generated = Basket.createGeneration({
    mode: 'balanced', seed: 'seed-42',
    composition: { mover: 1, anchor: 1, noise: 1 },
    roles: { move: 'mover', liq: 'anchor', cmp: 'noise' },
    startDate: '2020-01-01', endDate: '2020-06-01',
    symbols: ['move', 'liq', 'cmp']
  });
  assert.equal(generated.version, 2);
  assert.deepEqual(generated.origin.symbols, ['MOVE', 'LIQ', 'CMP']);

  const edited = Basket.reconcileGeneration(generated, {
    startDate: '2020-02-01', endDate: '2020-06-01',
    symbols: ['MOVE', 'LIQ', 'CMP']
  });
  assert.equal(edited.modified, true);
  assert.equal(Basket.resolveRole(edited, 'LIQ', 'unknown'), 'anchor');
  assert.equal(generated.modified, false, 'reconciliation must not mutate the origin object');
});

test('reverting exactly to the origin clears modified while order changes remain modified', () => {
  const generated = Basket.createGeneration({
    mode: 'balanced', seed: 'seed',
    composition: { mover: 1, anchor: 1, noise: 0 },
    roles: { MOVE: 'mover', LIQ: 'anchor' },
    startDate: '2020-01-01', endDate: '2020-06-01',
    symbols: ['MOVE', 'LIQ']
  });
  const reordered = Basket.reconcileGeneration(generated, {
    startDate: '2020-01-01', endDate: '2020-06-01', symbols: ['LIQ', 'MOVE']
  });
  assert.equal(reordered.modified, true);
  const restored = Basket.reconcileGeneration(reordered, {
    startDate: '2020-01-01', endDate: '2020-06-01', symbols: ['MOVE', 'LIQ']
  });
  assert.equal(restored.modified, false);
});

test('current role counts omit removals, restore known symbols, and count additions unknown', () => {
  const generation = Basket.createGeneration({
    mode: 'balanced', seed: 'seed',
    composition: { mover: 1, anchor: 1, noise: 1 },
    roles: { MOVE: 'mover', LIQ: 'anchor', CMP: 'noise' },
    startDate: '2020-01-01', endDate: '2020-06-01',
    symbols: ['MOVE', 'LIQ', 'CMP']
  });
  assert.deepEqual(
    Basket.countCurrentRoles(generation, [
      { symbol: 'move', role: 'unknown' },
      { symbol: 'liq', role: 'unknown' },
      { symbol: 'new', role: 'unknown' }
    ]),
    { mover: 1, anchor: 1, noise: 0, unknown: 1 }
  );
});

test('invalid explicit roles fall back to generation while valid roles win', () => {
  const generation = Basket.createGeneration({
    mode: 'same-year', seed: 'seed', composition: { mover: 1, anchor: 0, noise: 0 },
    roles: { MOVE: 'mover' }, startDate: '2020-01-01', endDate: '2020-06-01',
    symbols: ['MOVE']
  });
  assert.equal(Basket.resolveRole(generation, 'MOVE', 'unknown'), 'mover');
  assert.equal(Basket.resolveRole(generation, 'MOVE', 'invalid'), 'mover');
  assert.equal(Basket.resolveRole(generation, 'MOVE', 'anchor'), 'anchor');
  assert.equal(Basket.resolveRole(generation, 'NEW', 'unknown'), 'unknown');
});

test('legacy version-one generation remains readable without guessed modification', () => {
  const legacy = {
    version: 1, mode: 'balanced', seed: 'old',
    composition: { mover: 1, anchor: 1, noise: 0 },
    roles: { MOVE: 'mover', LIQ: 'anchor' }
  };
  const reconciled = Basket.reconcileGeneration(legacy, {
    startDate: '2020-01-01', endDate: '2020-06-01', symbols: ['MOVE']
  });
  assert.equal(reconciled.modified, undefined);
  assert.equal(Basket.resolveRole(reconciled, 'LIQ', 'unknown'), 'anchor');
});
