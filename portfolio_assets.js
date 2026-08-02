(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.PortSimAssets = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var INDEX_METADATA = [
    {
      key: 'index:SPX',
      symbol: 'SPX',
      dataSymbol: 'SPY',
      cacheSymbol: 'SPX',
      assetType: 'index'
    },
    {
      key: 'index:NDQ',
      symbol: 'NDQ',
      dataSymbol: 'NDQ',
      cacheSymbol: 'NDQ',
      assetType: 'index'
    }
  ];
  var RESERVED_INDEX_ALIASES = new Set(['SPX', 'SPY', 'NDQ', 'NDX', 'QQQ']);

  function normalizedSymbol(symbol) {
    return symbol == null ? '' : String(symbol).trim().toUpperCase();
  }

  function indexDefinitions() {
    return INDEX_METADATA.map(function (definition) {
      return Object.assign({}, definition);
    });
  }

  function isReservedIndexAlias(symbol) {
    return RESERVED_INDEX_ALIASES.has(normalizedSymbol(symbol));
  }

  function stockKey(symbol) {
    return 'stock:' + normalizedSymbol(symbol);
  }

  function isIndexEntry(entry) {
    if (!entry || typeof entry !== 'object') return false;
    if (String(entry.assetType || '').toLowerCase() === 'index') return true;
    return INDEX_METADATA.some(function (definition) {
      return entry.key === definition.key;
    });
  }

  function entryKey(entry) {
    if (!entry || typeof entry !== 'object') return '';
    if (typeof entry.key === 'string' && entry.key.trim()) return entry.key.trim();
    if (isIndexEntry(entry)) {
      var indexSymbol = normalizedSymbol(entry.symbol);
      return 'index:' + indexSymbol;
    }
    return stockKey(entry.symbol);
  }

  function entriesFrom(state, property) {
    var entries = state && Array.isArray(state[property]) ? state[property] : [];
    return entries.filter(function (entry) {
      return entry != null;
    });
  }

  function liveEntries(state) {
    return entriesFrom(state, 'basket').concat(entriesFrom(state, 'indexEntries'));
  }

  function allTradeEntries(state) {
    var seen = new Set();
    return liveEntries(state)
      .concat(entriesFrom(state, 'retiredEntries'))
      .filter(function (entry) {
        if (seen.has(entry)) return false;
        seen.add(entry);
        return true;
      });
  }

  return {
    indexDefinitions: indexDefinitions,
    isReservedIndexAlias: isReservedIndexAlias,
    stockKey: stockKey,
    entryKey: entryKey,
    liveEntries: liveEntries,
    allTradeEntries: allTradeEntries,
    isIndexEntry: isIndexEntry
  };
});
