(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.PortSimOrders = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var TERMINAL_STATUSES = {
    filled: true,
    cancelled: true,
    invalidated: true,
    expired: true
  };
  // Plain state owned by the module and safe to include in JSON snapshots.
  // Controllers initialize or repair it with reconcile(state, liveEntries).
  var RESERVATION_LEDGER_KEY = '_orderReservationCents';
  var orderSequence = 0;

  function finiteNumber(value) {
    var number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function toCents(value) {
    var number = finiteNumber(value);
    if (number == null) return 0;
    return Math.round(number * 100);
  }

  function fromCents(cents) {
    return cents / 100;
  }

  function money(value) {
    return fromCents(toCents(value));
  }

  function deepClone(value) {
    if (Array.isArray(value)) {
      return value.map(deepClone);
    }
    if (value && typeof value === 'object') {
      var copy = {};
      Object.keys(value).forEach(function (key) {
        copy[key] = deepClone(value[key]);
      });
      return copy;
    }
    return value;
  }

  function cloneOrder(order) {
    return order && typeof order === 'object' ? deepClone(order) : null;
  }

  function mintOrderId() {
    orderSequence += 1;
    var timestamp = Date.now().toString(36);
    var sequence = orderSequence.toString(36);
    return 'portfolio_order_' + timestamp + '_' + sequence;
  }

  function error(message) {
    return { ok: false, error: message };
  }

  function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  function validOrderId(order) {
    var id = order && order.id;
    if (typeof id !== 'string' || !id.trim()) return null;
    if (id === '__proto__' || id === 'prototype' || id === 'constructor') return null;
    return id;
  }

  function readReservationLedger(state) {
    if (!state || typeof state !== 'object') return null;
    var aggregateCents = toCents(state.reservedBuyingPower);
    var ledger = state[RESERVATION_LEDGER_KEY];
    if (ledger == null) return null;
    if (typeof ledger !== 'object' || Array.isArray(ledger)) return null;

    var totalCents = 0;
    var keys = Object.keys(ledger);
    for (var i = 0; i < keys.length; i++) {
      var cents = finiteNumber(ledger[keys[i]]);
      if (cents == null || cents <= 0 || Math.floor(cents) !== cents) return null;
      totalCents += cents;
      if (!Number.isSafeInteger(totalCents)) return null;
    }
    // An aggregate below the owned total is merely an understated cache and
    // the ledger remains conservative.  An aggregate above it implies that
    // ownership is missing, so callers must fail closed until reconcile().
    if (aggregateCents > totalCents) return null;
    return { ledger: ledger, totalCents: totalCents, aggregateCents: aggregateCents };
  }

  function availableBuyingPower(state) {
    if (!state || typeof state !== 'object') return 0;
    var cash = finiteNumber(state.cash);
    var ownership = readReservationLedger(state);
    if (!ownership) return 0;
    return fromCents(toCents(cash == null ? 0 : cash) - ownership.totalCents);
  }

  function workingOrderFrom(entry) {
    var order = entry && entry.pendingOrder;
    return order && order.status === 'working' ? order : null;
  }

  function firstDefined() {
    for (var i = 0; i < arguments.length; i++) {
      if (arguments[i] != null) return arguments[i];
    }
    return null;
  }

  function create(draft, context) {
    // Context supplies controller-owned facts that this domain module cannot
    // derive: { state, entry, eligible, submittedBarIdx, submittedDate }.
    draft = draft && typeof draft === 'object' ? draft : {};
    context = context && typeof context === 'object' ? context : {};

    var kind = draft.kind;
    if (kind !== 'entry' && kind !== 'add') {
      return error('Order kind must be entry or add.');
    }
    if (context.eligible !== true) {
      return error(kind === 'add'
        ? 'This position is not eligible for an add order.'
        : 'This card is not eligible for an entry order.');
    }

    var entry = context.entry || null;
    var entryOrder = entry && entry.pendingOrder;
    if (entryOrder && entryOrder.status === 'working') {
      return error('This card already has a working order.');
    }

    var direction = draft.direction;
    if (direction !== 'long' && direction !== 'short') {
      return error('Order direction must be long or short.');
    }

    var limitPrice = finiteNumber(draft.limitPrice);
    if (limitPrice == null || limitPrice <= 0) {
      return error('Limit price must be a positive finite number.');
    }
    limitPrice = money(limitPrice);
    if (limitPrice <= 0) {
      return error('Limit price must be at least $0.01.');
    }

    var sizeMode = draft.sizeMode == null ? 'shares' : draft.sizeMode;
    if (sizeMode !== 'shares' && sizeMode !== 'dollars') {
      return error('Order size mode must be shares or dollars.');
    }
    var sizeValue = finiteNumber(draft.sizeValue);
    if (sizeValue == null || sizeValue <= 0) {
      return error('Order size must be a positive finite number.');
    }
    var qty = sizeMode === 'dollars'
      ? Math.floor(sizeValue / limitPrice)
      : Math.floor(sizeValue);
    if (!Number.isFinite(qty) || qty <= 0) {
      return error('Order size resolves to zero whole shares.');
    }

    var rawStop = draft.stopPrice;
    var stopPrice = rawStop == null ? null : finiteNumber(rawStop);
    if (kind === 'entry' && (stopPrice == null || stopPrice <= 0)) {
      return error('Entry orders require a positive finite protective stop.');
    }
    if (rawStop != null && (stopPrice == null || stopPrice <= 0)) {
      return error('Stop price must be a positive finite number.');
    }
    if (stopPrice != null) {
      stopPrice = money(stopPrice);
      if (stopPrice <= 0) {
        return error('Stop price must be at least $0.01.');
      }
      if (direction === 'long' && stopPrice >= limitPrice) {
        return error('A long protective stop must be below the limit price.');
      }
      if (direction === 'short' && stopPrice <= limitPrice) {
        return error('A short protective stop must be above the limit price.');
      }
    }

    var submittedBarIdx = context.submittedBarIdx == null
      ? null
      : finiteNumber(context.submittedBarIdx);
    if (submittedBarIdx == null || submittedBarIdx < 0 || Math.floor(submittedBarIdx) !== submittedBarIdx) {
      return error('Submission bar index must be a non-negative integer.');
    }
    var submittedDate = context.submittedDate;
    if (submittedDate == null || String(submittedDate).trim() === '') {
      return error('Submission date is required.');
    }

    var reservedBuyingPower = money(qty * limitPrice);
    if (reservedBuyingPower <= 0) {
      return error('Reserved buying power must be positive.');
    }
    if (!context.state ||
        toCents(availableBuyingPower(context.state)) < toCents(reservedBuyingPower)) {
      return error('Not enough available buying power for this order.');
    }

    var stopTriggerMode = draft.stopTriggerMode == null
      ? 'intraday'
      : draft.stopTriggerMode;
    if (stopTriggerMode !== 'intraday' && stopTriggerMode !== 'close') {
      return error('Stop trigger mode must be intraday or close.');
    }

    var order = {
      id: mintOrderId(),
      kind: kind,
      direction: direction,
      limitPrice: limitPrice,
      qty: qty,
      sizeMode: sizeMode,
      sizeValue: sizeValue,
      reservedBuyingPower: reservedBuyingPower,
      submittedBarIdx: submittedBarIdx,
      submittedDate: submittedDate,
      stopTrail: draft.stopTrail ? deepClone(draft.stopTrail) : null,
      stopTriggerMode: stopTriggerMode,
      allowFillBarStop: draft.allowFillBarStop === true,
      status: 'working'
    };
    if (stopPrice != null) order.stopPrice = stopPrice;
    return { ok: true, order: order };
  }

  function evaluateFill(order, bar, barIdx) {
    if (!order || order.status !== 'working' || !bar) return null;
    var index = finiteNumber(barIdx);
    var submittedIndex = finiteNumber(order.submittedBarIdx);
    if (index == null || submittedIndex == null || index <= submittedIndex) return null;

    var limitPrice = finiteNumber(order.limitPrice);
    if (limitPrice == null || limitPrice <= 0) return null;
    var open = finiteNumber(bar.open);

    if (order.direction === 'long') {
      if (open != null && open > 0 && open <= limitPrice) {
        return { price: money(open), gapImproved: open < limitPrice };
      }
      var low = finiteNumber(bar.low);
      if (low != null && low > 0 && low <= limitPrice) {
        return { price: money(limitPrice), gapImproved: false };
      }
      return null;
    }

    if (order.direction === 'short') {
      if (open != null && open > 0 && open >= limitPrice) {
        return { price: money(open), gapImproved: open > limitPrice };
      }
      var high = finiteNumber(bar.high);
      if (high != null && high > 0 && high >= limitPrice) {
        return { price: money(limitPrice), gapImproved: false };
      }
    }
    return null;
  }

  function canSettle(state, order, fillPrice) {
    if (!state || typeof state !== 'object' ||
        !order || typeof order !== 'object' || order.status !== 'working') {
      return false;
    }
    if (order.direction !== 'long' && order.direction !== 'short') return false;
    var price = finiteNumber(fillPrice);
    var qty = finiteNumber(order.qty);
    if (price == null || price <= 0 || qty == null || qty <= 0) return false;

    var ownership = readReservationLedger(state);
    var orderId = validOrderId(order);
    if (!ownership || !ownership.ledger || !orderId ||
        !hasOwn(ownership.ledger, orderId)) {
      return false;
    }
    var cashCents = toCents(state.cash);
    var orderReservedCents = Math.max(0, toCents(order.reservedBuyingPower));
    var ownedCents = ownership.ledger[orderId];
    if (orderReservedCents <= 0 || ownedCents !== orderReservedCents) return false;
    var otherReservedCents = ownership.totalCents - ownedCents;
    var uncommittedCents = cashCents - otherReservedCents;
    var requiredCents = order.direction === 'short'
      ? orderReservedCents
      : toCents(qty * price);
    return requiredCents > 0 && uncommittedCents >= requiredCents;
  }

  function eventDetails(entry, order, type, details) {
    details = details && typeof details === 'object' ? details : {};
    var event = {};
    Object.keys(details).forEach(function (key) {
      if (key !== 'order') event[key] = deepClone(details[key]);
    });

    event.type = type;
    event.orderId = order && order.id ? order.id : firstDefined(details.orderId, null);
    event.kind = order && order.kind ? order.kind : firstDefined(details.kind, null);
    event.entryKey = entry && entry.entryKey != null ? entry.entryKey : null;
    event.entryInstanceKey = entry && entry.entryInstanceKey != null
      ? entry.entryInstanceKey
      : null;
    event.cardId = firstDefined(event.entryInstanceKey, event.entryKey, null);
    event.symbol = entry && entry.symbol != null ? entry.symbol : null;
    event.displaySymbol = entry && entry.displaySymbol != null
      ? entry.displaySymbol
      : event.symbol;
    event.assetType = entry && entry.assetType != null ? entry.assetType : 'stock';
    event.role = entry && entry.role != null ? entry.role : null;
    event.direction = order && order.direction
      ? order.direction
      : firstDefined(details.direction, null);
    event.qty = order && finiteNumber(order.qty) != null
      ? order.qty
      : firstDefined(details.qty, null);
    event.price = firstDefined(
      details.price,
      details.fillPrice,
      order && order.limitPrice
    );
    event.date = firstDefined(
      details.date,
      details.fillDate,
      order && order.submittedDate
    );
    event.barIdx = firstDefined(
      details.barIdx,
      details.fillBarIdx,
      order && order.submittedBarIdx
    );
    event.reason = firstDefined(details.reason, null);
    return event;
  }

  function recordEvent(entry, type, details) {
    if (!entry || typeof entry !== 'object' || !type) return null;
    if (!Array.isArray(entry.orderEvents)) entry.orderEvents = [];
    var suppliedOrder = details && details.order;
    var order = suppliedOrder && typeof suppliedOrder === 'object'
      ? suppliedOrder
      : entry.pendingOrder;
    var event = eventDetails(entry, order, type, details);
    entry.orderEvents.push(event);
    return event;
  }

  function reserve(state, entry, order) {
    if (!state || typeof state !== 'object' ||
        !entry || typeof entry !== 'object' ||
        !order || typeof order !== 'object' || order.status !== 'working') {
      return null;
    }
    var existing = entry.pendingOrder;
    if (existing && existing.status === 'working') {
      if (existing.id !== order.id) return null;
      var existingOwnership = readReservationLedger(state);
      var existingId = validOrderId(existing);
      var existingCents = Math.max(0, toCents(existing.reservedBuyingPower));
      if (!existingOwnership || !existingOwnership.ledger || !existingId ||
          !hasOwn(existingOwnership.ledger, existingId) ||
          existingOwnership.ledger[existingId] !== existingCents) {
        return null;
      }
      state.reservedBuyingPower = fromCents(existingOwnership.totalCents);
      return existing;
    }

    var ownership = readReservationLedger(state);
    var orderId = validOrderId(order);
    if (!ownership || !orderId) return null;
    var ledger = ownership.ledger || {};
    if (hasOwn(ledger, orderId)) return null;
    var qty = finiteNumber(order.qty);
    var limitPrice = finiteNumber(order.limitPrice);
    if (qty == null || qty <= 0 || Math.floor(qty) !== qty ||
        limitPrice == null || limitPrice <= 0) {
      return null;
    }
    var reservedCents = toCents(qty * limitPrice);
    if (reservedCents <= 0) return null;
    var cashCents = toCents(state.cash);
    if (cashCents - ownership.totalCents < reservedCents) return null;
    order.reservedBuyingPower = fromCents(reservedCents);
    ledger[orderId] = reservedCents;
    state[RESERVATION_LEDGER_KEY] = ledger;
    state.reservedBuyingPower = fromCents(ownership.totalCents + reservedCents);
    entry.pendingOrder = order;

    var alreadyPlaced = Array.isArray(entry.orderEvents) && entry.orderEvents.some(function (event) {
      return event && event.type === 'placed' && event.orderId === order.id;
    });
    if (!alreadyPlaced) recordEvent(entry, 'placed', { order: order });
    return order;
  }

  function transition(state, entry, status, details) {
    if (!state || typeof state !== 'object' ||
        !entry || typeof entry !== 'object' ||
        !TERMINAL_STATUSES[status]) {
      return null;
    }
    var order = workingOrderFrom(entry);
    if (!order) return null;

    var ownership = readReservationLedger(state);
    var orderId = validOrderId(order);
    var reservedCents = Math.max(0, toCents(order.reservedBuyingPower));
    if (!ownership || !ownership.ledger || !orderId || reservedCents <= 0 ||
        !hasOwn(ownership.ledger, orderId) ||
        ownership.ledger[orderId] !== reservedCents) {
      return null;
    }
    delete ownership.ledger[orderId];
    state[RESERVATION_LEDGER_KEY] = ownership.ledger;
    state.reservedBuyingPower = fromCents(ownership.totalCents - reservedCents);
    order.status = status;
    order.completedDate = firstDefined(
      details && details.date,
      details && details.fillDate,
      order.submittedDate
    );
    order.completedBarIdx = firstDefined(
      details && details.barIdx,
      details && details.fillBarIdx,
      null
    );
    if (status === 'filled') {
      order.fillPrice = firstDefined(
        details && details.price,
        details && details.fillPrice,
        order.limitPrice
      );
    }
    return recordEvent(entry, status, Object.assign({}, details || {}, { order: order }));
  }

  function reconcile(state, entries) {
    if (!state || typeof state !== 'object') return 0;
    var totalCents = 0;
    var ledger = {};
    var valid = true;
    var list = Array.isArray(entries) ? entries : [];
    list.forEach(function (entry) {
      var order = workingOrderFrom(entry);
      if (!order) return;
      var orderId = validOrderId(order);
      var qty = finiteNumber(order.qty);
      var limitPrice = finiteNumber(order.limitPrice);
      var reservedCents = qty != null && qty > 0 && Math.floor(qty) === qty &&
          limitPrice != null && limitPrice > 0
        ? toCents(qty * limitPrice)
        : 0;
      if (!orderId || reservedCents <= 0 || hasOwn(ledger, orderId)) {
        valid = false;
        return;
      }
      order.reservedBuyingPower = fromCents(reservedCents);
      ledger[orderId] = reservedCents;
      totalCents += reservedCents;
    });
    if (!valid || !Number.isSafeInteger(totalCents)) {
      state[RESERVATION_LEDGER_KEY] = null;
      state.reservedBuyingPower = fromCents(Math.max(1, toCents(state.reservedBuyingPower)));
      return state.reservedBuyingPower;
    }
    state[RESERVATION_LEDGER_KEY] = ledger;
    state.reservedBuyingPower = fromCents(totalCents);
    return state.reservedBuyingPower;
  }

  return {
    create: create,
    availableBuyingPower: availableBuyingPower,
    evaluateFill: evaluateFill,
    canSettle: canSettle,
    reserve: reserve,
    transition: transition,
    recordEvent: recordEvent,
    reconcile: reconcile,
    cloneOrder: cloneOrder
  };
});
