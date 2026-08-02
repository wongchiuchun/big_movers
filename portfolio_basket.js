(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.PortSimBasket = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function seedWords(seed) {
    var value = String(seed == null ? '' : seed);
    var hash = 1779033703 ^ value.length;
    for (var index = 0; index < value.length; index++) {
      hash = Math.imul(hash ^ value.charCodeAt(index), 3432918353);
      hash = (hash << 13) | (hash >>> 19);
    }
    return function () {
      hash = Math.imul(hash ^ (hash >>> 16), 2246822507);
      hash = Math.imul(hash ^ (hash >>> 13), 3266489909);
      return (hash ^= hash >>> 16) >>> 0;
    };
  }

  function createRng(seed) {
    var nextSeed = seedWords(seed);
    var state = nextSeed();
    return function () {
      state += 0x6d2b79f5;
      var value = state;
      value = Math.imul(value ^ (value >>> 15), value | 1);
      value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
      return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
  }

  function asRng(seedOrRng) {
    return typeof seedOrRng === 'function'
      ? seedOrRng
      : createRng(seedOrRng);
  }

  function clampSize(size) {
    var parsed = Number(size);
    if (!Number.isFinite(parsed)) parsed = 1;
    return Math.max(1, Math.min(10, Math.trunc(parsed)));
  }

  function validCompositions(size) {
    var basketSize = clampSize(size);
    if (basketSize === 1) {
      return [{ mover: 1, anchor: 0, noise: 0 }];
    }
    if (basketSize === 2) {
      return [{ mover: 1, anchor: 1, noise: 0 }];
    }

    var compositions = [];
    var minMovers = Math.ceil(0.25 * basketSize);
    var maxMovers = Math.floor(0.50 * basketSize);
    var minAnchors = Math.max(1, Math.round(0.20 * basketSize));
    var maxAnchors = Math.min(
      3,
      Math.max(1, Math.floor(0.40 * basketSize))
    );

    for (var movers = minMovers; movers <= maxMovers; movers++) {
      for (var anchors = minAnchors; anchors <= maxAnchors; anchors++) {
        var noise = basketSize - movers - anchors;
        if (noise >= 1) {
          compositions.push({
            mover: movers,
            anchor: anchors,
            noise: noise
          });
        }
      }
    }
    return compositions;
  }

  function compositionWeight(composition, compositions) {
    if (compositions.length <= 1) return 1;
    var maxMovers = Math.max.apply(
      null,
      compositions.map(function (candidate) {
        return candidate.mover;
      })
    );
    var minAnchors = Math.min.apply(
      null,
      compositions.map(function (candidate) {
        return candidate.anchor;
      })
    );
    var boundary =
      composition.mover === maxMovers || composition.anchor === minAnchors;
    return boundary ? 1 : 2;
  }

  function orderedCompositions(size, seedOrRng) {
    var rng = asRng(seedOrRng);
    var remaining = validCompositions(size).slice();
    var ordered = [];

    while (remaining.length) {
      var totalWeight = remaining.reduce(function (total, composition) {
        return total + compositionWeight(composition, validCompositions(size));
      }, 0);
      var target = rng() * totalWeight;
      var selectedIndex = remaining.length - 1;

      for (var index = 0; index < remaining.length; index++) {
        target -= compositionWeight(remaining[index], validCompositions(size));
        if (target < 0) {
          selectedIndex = index;
          break;
        }
      }
      ordered.push(remaining.splice(selectedIndex, 1)[0]);
    }
    return ordered;
  }

  function normalizedSymbol(row) {
    if (!row || row.symbol == null) return '';
    return String(row.symbol).trim().toUpperCase();
  }

  function uniqueCandidates(rows) {
    var seen = new Set();
    var unique = [];
    (Array.isArray(rows) ? rows : []).forEach(function (row) {
      var symbol = normalizedSymbol(row);
      if (!symbol || seen.has(symbol)) return;
      seen.add(symbol);
      unique.push(Object.assign({}, row, { symbol: symbol }));
    });
    return unique;
  }

  function shuffle(rows, rng) {
    var shuffled = rows.slice();
    for (var index = shuffled.length - 1; index > 0; index--) {
      var swapIndex = Math.floor(rng() * (index + 1));
      var held = shuffled[index];
      shuffled[index] = shuffled[swapIndex];
      shuffled[swapIndex] = held;
    }
    return shuffled;
  }

  function chooseAnchors(candidates, count, rng) {
    if (count === 0) return [];

    var growth = shuffle(
      candidates.filter(function (row) {
        return String(row.group || '').toLowerCase() === 'growth';
      }),
      rng
    );
    var broad = shuffle(
      candidates.filter(function (row) {
        return String(row.group || '').toLowerCase() === 'broad';
      }),
      rng
    );

    if (count === 1) {
      var preferGrowth = rng() < 0.5;
      var preferred = preferGrowth ? growth : broad;
      var fallback = preferGrowth ? broad : growth;
      if (preferred.length) return [preferred[0]];
      return fallback.length ? [fallback[0]] : null;
    }

    if (count === 2) {
      if (!growth.length || !broad.length) return null;
      return [growth[0], broad[0]];
    }

    if (count === 3) {
      var growthFirst = rng() < 0.5;
      var splits = growthFirst
        ? [
            { growth: 2, broad: 1 },
            { growth: 1, broad: 2 }
          ]
        : [
            { growth: 1, broad: 2 },
            { growth: 2, broad: 1 }
          ];

      for (var index = 0; index < splits.length; index++) {
        var split = splits[index];
        if (
          growth.length >= split.growth &&
          broad.length >= split.broad
        ) {
          return growth
            .slice(0, split.growth)
            .concat(broad.slice(0, split.broad));
        }
      }
    }
    return null;
  }

  function canFillAnchorSplit(growthCount, broadCount, needed) {
    if (needed === 0) return true;
    if (needed === 1) return growthCount + broadCount >= 1;
    if (needed === 2) return growthCount >= 1 && broadCount >= 1;
    if (needed === 3) {
      return (
        (growthCount >= 2 && broadCount >= 1) ||
        (growthCount >= 1 && broadCount >= 2)
      );
    }
    return false;
  }

  function findFillableMovers(
    moverPool,
    moverCount,
    anchorPool,
    anchorCount,
    noisePool,
    noiseCount
  ) {
    var anchorGroups = new Map();
    var growthCount = 0;
    var broadCount = 0;
    anchorPool.forEach(function (row) {
      var group = String(row.group || '').toLowerCase();
      if (group === 'growth' || group === 'broad') {
        anchorGroups.set(row.symbol, group);
        if (group === 'growth') growthCount++;
        else broadCount++;
      }
    });
    var noiseSymbols = new Set(
      noisePool.map(function (row) {
        return row.symbol;
      })
    );
    var failedStates = new Set();

    function visit(index, selected, availableGrowth, availableBroad, availableNoise) {
      var moversStillNeeded = moverCount - selected.length;
      // Every later choice can only reduce role capacity, so these checks safely
      // prune branches before enumerating another mover subset.
      if (
        !canFillAnchorSplit(
          availableGrowth,
          availableBroad,
          anchorCount
        )
      ) {
        return null;
      }
      if (availableNoise < noiseCount) return null;
      if (moversStillNeeded === 0) return selected.slice();
      if (moverPool.length - index < moversStillNeeded) return null;

      var stateKey = [
        index,
        selected.length,
        availableGrowth,
        availableBroad,
        availableNoise
      ].join('|');
      if (failedStates.has(stateKey)) return null;

      var mover = moverPool[index];
      var group = anchorGroups.get(mover.symbol);
      selected.push(mover);
      var included = visit(
        index + 1,
        selected,
        availableGrowth - (group === 'growth' ? 1 : 0),
        availableBroad - (group === 'broad' ? 1 : 0),
        availableNoise - (noiseSymbols.has(mover.symbol) ? 1 : 0)
      );
      selected.pop();
      if (included) return included;

      var skipped = visit(
        index + 1,
        selected,
        availableGrowth,
        availableBroad,
        availableNoise
      );
      if (skipped) return skipped;

      failedStates.add(stateKey);
      return null;
    }

    if (
      !canFillAnchorSplit(growthCount, broadCount, anchorCount) ||
      noisePool.length < noiseCount
    ) {
      return null;
    }
    return visit(0, [], growthCount, broadCount, noisePool.length);
  }

  function selectRoles(options) {
    options = options || {};
    var composition = options.composition;
    if (
      !composition ||
      !Number.isInteger(composition.mover) ||
      !Number.isInteger(composition.anchor) ||
      !Number.isInteger(composition.noise)
    ) {
      return null;
    }

    var rng = asRng(options.rng || options.seed);
    var selected = [];
    var roles = {};
    var selectedSymbols = new Set();

    var moverPool = shuffle(uniqueCandidates(options.movers), rng);
    var anchorPool = uniqueCandidates(options.anchors);
    var manifestInput =
      options.manifestSymbols instanceof Set
        ? Array.from(options.manifestSymbols)
        : Array.isArray(options.manifestSymbols)
          ? options.manifestSymbols
          : [];
    var manifestSymbols = new Set(
      manifestInput.map(function (symbol) {
        return String(symbol).trim().toUpperCase();
      })
    );
    anchorPool.forEach(function (row) {
      manifestSymbols.add(row.symbol);
    });
    var availableNoise = uniqueCandidates(options.noise).filter(function (row) {
      return !manifestSymbols.has(row.symbol);
    });

    if (moverPool.length < composition.mover) return null;
    var movers = findFillableMovers(
      moverPool,
      composition.mover,
      anchorPool,
      composition.anchor,
      availableNoise,
      composition.noise
    );
    if (!movers) return null;
    movers.forEach(function (row) {
      selected.push(row);
      selectedSymbols.add(row.symbol);
      roles[row.symbol] = 'mover';
    });

    var remainingAnchors = anchorPool.filter(function (row) {
      return !selectedSymbols.has(row.symbol);
    });
    var anchors = chooseAnchors(remainingAnchors, composition.anchor, rng);
    if (!anchors || anchors.length !== composition.anchor) return null;
    anchors.forEach(function (row) {
      selected.push(row);
      selectedSymbols.add(row.symbol);
      roles[row.symbol] = 'anchor';
    });

    var noisePool = shuffle(
      availableNoise.filter(function (row) {
        return !selectedSymbols.has(row.symbol);
      }),
      rng
    );
    if (noisePool.length < composition.noise) return null;
    var noise = noisePool.slice(0, composition.noise);
    noise.forEach(function (row) {
      selected.push(row);
      selectedSymbols.add(row.symbol);
      roles[row.symbol] = 'noise';
    });

    if (
      selected.length !==
        composition.mover + composition.anchor + composition.noise ||
      selectedSymbols.size !== selected.length
    ) {
      return null;
    }

    return {
      rows: shuffle(selected, rng),
      roles: roles,
      composition: {
        mover: composition.mover,
        anchor: composition.anchor,
        noise: composition.noise
      }
    };
  }

  function selectBasket(options) {
    options = options || {};
    var size = clampSize(options.size);
    var rng = createRng(options.seed);
    var compositions = orderedCompositions(size, rng);

    for (var index = 0; index < compositions.length; index++) {
      var result = selectRoles(
        Object.assign({}, options, {
          composition: compositions[index],
          rng: rng
        })
      );
      if (result) return result;
    }
    return null;
  }

  function isAnchorEligible(anchor, windowStart) {
    if (!anchor || typeof windowStart !== 'string') return false;
    return (Array.isArray(anchor.eligibility) ? anchor.eligibility : []).some(
      function (interval) {
        if (!interval || typeof interval.from !== 'string') return false;
        return (
          interval.from <= windowStart &&
          (interval.to == null || windowStart <= interval.to)
        );
      }
    );
  }

  function barTime(bar) {
    if (!bar) return '';
    var value = bar.time != null ? bar.time : bar.date;
    return typeof value === 'string' ? value.slice(0, 10) : '';
  }

  function shiftCalendarMonths(dateText, monthsBack) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateText || '');
    if (!match) return null;
    var year = Number(match[1]);
    var monthIndex = Number(match[2]) - 1;
    var day = Number(match[3]);
    var targetMonthIndex = monthIndex - monthsBack;
    var targetYear = year + Math.floor(targetMonthIndex / 12);
    var normalizedMonth = ((targetMonthIndex % 12) + 12) % 12;
    var lastDay = new Date(
      Date.UTC(targetYear, normalizedMonth + 1, 0)
    ).getUTCDate();
    var targetDay = Math.min(day, lastDay);
    return (
      String(targetYear).padStart(4, '0') +
      '-' +
      String(normalizedMonth + 1).padStart(2, '0') +
      '-' +
      String(targetDay).padStart(2, '0')
    );
  }

  function hasWindowCoverage(bars, windowStart, windowEnd, contextMonths) {
    var months =
      contextMonths == null ? 4 : Math.max(0, Math.trunc(contextMonths));
    var requiredStart = shiftCalendarMonths(windowStart, months);
    if (!requiredStart || typeof windowEnd !== 'string') return false;

    var times = (Array.isArray(bars) ? bars : [])
      .map(barTime)
      .filter(Boolean)
      .sort();
    if (!times.length) return false;
    return times[0] <= requiredStart && times[times.length - 1] >= windowEnd;
  }

  function median(values) {
    var ordered = values.slice().sort(function (left, right) {
      return left - right;
    });
    var middle = Math.floor(ordered.length / 2);
    return ordered.length % 2
      ? ordered[middle]
      : (ordered[middle - 1] + ordered[middle]) / 2;
  }

  function noiseLiquidity(bars, windowStart, options) {
    options = options || {};
    var minBars = options.minBars == null ? 20 : options.minBars;
    var maxBars = options.maxBars == null ? 60 : options.maxBars;
    var minClose = options.minClose == null ? 5 : options.minClose;
    var minMedianDollarVolume =
      options.minMedianDollarVolume == null
        ? 20000000
        : options.minMedianDollarVolume;

    var preWindow = (Array.isArray(bars) ? bars : [])
      .filter(function (bar) {
        var time = barTime(bar);
        var close = Number(bar && bar.close);
        var volume = Number(bar && bar.volume);
        return (
          time &&
          time < windowStart &&
          Number.isFinite(close) &&
          close >= 0 &&
          Number.isFinite(volume) &&
          volume >= 0
        );
      })
      .sort(function (left, right) {
        return barTime(left).localeCompare(barTime(right));
      })
      .slice(-maxBars);

    if (preWindow.length < minBars) return false;
    var finalClose = Number(preWindow[preWindow.length - 1].close);
    if (finalClose < minClose) return false;
    var dollarVolumes = preWindow.map(function (bar) {
      return Number(bar.close) * Number(bar.volume);
    });
    return median(dollarVolumes) >= minMedianDollarVolume;
  }

  function normalizeRole(role) {
    return /^(mover|anchor|noise)$/.test(String(role || ''))
      ? String(role)
      : null;
  }

  function normalizeSymbols(symbols) {
    return (Array.isArray(symbols) ? symbols : []).map(function (item) {
      return normalizedSymbol(typeof item === 'string' ? { symbol: item } : item);
    }).filter(Boolean);
  }

  function normalizeRoles(roles) {
    var out = {};
    if (!roles || typeof roles !== 'object') return out;
    Object.keys(roles).forEach(function (symbol) {
      var normalized = normalizedSymbol({ symbol: symbol });
      var role = normalizeRole(roles[symbol]);
      if (normalized && role) out[normalized] = role;
    });
    return out;
  }

  function cloneObject(value) {
    return value && typeof value === 'object'
      ? JSON.parse(JSON.stringify(value))
      : value;
  }

  function createGeneration(options) {
    options = options || {};
    var composition = options.composition || {};
    return {
      version: 2,
      mode: options.mode === 'same-year' ? 'same-year' : 'balanced',
      seed: options.seed == null ? null : String(options.seed),
      composition: {
        mover: Math.max(0, Math.trunc(Number(composition.mover) || 0)),
        anchor: Math.max(0, Math.trunc(Number(composition.anchor) || 0)),
        noise: Math.max(0, Math.trunc(Number(composition.noise) || 0))
      },
      roles: normalizeRoles(options.roles),
      modified: false,
      origin: {
        startDate: String(options.startDate || ''),
        endDate: String(options.endDate || ''),
        symbols: normalizeSymbols(options.symbols)
      }
    };
  }

  function reconcileGeneration(generation, current) {
    if (!generation || typeof generation !== 'object') return null;
    var next = cloneObject(generation);
    if (!next.origin || typeof next.origin !== 'object') return next;
    current = current || {};
    var originSymbols = normalizeSymbols(next.origin.symbols);
    var currentSymbols = normalizeSymbols(current.symbols);
    var sameSymbols = originSymbols.length === currentSymbols.length &&
      originSymbols.every(function (symbol, index) {
        return symbol === currentSymbols[index];
      });
    next.modified = !(
      String(next.origin.startDate || '') === String(current.startDate || '') &&
      String(next.origin.endDate || '') === String(current.endDate || '') &&
      sameSymbols
    );
    return next;
  }

  function resolveRole(generation, symbol, explicitRole) {
    var explicit = normalizeRole(explicitRole);
    if (explicit) return explicit;
    var normalized = normalizedSymbol({ symbol: symbol });
    var roles = generation && normalizeRoles(generation.roles);
    return normalized && roles && roles[normalized] ? roles[normalized] : 'unknown';
  }

  function countCurrentRoles(generation, entries) {
    var counts = { mover: 0, anchor: 0, noise: 0, unknown: 0 };
    (Array.isArray(entries) ? entries : []).forEach(function (entry) {
      var symbol = typeof entry === 'string' ? entry : entry && entry.symbol;
      var explicitRole = entry && typeof entry === 'object' ? entry.role : null;
      var role = resolveRole(generation, symbol, explicitRole);
      counts[role] += 1;
    });
    return counts;
  }

  return {
    createRng: createRng,
    validCompositions: validCompositions,
    orderedCompositions: orderedCompositions,
    selectBasket: selectBasket,
    selectRoles: selectRoles,
    isAnchorEligible: isAnchorEligible,
    hasWindowCoverage: hasWindowCoverage,
    noiseLiquidity: noiseLiquidity,
    createGeneration: createGeneration,
    reconcileGeneration: reconcileGeneration,
    resolveRole: resolveRole,
    countCurrentRoles: countCurrentRoles
  };
});
