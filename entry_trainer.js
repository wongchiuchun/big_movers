(function(){
  'use strict';

  const BATCH_VERSION = 1;
  const BATCH_SIZE = 3;
  const MAX_ATTEMPTS = 3;
  const DEFAULT_EQUITY = 300000;
  const MASK_OWNER = 'entry-trainer';
  const COMPARISON_DIAGNOSTIC_LABEL = 'Hindsight MFE R using 5-bar-low stop';
  const REQUIRED_RULES = Object.freeze({
    gainLookback: 63,
    minGain: 0.50,
    emaPeriods: [10, 20],
    contextBars: 85,
    forwardBars: 90
  });

  let wired = false;
  let state = {
    status: 'idle',
    batch: null,
    lastBatch: null,
    runtime: null
  };
  let operationGeneration = 0;
  let activeOperation = null;
  let setupOpener = null;
  let setupFocusTimer = null;

  function beginOperation(){
    if (activeOperation) {
      try { activeOperation.controller.abort(); } catch (error) {}
    }
    const operation = {
      generation: ++operationGeneration,
      controller: new AbortController()
    };
    activeOperation = operation;
    return operation;
  }

  function isCurrentOperation(operation){
    return !!operation && activeOperation === operation && operation.generation === operationGeneration;
  }

  function staleOperationError(){
    const error = new Error('Entry Trainer operation is no longer current');
    error.code = 'ENTRY_TRAINER_STALE_OPERATION';
    return error;
  }

  function assertCurrentOperation(operation){
    if (!isCurrentOperation(operation) || operation.controller.signal.aborted) throw staleOperationError();
  }

  function isStaleOperation(error, operation){
    return !isCurrentOperation(operation)
      || !!(error && error.code === 'ENTRY_TRAINER_STALE_OPERATION')
      || !!(error && error.name === 'AbortError' && operation && operation.controller.signal.aborted);
  }

  function finishOperation(operation){
    if (activeOperation === operation) activeOperation = null;
  }

  function cancelOperations(){
    operationGeneration += 1;
    if (activeOperation) {
      try { activeOperation.controller.abort(); } catch (error) {}
    }
    activeOperation = null;
  }

  function byId(id){ return document.getElementById(id); }

  function clone(value){
    return JSON.parse(JSON.stringify(value));
  }

  function setSetupStatus(message, isError){
    const node = byId('entry-trainer-setup-status');
    if (!node) return;
    node.textContent = message || '';
    node.className = 'fetch-status' + (isError ? ' error' : '');
  }

  function setSetupBusy(busy){
    const start = byId('entry-trainer-start');
    const cancel = byId('entry-trainer-cancel');
    const equity = byId('entry-trainer-equity');
    if (start) {
      start.disabled = !!busy;
      start.textContent = busy ? 'Selecting batch…' : 'Start 3-ticker batch';
    }
    if (cancel) {
      cancel.disabled = false;
      cancel.textContent = busy ? 'Cancel loading' : 'Cancel';
    }
    if (equity) equity.disabled = !!busy;
  }

  function restoreSetupOpener(){
    const opener = setupOpener;
    setupOpener = null;
    if (opener && opener.isConnected && typeof opener.focus === 'function') opener.focus();
  }

  function setSetupOpen(open, options){
    options = options || {};
    const modal = byId('entry-trainer-setup-modal');
    if (!modal) return;
    if (setupFocusTimer) {
      clearTimeout(setupFocusTimer);
      setupFocusTimer = null;
    }
    if (open && !modal.classList.contains('open') && !setupOpener) setupOpener = document.activeElement;
    modal.classList.toggle('open', !!open);
    modal.setAttribute('aria-hidden', open ? 'false' : 'true');
    document.body.classList.toggle('entry-trainer-setup-open', !!open);
    if (open) {
      const focusTarget = options.focusTarget ? byId(options.focusTarget) : byId('entry-trainer-equity');
      setupFocusTimer = setTimeout(function(){
        setupFocusTimer = null;
        if (!modal.classList.contains('open')) return;
        focusTarget?.focus();
        if (focusTarget && typeof focusTarget.select === 'function') focusTarget.select();
      }, 30);
    } else if (options.restoreFocus) {
      restoreSetupOpener();
    }
  }

  function trapSetupFocus(event){
    const modal = byId('entry-trainer-setup-modal');
    if (!modal || !modal.classList.contains('open') || event.key !== 'Tab') return;
    const focusable = Array.from(modal.querySelectorAll('button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      .filter(function(node){ return node.getClientRects().length > 0; });
    if (!focusable.length) {
      event.preventDefault();
      modal.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!modal.contains(document.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function isOtherPlaybackActive(){
    if (window.SimBlind && typeof window.SimBlind.isActive === 'function' && window.SimBlind.isActive()) return true;
    if (window.Sim && window.Sim.Ctrl && typeof window.Sim.Ctrl.isActive === 'function' && window.Sim.Ctrl.isActive()) return true;
    if (window.Sim && window.Sim.Ctrl && typeof window.Sim.Ctrl.isPicking === 'function' && window.Sim.Ctrl.isPicking()) return true;
    if (window.PortSim && window.PortSim.Ctrl && typeof window.PortSim.Ctrl.isActive === 'function' && window.PortSim.Ctrl.isActive()) return true;
    const quiz = byId('quiz-panel');
    return !!(quiz && quiz.style.display !== 'none');
  }

  function normalizeCandidate(raw){
    const symbol = String(raw && raw.symbol || '').trim().toUpperCase();
    const qualificationDate = String(raw && raw.qualificationDate || '');
    const contextStartDate = String(raw && raw.contextStartDate || '');
    const endDate = String(raw && raw.endDate || '');
    const qualificationBar = Number(raw && raw.qualificationBar);
    const iso = /^\d{4}-\d{2}-\d{2}$/;
    if (!symbol || !iso.test(qualificationDate) || !iso.test(contextStartDate) || !iso.test(endDate)
        || !Number.isInteger(qualificationBar) || qualificationBar < 0) {
      throw new Error('Candidate descriptors are incomplete');
    }
    return {
      symbol,
      displaySymbol: symbol,
      assetType: 'stock',
      role: 'entry_trainer_candidate',
      entryKey: 'entry_trainer:' + symbol + ':' + qualificationDate,
      entryInstanceKey: 'entry_trainer:' + symbol + ':' + qualificationDate,
      qualificationDate,
      qualificationBar,
      contextStartDate,
      endDate,
      status: 'pending',
      attempts: [],
      pendingOrder: null,
      orderEvents: [],
      comparisonPoints: []
    };
  }

  function validateRules(raw){
    const periods = raw && Array.isArray(raw.emaPeriods) ? raw.emaPeriods.map(Number).sort(function(a,b){ return a-b; }) : [];
    if (!raw || Number(raw.gainLookback) !== REQUIRED_RULES.gainLookback
        || Number(raw.minGain) !== REQUIRED_RULES.minGain
        || Number(raw.contextBars) !== REQUIRED_RULES.contextBars
        || Number(raw.forwardBars) !== REQUIRED_RULES.forwardBars
        || periods.length !== 2 || periods[0] !== 10 || periods[1] !== 20) {
      throw new Error('The server returned unsupported trainer rules');
    }
    return {
      gainLookback: REQUIRED_RULES.gainLookback,
      minGain: REQUIRED_RULES.minGain,
      emaPeriods: REQUIRED_RULES.emaPeriods.slice(),
      contextBars: REQUIRED_RULES.contextBars,
      forwardBars: REQUIRED_RULES.forwardBars
    };
  }

  function validateBatchPayload(payload){
    if (!payload || !Array.isArray(payload.candidates) || payload.candidates.length !== BATCH_SIZE) {
      throw new Error('Entry Trainer requires exactly three candidates');
    }
    const candidates = payload.candidates.map(normalizeCandidate);
    const unique = new Set(candidates.map(function(candidate){ return candidate.symbol; }));
    if (unique.size !== BATCH_SIZE) throw new Error('Entry Trainer candidates must be unique');
    return { rules:validateRules(payload.rules), candidates };
  }

  async function fetchBatchDescriptors(operation){
    const response = await fetch('/api/entry-trainer/candidates?count=3', {
      headers:{Accept:'application/json'},
      signal: operation.controller.signal
    });
    assertCurrentOperation(operation);
    let payload = null;
    try { payload = await response.json(); } catch (error) {}
    if (!response.ok || !payload || payload.error) {
      throw new Error(payload && payload.error ? String(payload.error) : 'Could not select an Entry Trainer batch');
    }
    return validateBatchPayload(payload);
  }

  function createBatch(descriptors, startingEquity){
    return {
      version: BATCH_VERSION,
      id: 'entry-trainer-' + Date.now() + '-' + Math.random().toString(36).slice(2, 9),
      createdAt: new Date().toISOString(),
      rules: clone(descriptors.rules),
      startingEquity,
      orderState: {
        cash: startingEquity,
        reservedBuyingPower: 0,
        _orderReservationCents: {}
      },
      status: 'loading',
      activeIndex: 0,
      candidates: descriptors.candidates.map(function(candidate){ return clone(candidate); })
    };
  }

  function ordersApi(){
    return window.PortSimOrders || null;
  }

  function activeCandidate(){
    const batch = state.batch;
    return batch && batch.candidates ? batch.candidates[batch.activeIndex] : null;
  }

  function workingOrder(candidate){
    const order = candidate && candidate.pendingOrder;
    return order && order.status === 'working' ? order : null;
  }

  function reconcileOrders(batch, reason){
    const api = ordersApi();
    if (!api || !batch || !batch.orderState || typeof api.reconcile !== 'function') return 0;
    const runtime = state.runtime;
    const barIdx = runtime && runtime.playbackState ? runtime.playbackState.playIdx : null;
    const bar = runtime && runtime.fullBars && Number.isInteger(barIdx) ? runtime.fullBars[barIdx] : null;
    const reserved = api.reconcile(batch.orderState, batch.candidates, {
      date: bar && bar.time || null,
      barIdx: barIdx,
      reason: reason || 'Entry Trainer reservation state was reconciled.'
    });
    syncOrderPresentation(batch);
    return reserved;
  }

  function clearLimitLine(){
    if (window.Sim && window.Sim.Ctrl && typeof window.Sim.Ctrl.setFlatGuideLine === 'function') {
      window.Sim.Ctrl.setFlatGuideLine(null);
    }
  }

  function showLimitLine(order){
    if (!order || !window.Sim || !window.Sim.Ctrl || typeof window.Sim.Ctrl.setFlatGuideLine !== 'function') return false;
    return window.Sim.Ctrl.setFlatGuideLine({
      price: order.limitPrice,
      color: '#60a5fa',
      title: 'ENTRY LIMIT'
    });
  }

  function syncOrderPresentation(batch){
    if (!batch || batch !== state.batch) return;
    const candidate = batch.candidates && batch.candidates[batch.activeIndex];
    const order = workingOrder(candidate);
    if (order && state.runtime && state.runtime.playbackState) showLimitLine(order);
    else clearLimitLine();
    updateStrip();
  }

  function transitionOrder(candidate, status, details){
    const api = ordersApi();
    const batch = state.batch;
    if (!api || !batch || !candidate || !workingOrder(candidate)) return null;
    const orderId = workingOrder(candidate).id;
    const priorEventCount = Array.isArray(candidate.orderEvents) ? candidate.orderEvents.length : 0;
    let event = api.transition(batch.orderState, candidate, status, details || {});
    if (!event) {
      reconcileOrders(batch, 'Entry Trainer repaired a reservation before terminal transition.');
      if (workingOrder(candidate)) event = api.transition(batch.orderState, candidate, status, details || {});
    }
    if (!event && !workingOrder(candidate)) {
      event = (candidate.orderEvents || []).slice(priorEventCount).find(function(item){
        return item && item.orderId === orderId && item.type === 'invalidated';
      }) || null;
    }
    if (!event && workingOrder(candidate)) {
      const stranded = workingOrder(candidate);
      stranded.status = 'invalidated';
      stranded.completedDate = details && (details.date || details.fillDate) || stranded.submittedDate;
      stranded.completedBarIdx = details && (details.barIdx != null ? details.barIdx : details.fillBarIdx);
      event = api.recordEvent(candidate, 'invalidated', Object.assign({}, details || {}, {
        order: stranded,
        reason: 'Order lifecycle transition failed after reservation reconciliation.'
      }));
      api.reconcile(batch.orderState, batch.candidates, {
        date: stranded.completedDate,
        barIdx: stranded.completedBarIdx,
        reason: 'Entry Trainer released a stranded terminal reservation.'
      });
    }
    syncOrderPresentation(batch);
    return event;
  }

  function terminalizeWorkingOrder(candidate, status, reason, barIdx){
    const order = workingOrder(candidate);
    if (!order) return null;
    const runtime = state.runtime;
    const resolvedIdx = Number.isInteger(barIdx)
      ? barIdx
      : (runtime && runtime.playbackState ? runtime.playbackState.playIdx : order.submittedBarIdx);
    const bar = runtime && runtime.fullBars && Number.isInteger(resolvedIdx) ? runtime.fullBars[resolvedIdx] : null;
    return transitionOrder(candidate, status, {
      date: bar && bar.time || order.submittedDate,
      barIdx: resolvedIdx,
      reason: reason
    });
  }

  function cleanupWorkingOrders(status, reason){
    const batch = state.batch;
    if (!batch || !Array.isArray(batch.candidates)) {
      clearLimitLine();
      return;
    }
    batch.candidates.forEach(function(candidate){
      terminalizeWorkingOrder(candidate, status, reason);
    });
    reconcileOrders(batch, reason);
    clearLimitLine();
  }

  function verifyCandidateBars(candidate, rules, bars){
    const qualificationIndex = bars.findIndex(function(bar){ return bar.time === candidate.qualificationDate; });
    const contextIndex = bars.findIndex(function(bar){ return bar.time === candidate.contextStartDate; });
    const endIndex = bars.findIndex(function(bar){ return bar.time === candidate.endDate; });
    if (qualificationIndex < 0 || contextIndex < 0 || endIndex < 0) {
      throw new Error('Candidate dates are missing from local daily history');
    }
    if (qualificationIndex !== candidate.qualificationBar
        || !bars[candidate.qualificationBar]
        || bars[candidate.qualificationBar].time !== candidate.qualificationDate) {
      throw new Error('Candidate qualification bar does not match local daily history');
    }
    if (qualificationIndex - contextIndex !== rules.contextBars
        || endIndex - qualificationIndex !== rules.forwardBars) {
      throw new Error('Candidate daily history no longer matches the fixed trainer window');
    }
    return { qualificationIndex, contextIndex, endIndex };
  }

  function finiteNumber(value){
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value !== 'string' || !value.trim()) return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  // This intentionally remains review-only: playback receives no EMA series or comparison markers.
  function pointInTimeEma(bars, period){
    const values = Array.isArray(bars) ? new Array(bars.length).fill(null) : [];
    const alpha = 2 / (period + 1);
    let ema = null;
    values.forEach(function(unused, index){
      const close = finiteNumber(bars[index] && bars[index].close);
      if (close == null || close <= 0) return;
      ema = ema == null ? close : ema + alpha * (close - ema);
      values[index] = ema;
    });
    return values;
  }

  function comparisonDate(bar){
    return bar && typeof bar.time === 'string' && bar.time ? bar.time : null;
  }

  function fiveBarLow(bars, barIdx){
    if (!Array.isArray(bars) || barIdx < 4) return null;
    let lowest = null;
    for (let index = barIdx - 4; index <= barIdx; index += 1) {
      const low = finiteNumber(bars[index] && bars[index].low);
      if (low == null) return null;
      lowest = lowest == null ? low : Math.min(lowest, low);
    }
    return lowest;
  }

  function comparisonDiagnostic(bars, barIdx, endIndex, entry, stop){
    const risk = entry - stop;
    if (!Number.isFinite(entry) || !Number.isFinite(stop) || !Number.isFinite(risk) || risk <= 0) {
      return {
        label: COMPARISON_DIAGNOSTIC_LABEL,
        mfeR: null,
        endReason: 'invalid_stop',
        endDate: null,
        endBarIdx: null,
        stopped: null,
        sequencingAssumption: 'stop_before_high',
        stopBarHighIncluded: false
      };
    }
    let maxHigh = entry;
    let stopped = false;
    let endBarIdx = endIndex;
    for (let index = barIdx + 1; index <= endIndex; index += 1) {
      const bar = bars[index];
      const low = finiteNumber(bar && bar.low);
      if (low != null && low <= stop) {
        stopped = true;
        endBarIdx = index;
        break;
      }
      const high = finiteNumber(bar && bar.high);
      if (high != null) maxHigh = Math.max(maxHigh, high);
    }
    return {
      label: COMPARISON_DIAGNOSTIC_LABEL,
      mfeR: Math.max(0, maxHigh - entry) / risk,
      endReason: stopped ? 'stop' : 'horizon',
      endDate: comparisonDate(bars[endBarIdx]),
      endBarIdx: endBarIdx,
      stopped: stopped,
      sequencingAssumption: 'stop_before_high',
      stopBarHighIncluded: false
    };
  }

  function createComparisonPoint(rule, bars, qualificationIndex, endIndex, barIdx){
    const bar = bars[barIdx];
    const entry = finiteNumber(bar && bar.close);
    const stop = fiveBarLow(bars, barIdx);
    return {
      rule: rule,
      date: comparisonDate(bar),
      barIdx: barIdx,
      relativeBarsFromQualification: barIdx - qualificationIndex,
      hypotheticalEntry: entry,
      hypotheticalStop: stop,
      diagnostic: comparisonDiagnostic(bars, barIdx, endIndex, entry, stop)
    };
  }

  function computeComparisonPoints(bars, qualificationIndex, endIndex){
    if (!Array.isArray(bars) || !Number.isInteger(qualificationIndex) || !Number.isInteger(endIndex)
        || qualificationIndex < 0 || endIndex >= bars.length) return [];
    const firstBarIdx = Math.max(qualificationIndex + 1, 1);
    const finalBarIdx = endIndex;
    if (firstBarIdx > finalBarIdx) return [];
    const points = [];
    [10, 20].forEach(function(period){
      const ema = pointInTimeEma(bars, period);
      const rule = 'ema' + period + '_pullback';
      let armed = true;
      for (let barIdx = firstBarIdx; barIdx <= finalBarIdx; barIdx += 1) {
        const bar = bars[barIdx];
        const priorBar = bars[barIdx - 1];
        const currentEma = ema[barIdx];
        const priorEma = ema[barIdx - 1];
        const close = finiteNumber(bar && bar.close);
        const low = finiteNumber(bar && bar.low);
        const priorClose = finiteNumber(priorBar && priorBar.close);
        const wasArmed = armed;
        if (!armed && close != null && currentEma != null && close >= currentEma * 1.03) armed = true;
        if (!wasArmed || priorClose == null || close == null || low == null
            || priorEma == null || currentEma == null) continue;
        if (priorClose >= priorEma * 1.03 && low <= currentEma && close >= currentEma) {
          points.push(createComparisonPoint(rule, bars, qualificationIndex, finalBarIdx, barIdx));
          armed = false;
        }
      }
    });
    return points.sort(function(left, right){
      if (left.barIdx !== right.barIdx) return left.barIdx - right.barIdx;
      return left.rule < right.rule ? -1 : (left.rule > right.rule ? 1 : 0);
    });
  }

  function relativeLabel(relative, surface){
    if (surface === 'axis-tick') return relative >= 0 ? '+' + relative : String(relative);
    return (relative >= 0 ? 'Day +' : 'Day ') + relative;
  }

  function createDateAdapter(bars, indexes){
    const indexByDate = new Map();
    bars.forEach(function(bar, index){ indexByDate.set(bar.time, index); });
    return {
      formatDate: function(date, surface){
        const index = indexByDate.get(String(date || '').slice(0, 10));
        return index == null ? null : relativeLabel(index - indexes.qualificationIndex, surface);
      },
      formatBarIdx: function(index, surface){
        return Number.isInteger(index) ? relativeLabel(index - indexes.qualificationIndex, surface) : null;
      }
    };
  }

  function updateStrip(){
    const batch = state.batch;
    const strip = byId('entry-trainer-strip');
    if (!batch || !strip) return;
    strip.classList.add('is-active');
    const ticker = byId('entry-trainer-ticker-progress');
    const attempts = byId('entry-trainer-attempt-progress');
    const status = byId('entry-trainer-shell-status');
    const candidate = batch.candidates[batch.activeIndex];
    const order = workingOrder(candidate);
    const retryNotice = state.runtime && state.runtime.orderRetryNotice;
    const retryMessage = order && retryNotice && retryNotice.orderId === order.id
      ? retryNotice.message
      : null;
    if (ticker) ticker.textContent = 'Ticker ' + (batch.activeIndex + 1) + ' of ' + BATCH_SIZE;
    const playback = state.runtime && state.runtime.playbackState;
    let attemptNumber = candidate.attempts.length;
    if (playback && (playback.attemptActive || playback.attemptCompletePending)) {
      attemptNumber = playback.attemptNumber;
    }
    if (attempts) attempts.textContent = 'Attempt ' + Math.min(attemptNumber, MAX_ATTEMPTS) + ' of ' + MAX_ATTEMPTS;
    if (status) {
      status.textContent = batch.status === 'completed'
        ? 'Batch complete · review and persistence arrive in a later task.'
        : retryMessage
          ? retryMessage
          : playback && playback.atHorizon
            ? '90-bar horizon reached.'
            : playback && playback.attemptActive
              ? 'Attempt open · manage the stop or close the full position at the paused close.'
              : order
                ? 'Limit order working · Wait advances one candle and checks for a fill.'
                : 'Out of position · wait one bar, enter at this close, or skip the ticker.';
    }
    const pending = byId('entry-trainer-pending');
    const pendingDetail = byId('entry-trainer-pending-detail');
    const cancelOrder = byId('entry-trainer-cancel-order');
    if (pending) pending.classList.toggle('is-visible', !!order);
    if (pendingDetail) {
      pendingDetail.textContent = order
        ? order.qty.toLocaleString() + ' @ $' + Number(order.limitPrice).toFixed(2)
          + ' · $' + Math.round(order.reservedBuyingPower).toLocaleString() + ' reserved'
        : '';
    }
    if (cancelOrder) cancelOrder.disabled = !order || batch.status !== 'active';
    const wait = byId('entry-trainer-wait');
    const enter = byId('entry-trainer-enter');
    const skip = byId('entry-trainer-skip');
    const primary = byId('entry-trainer-primary-actions');
    const result = byId('entry-trainer-result');
    const showingResult = !!(result && result.classList.contains('is-visible'));
    if (status) status.style.display = showingResult ? 'none' : '';
    if (primary) primary.style.display = showingResult ? 'none' : '';
    const tryAgain = byId('entry-trainer-try-again');
    if (tryAgain && showingResult) tryAgain.disabled = !playback || !playback.canTryAgain;
    if (wait) {
      wait.disabled = batch.status !== 'active' || !playback || !playback.canWait;
      wait.title = wait.disabled ? 'Wait is available only while flat before the horizon.' : 'Advance exactly one daily bar';
    }
    if (enter) {
      enter.disabled = batch.status !== 'active' || !playback || !playback.canEnter || !!order;
      enter.title = order
        ? 'Cancel the working limit order before submitting another entry.'
        : (enter.disabled ? 'Entry is available only while flat before the horizon.' : 'Submit a market-at-close or exact-price limit entry');
    }
    if (skip) skip.disabled = batch.status !== 'active' || !playback || !playback.flat || playback.attemptCompletePending;
    const launch = byId('entry-trainer-btn');
    if (launch) launch.setAttribute('aria-pressed', 'true');
  }

  function hideAttemptResult(){
    byId('entry-trainer-result')?.classList.remove('is-visible');
    const tryAgain = byId('entry-trainer-try-again');
    if (tryAgain) tryAgain.hidden = false;
    const primary = byId('entry-trainer-primary-actions');
    if (primary) primary.style.display = '';
  }

  function signedR(value){
    if (!Number.isFinite(value)) return '—R';
    return (value >= 0 ? '+' : '−') + Math.abs(value).toFixed(2) + 'R';
  }

  function signedDollars(value){
    if (!Number.isFinite(value)) return '$—';
    return (value >= 0 ? '+' : '−') + '$' + Math.round(Math.abs(value)).toLocaleString();
  }

  function showAttemptResult(snapshot){
    const result = byId('entry-trainer-result');
    if (!result) return;
    const r = byId('entry-trainer-result-r');
    const detail = byId('entry-trainer-result-detail');
    if (r) r.textContent = signedR(snapshot.realizedR);
    if (detail) {
      detail.textContent = signedDollars(snapshot.realizedPnL)
        + ' · ' + snapshot.barsHeld + ' bars'
        + ' · MFE ' + signedR(snapshot.mfeR)
        + ' · MAE ' + signedR(snapshot.maeR);
    }
    const canTry = snapshot.attemptNumber < MAX_ATTEMPTS
      && snapshot.exitReason !== 'horizon_end'
      && state.runtime && state.runtime.playbackState
      && !state.runtime.playbackState.atHorizon;
    const tryAgain = byId('entry-trainer-try-again');
    if (tryAgain) {
      tryAgain.hidden = !canTry;
      tryAgain.disabled = !canTry;
    }
    result.classList.add('is-visible');
    updateStrip();
  }

  function showHorizonEnded(){
    const result = byId('entry-trainer-result');
    if (!result) return;
    const r = byId('entry-trainer-result-r');
    const detail = byId('entry-trainer-result-detail');
    if (r) r.textContent = 'HORIZON';
    if (detail) detail.textContent = '90 forward bars complete · no open position';
    const tryAgain = byId('entry-trainer-try-again');
    if (tryAgain) {
      tryAgain.hidden = true;
      tryAgain.disabled = true;
    }
    result.classList.add('is-visible');
    updateStrip();
  }

  function playbackIsCurrent(runtime, candidateIndex, token){
    return state.runtime === runtime
      && state.batch
      && state.batch.activeIndex === candidateIndex
      && runtime.playbackToken === token
      && state.status === 'active';
  }

  function validateEntrySubmission(form, context){
    const batch = state.batch;
    const runtime = state.runtime;
    const candidate = activeCandidate();
    const playback = runtime && runtime.playbackState;
    if (!batch || batch.status !== 'active' || state.status !== 'active' || !candidate || !playback
        || !playback.flat || playback.attemptCompletePending || playback.atHorizon
        || playback.attemptsCompleted >= MAX_ATTEMPTS || workingOrder(candidate)) {
      throw new Error('Entry is no longer available at this paused bar.');
    }
    if (!context || context.playIdx !== playback.playIdx) throw new Error('The paused bar changed before entry submission.');
    const price = Number(form && form.price);
    const stop = Number(form && form.stop);
    const sizeValue = Number(form && form.sizeValue);
    if (!Number.isFinite(price) || price <= 0) throw new Error('Entry price must be greater than $0.');
    if (!Number.isFinite(stop) || stop <= 0 || stop >= price) throw new Error('The long protective stop must be below the entry price.');
    if (!Number.isFinite(sizeValue) || sizeValue <= 0) throw new Error('Order size must be greater than zero.');
    if (form.sizeMode === 'shares' && !Number.isInteger(sizeValue)) throw new Error('Share quantity must be a whole number.');
    const qty = form.sizeMode === 'dollars' ? Math.floor(sizeValue / price) : sizeValue;
    if (!Number.isSafeInteger(qty) || qty <= 0) throw new Error('Order size must resolve to at least one whole share.');
    const notional = qty * price;
    if (!Number.isFinite(notional) || notional > batch.startingEquity + 1e-9) {
      throw new Error('Order notional cannot exceed the starting equity.');
    }
    return { candidate:candidate, qty:qty, price:price, stop:stop, notional:notional };
  }

  function handleEntrySubmission(form, context){
    const validated = validateEntrySubmission(form, context);
    if (form.orderType !== 'limit') return null;
    const api = ordersApi();
    const batch = state.batch;
    if (!api || typeof api.create !== 'function' || typeof api.reserve !== 'function') {
      throw new Error('Pending-order support is unavailable.');
    }
    if (batch.candidates.some(function(candidate){ return !!workingOrder(candidate); })) {
      throw new Error('Only one Entry Trainer order may be working at a time.');
    }
    reconcileOrders(batch, 'Entry Trainer reconciled reservations before order placement.');
    const created = api.create({
      kind: 'entry',
      direction: 'long',
      limitPrice: validated.price,
      sizeMode: 'shares',
      sizeValue: validated.qty,
      stopPrice: validated.stop,
      stopTrail: null,
      stopTriggerMode: form.stopTriggerMode,
      allowFillBarStop: form.allowFillBarStop === true
    }, {
      state: batch.orderState,
      entry: validated.candidate,
      eligible: true,
      submittedBarIdx: context.playIdx,
      submittedDate: context.date
    });
    if (!created || !created.ok) throw new Error(created && created.error || 'Could not create the limit order.');
    let reserved = api.reserve(batch.orderState, validated.candidate, created.order);
    if (!reserved) {
      reconcileOrders(batch, 'Entry Trainer repaired reservations before order placement.');
      reserved = api.reserve(batch.orderState, validated.candidate, created.order);
    }
    if (!reserved) throw new Error('Could not reserve buying power for the limit order.');
    syncOrderPresentation(batch);
    return { handled:true };
  }

  function cancelPendingOrder(){
    const candidate = activeCandidate();
    const event = terminalizeWorkingOrder(candidate, 'cancelled', 'Manually cancelled.');
    if (!event) return false;
    reconcileOrders(state.batch, 'Entry Trainer reconciled reservations after cancellation.');
    updateStrip();
    byId('entry-trainer-enter')?.focus();
    return true;
  }

  function captureOrderTransaction(batch, candidate){
    return {
      pendingOrder: clone(candidate.pendingOrder),
      orderEvents: clone(candidate.orderEvents || []),
      orderState: clone(batch.orderState)
    };
  }

  function restoreOrderTransaction(batch, candidate, snapshot){
    if (!batch || !candidate || !snapshot) return false;
    function restoreSnapshot(){
      candidate.pendingOrder = clone(snapshot.pendingOrder);
      candidate.orderEvents = clone(snapshot.orderEvents);
      batch.orderState = clone(snapshot.orderState);
    }
    restoreSnapshot();
    try {
      const api = ordersApi();
      if (api && typeof api.reconcile === 'function') {
        api.reconcile(batch.orderState, batch.candidates, {
          reason: 'Entry Trainer restored a working reservation after fill commit failure.'
        });
      }
    } catch (error) {
      console.error('[EntryTrainer] order rollback reconciliation failed:', error);
      restoreSnapshot();
    }
    if (!workingOrder(candidate)) restoreSnapshot();
    try { syncOrderPresentation(batch); }
    catch (error) {
      console.error('[EntryTrainer] order rollback presentation failed:', error);
      try { showLimitLine(workingOrder(candidate)); } catch (ignored) {}
      try { updateStrip(); } catch (ignored) {}
    }
    return !!workingOrder(candidate);
  }

  function clearOrderRetryNotice(order){
    const runtime = state.runtime;
    if (!runtime || !runtime.orderRetryNotice) return;
    if (!order || runtime.orderRetryNotice.orderId === order.id) runtime.orderRetryNotice = null;
  }

  function showOrderRetryNotice(order){
    const runtime = state.runtime;
    if (!runtime || !order) return;
    runtime.orderRetryNotice = {
      orderId: order.id,
      message: 'The limit fill could not be applied. The order remains working; choose Wait to retry.'
    };
    try { updateStrip(); }
    catch (error) { console.error('[EntryTrainer] order retry notice could not render:', error); }
  }

  function fillWorkingOrderOnBar(candidate, order, bar, barIdx, fill){
    const api = ordersApi();
    const batch = state.batch;
    const runtime = state.runtime;
    if (!api || !batch || !runtime || !workingOrder(candidate)) return false;
    let canSettle = api.canSettle(batch.orderState, order, fill.price);
    if (!canSettle) {
      reconcileOrders(batch, 'Entry Trainer repaired reservations before fill settlement.');
      canSettle = api.canSettle(batch.orderState, order, fill.price);
    }
    if (!canSettle) {
      transitionOrder(candidate, 'invalidated', {
        date: bar.time,
        barIdx: barIdx,
        price: fill.price,
        reason: 'Reserved buying power was unavailable when the order tried to fill.'
      });
      updateStrip();
      return null;
    }

    const openingFill = Number(bar.open) > 0 && Number(bar.open) <= Number(order.limitPrice);
    const gapThroughStop = openingFill && Number(bar.open) <= Number(order.stopPrice);
    const processFillBarStop = gapThroughStop || order.allowFillBarStop === true;
    const recordIntradayExtremes = openingFill;
    const fillTiming = gapThroughStop
      ? 'opening_gap_through_stop'
      : (openingFill ? 'opening_limit_fill' : 'intraday_limit_touch');
    const extremaTiming = gapThroughStop
      ? 'opening_gap_safety'
      : openingFill
        ? 'fill_bar_full'
        : processFillBarStop
          ? 'fill_bar_close_and_stop_only'
        : 'next_bar';
    const prepared = window.Sim.Ctrl.prepareFlatEntry({
      direction: 'long',
      price: fill.price,
      sizeMode: 'shares',
      sizeValue: order.qty,
      stop: order.stopPrice,
      stopTrail: null,
      stopTriggerMode: order.stopTriggerMode
    }, {
      barIdx: barIdx,
      orderId: order.id,
      requestedPrice: order.limitPrice,
      riskReferencePrice: order.limitPrice,
      executionTiming: 'limit_fill',
      fillTiming: fillTiming,
      extremaTiming: extremaTiming,
      extremaStartBarIdx: extremaTiming === 'next_bar' ? barIdx + 1 : barIdx,
      processFillBarStop: processFillBarStop,
      recordIntradayExtremes: recordIntradayExtremes,
      forceGap: gapThroughStop
    });
    if (!prepared || !prepared.ok) {
      transitionOrder(candidate, 'invalidated', {
        date: bar.time,
        barIdx: barIdx,
        price: fill.price,
        reason: 'Entry preparation failed: ' + (prepared && prepared.error || 'Flat-playback adapter rejected the fill.')
      });
      return null;
    }

    const orderSnapshot = captureOrderTransaction(batch, candidate);
    let committed = false;
    let terminalizedWithoutFill = false;
    let started = null;
    try {
      const filledEvent = transitionOrder(candidate, 'filled', {
        date: bar.time,
        barIdx: barIdx,
        price: fill.price,
        fillPrice: fill.price,
        requestedPrice: order.limitPrice,
        gapImproved: fill.gapImproved === true,
        fillTiming: fillTiming,
        executionTiming: 'limit_fill',
        extremaTiming: extremaTiming,
        extremaStartBarIdx: extremaTiming === 'next_bar' ? barIdx + 1 : barIdx
      });
      if (!filledEvent || filledEvent.type !== 'filled') {
        terminalizedWithoutFill = !workingOrder(candidate)
          && (!candidate.pendingOrder || candidate.pendingOrder.status !== 'filled');
        return terminalizedWithoutFill ? null : { allow:false };
      }

      started = window.Sim.Ctrl.commitFlatEntry(prepared);
      if (!started || !started.ok) return { allow:false };
      committed = true;
    } catch (error) {
      console.error('[EntryTrainer] limit fill transaction failed:', error);
      return { allow:false };
    } finally {
      if (!committed) {
        try { window.Sim.Ctrl.discardFlatEntry(prepared); }
        catch (error) { console.error('[EntryTrainer] staged entry discard failed:', error); }
        if (!terminalizedWithoutFill && restoreOrderTransaction(batch, candidate, orderSnapshot)) {
          showOrderRetryNotice(workingOrder(candidate));
        }
      }
    }
    clearOrderRetryNotice(order);
    if (gapThroughStop && started.stopEvent) {
      api.recordEvent(candidate, 'gap_stop', {
        order: order,
        date: bar.time,
        barIdx: barIdx,
        price: started.stopEvent.price,
        fillTiming: fillTiming,
        reason: 'Opening gap filled the entry through its fixed protective stop.'
      });
    }
    reconcileOrders(batch, 'Entry Trainer reconciled reservations after fill settlement.');
    return { handled:true };
  }

  function handleBeforeFlatStep(context){
    const candidate = activeCandidate();
    const order = workingOrder(candidate);
    if (!order || !context || !context.bar) return null;
    clearOrderRetryNotice(order);
    if (context.barIdx >= context.endBarIdx) {
      terminalizeWorkingOrder(candidate, 'expired', 'Limit order reached the ticker horizon unfilled.', context.barIdx);
      reconcileOrders(state.batch, 'Entry Trainer reconciled reservations at the ticker horizon.');
      updateStrip();
      return null;
    }
    const api = ordersApi();
    const fill = api && api.evaluateFill(order, context.bar, context.barIdx);
    if (fill) {
      return fillWorkingOrderOnBar(candidate, order, context.bar, context.barIdx, fill);
    }
    return null;
  }

  function activateCandidatePlayback(batch, runtime, index){
    if (!window.Sim || !window.Sim.Ctrl || typeof window.Sim.Ctrl.startFlatPlayback !== 'function') {
      throw new Error('The flat playback controller is not ready');
    }
    hideAttemptResult();
    runtime.playbackState = null;
    runtime.lastAttempt = null;
    runtime.horizonEnded = false;
    runtime.playbackToken = (runtime.playbackToken || 0) + 1;
    const token = runtime.playbackToken;
    const candidate = batch.candidates[index];
    batch.candidates.forEach(function(owner, ownerIndex){
      const stale = ownerIndex !== index ? workingOrder(owner) : null;
      if (!stale) return;
      transitionOrder(owner, 'expired', {
        date: stale.submittedDate,
        barIdx: null,
        reason: 'Prior candidate was deactivated before the order filled.'
      });
    });
    reconcileOrders(batch, 'Entry Trainer reconciled reservations during candidate activation.');
    clearLimitLine();
    const started = window.Sim.Ctrl.startFlatPlayback({
      bars: runtime.fullBars,
      moveKey: 'ENTRY_TRAINER',
      startBarIdx: runtime.qualificationIndex,
      endBarIdx: runtime.endIndex,
      initialEquity: batch.startingEquity,
      policy: {
        longOnly: true,
        disableRewind: true,
        disableAdds: true,
        fullExitOnly: true,
        pauseWhenFlat: true,
        maxLegs: MAX_ATTEMPTS,
        entryOrderMode: 'pending_limit',
        beforeFlatStep: function(context){
          if (!playbackIsCurrent(runtime, index, token)) return { allow:false };
          return handleBeforeFlatStep(context);
        },
        onEntrySubmit: function(form, context){
          if (!playbackIsCurrent(runtime, index, token)) throw new Error('This candidate is no longer active.');
          return handleEntrySubmission(form, context);
        },
        onStateChange: function(playbackState){
          if (!playbackIsCurrent(runtime, index, token)) return;
          runtime.playbackState = playbackState;
          updateStrip();
        },
        onAttemptComplete: function(snapshot){
          if (!playbackIsCurrent(runtime, index, token)) return;
          candidate.attempts.push(clone(snapshot));
          candidate.status = 'active';
          runtime.lastAttempt = snapshot;
          showAttemptResult(snapshot);
        },
        onHorizonComplete: function(){
          if (!playbackIsCurrent(runtime, index, token)) return;
          runtime.horizonEnded = true;
          if (!runtime.lastAttempt) showHorizonEnded();
          else updateStrip();
        }
      }
    });
    if (!started) throw new Error('Could not start candidate playback');
    if (workingOrder(candidate)) showLimitLine(candidate.pendingOrder);
  }

  function lockOrdinaryControls(runtime){
    const nodes = [
      document.querySelector('.table-panel'),
      document.querySelector('.filters'),
      document.querySelector('.chart-topbar'),
      byId('draw-toolbar'),
      byId('add-ticker-btn'), byId('sim-start-btn'), byId('sim-random-btn'),
      byId('sim-blind-btn'), byId('sim-saved-btn'), byId('sim-stats-btn'),
      byId('quiz-btn'), byId('portsim-start-btn'), byId('portsim-saved-btn')
    ].filter(Boolean);
    runtime.lockedControls = nodes.map(function(node){
      const prior = !!node.inert;
      node.inert = true;
      return { node, prior };
    });
  }

  function unlockOrdinaryControls(runtime){
    (runtime && runtime.lockedControls || []).forEach(function(record){
      record.node.inert = record.prior;
    });
    if (runtime) runtime.lockedControls = [];
  }

  async function loadCandidate(batch, runtime, index, operation){
    assertCurrentOperation(operation);
    const candidate = batch.candidates[index];
    let validated = null;
    const fullBars = await runtime.chartSession.loadSymbol(candidate.symbol, {
      signal: operation.controller.signal,
      displayFrom: candidate.contextStartDate,
      displayThrough: candidate.qualificationDate,
      mask: {
        symbolLabel: '🎯 MASKED TICKER',
        conditionLabel: 'LONG · DAILY',
        rangeLabel: 'Day −' + batch.rules.contextBars + ' → Day 0'
      },
      validateBars: function(bars){
        assertCurrentOperation(operation);
        validated = verifyCandidateBars(candidate, batch.rules, bars);
      },
      beforeCommit: function(bars){
        assertCurrentOperation(operation);
        if (!validated || !runtime.maskLease || !runtime.maskLease.install(createDateAdapter(bars, validated))) {
          throw new Error('Entry Trainer lost its date-mask lease');
        }
      }
    });
    assertCurrentOperation(operation);
    if (!validated) throw new Error('Candidate validation did not complete');
    const analysisToken = (runtime.comparisonAnalysisToken || 0) + 1;
    runtime.comparisonAnalysisToken = analysisToken;
    const comparisonPoints = computeComparisonPoints(fullBars, validated.qualificationIndex, validated.endIndex);
    if (!isCurrentOperation(operation)
        || runtime.comparisonAnalysisToken !== analysisToken
        || batch.candidates[index] !== candidate) {
      throw staleOperationError();
    }
    runtime.fullBars = fullBars;
    runtime.qualificationIndex = validated.qualificationIndex;
    runtime.contextIndex = validated.contextIndex;
    runtime.endIndex = validated.endIndex;
    runtime.activeSymbol = candidate.symbol;
    candidate.comparisonPoints = comparisonPoints;
    candidate.status = 'active';
    batch.activeIndex = index;
  }

  function cleanupShell(options){
    options = options || {};
    const runtime = state.runtime;
    let restored = { ok:true, restored:false, error:null };
    cleanupWorkingOrders('cancelled', options.orderReason || 'Entry Trainer batch exited.');
    if (window.Sim && window.Sim.Ctrl && typeof window.Sim.Ctrl.stopFlatPlayback === 'function') {
      try { window.Sim.Ctrl.stopFlatPlayback(); } catch (error) {}
    }
    try {
      if (runtime && runtime.chartSession) restored = runtime.chartSession.restore();
    } catch (error) {
      restored = { ok:false, restored:false, error };
    }
    if (!restored || !restored.ok) {
      if (runtime && !(runtime.lockedControls || []).length) lockOrdinaryControls(runtime);
      state.status = 'restore-error';
      document.body.classList.add('entry-trainer-active');
      setSetupBusy(false);
      const start = byId('entry-trainer-start');
      const cancel = byId('entry-trainer-cancel');
      if (start) start.disabled = true;
      if (cancel) cancel.textContent = 'Retry restore';
      setSetupOpen(true, {focusTarget:'entry-trainer-cancel'});
      setSetupStatus('The prior chart could not be fully restored. Cancel retries restoration while ordinary controls remain locked. ' + (restored && restored.error ? restored.error.message : ''), true);
      return restored || { ok:false, restored:false, error:new Error('Unknown chart restore failure') };
    }
    try { runtime?.maskLease?.release(); } catch (error) {}
    unlockOrdinaryControls(runtime);
    document.body.classList.remove('entry-trainer-active');
    byId('entry-trainer-strip')?.classList.remove('is-active');
    hideAttemptResult();
    const launch = byId('entry-trainer-btn');
    if (launch) launch.setAttribute('aria-pressed', 'false');
    setSetupBusy(false);
    if (options.closeModal) setSetupOpen(false, {restoreFocus:!!options.restoreFocus});
    return restored;
  }

  async function startFromSetup(){
    if (state.status === 'loading' || state.status === 'active' || state.status === 'restore-error') return;
    const input = byId('entry-trainer-equity');
    const startingEquity = Number(input && input.value);
    if (!Number.isFinite(startingEquity) || startingEquity <= 0) {
      setSetupStatus('Starting equity must be a number greater than $0.', true);
      input?.focus();
      return;
    }
    if (isOtherPlaybackActive()) {
      setSetupStatus('Exit the active simulation or quiz before starting Entry Trainer.', true);
      return;
    }
    if (!window.MainChartSession || !window.SimDateMask || !ordersApi()
        || !window.Sim || !window.Sim.Ctrl
        || typeof window.Sim.Ctrl.prepareFlatEntry !== 'function'
        || typeof window.Sim.Ctrl.commitFlatEntry !== 'function'
        || typeof window.Sim.Ctrl.discardFlatEntry !== 'function') {
      setSetupStatus('The chart session is still loading. Try again in a moment.', true);
      return;
    }
    if (typeof window.SimDateMask.tryAcquire !== 'function') {
      setSetupStatus('The date-mask service is not ready. Try again in a moment.', true);
      return;
    }

    const maskAcquisition = window.SimDateMask.tryAcquire(MASK_OWNER);
    if (!maskAcquisition.ok) {
      const owner = maskAcquisition.owner === 'sim-blind' ? 'Blind Sim' : (maskAcquisition.owner || 'another playback mode');
      setSetupStatus('Entry Trainer cannot start because date masking is currently owned by ' + owner + '. Exit it and try again.', true);
      return;
    }
    if (typeof window.MainChartSession.acquire !== 'function') {
      maskAcquisition.lease.release();
      setSetupStatus('The chart session owner is not ready. Try again in a moment.', true);
      return;
    }
    const chartAcquisition = window.MainChartSession.acquire(MASK_OWNER);
    if (!chartAcquisition.ok) {
      maskAcquisition.lease.release();
      setSetupStatus('Entry Trainer cannot start because the main chart is currently owned by ' + (chartAcquisition.owner || 'another session') + '.', true);
      return;
    }

    const operation = beginOperation();
    const runtime = {
      chartSession: chartAcquisition.session,
      maskLease: maskAcquisition.lease,
      fullBars: null,
      qualificationIndex: null,
      contextIndex: null,
      endIndex: null,
      activeSymbol: null,
      lockedControls: [],
      playbackState: null,
      playbackToken: 0,
      lastAttempt: null,
      horizonEnded: false
    };
    state.status = 'loading';
    state.runtime = runtime;
    setSetupBusy(true);
    setSetupStatus('Selecting three point-in-time candidates…', false);
    let draft = null;
    try {
      const descriptors = await fetchBatchDescriptors(operation);
      assertCurrentOperation(operation);
      draft = createBatch(descriptors, startingEquity);
      state.batch = draft;
      setSetupStatus('Loading the first masked chart…', false);
      await loadCandidate(draft, runtime, 0, operation);
      assertCurrentOperation(operation);
      draft.status = 'active';
      state = { status:'active', batch:draft, lastBatch:state.lastBatch, runtime };
      lockOrdinaryControls(runtime);
      document.body.classList.add('entry-trainer-active');
      activateCandidatePlayback(draft, runtime, 0);
      setSetupOpen(false, {restoreFocus:false});
      setSetupStatus('', false);
      updateStrip();
      byId('entry-trainer-strip')?.focus();
    } catch (error) {
      if (isStaleOperation(error, operation)) return;
      console.error('[EntryTrainer] start failed:', error);
      const cleanup = cleanupShell({closeModal:false, restoreFocus:false});
      if (cleanup.ok) {
        state.status = 'idle';
        state.batch = null;
        state.runtime = null;
        setSetupStatus('Could not start the batch. The previous chart was preserved. ' + error.message, true);
      }
    } finally {
      if (isCurrentOperation(operation)) {
        setSetupBusy(false);
        finishOperation(operation);
      }
    }
  }

  async function advanceCandidate(outcome, reason){
    const batch = state.batch;
    if (!batch || batch.status !== 'active' || state.status !== 'active') return;
    const skip = byId('entry-trainer-skip');
    const status = byId('entry-trainer-shell-status');
    if (skip) skip.disabled = true;
    const current = batch.candidates[batch.activeIndex];
    const runtime = state.runtime;
    if (workingOrder(current)) {
      terminalizeWorkingOrder(
        current,
        outcome === 'skipped' ? 'cancelled' : 'expired',
        outcome === 'skipped' ? 'Ticker skipped before the order filled.' : 'Ticker finished before the order filled.'
      );
      reconcileOrders(batch, 'Entry Trainer reconciled reservations before candidate cleanup.');
    }
    clearLimitLine();
    runtime.playbackToken += 1;
    if (window.Sim && window.Sim.Ctrl && typeof window.Sim.Ctrl.stopFlatPlayback === 'function') {
      window.Sim.Ctrl.stopFlatPlayback();
    }
    runtime.playbackState = null;
    hideAttemptResult();
    current.status = outcome === 'skipped' ? 'skipped' : 'completed';
    if (outcome === 'skipped') current.skipReason = reason || 'user_skip';
    else current.finishReason = reason || 'user_finish';

    if (batch.activeIndex >= BATCH_SIZE - 1) {
      batch.status = 'completed';
      batch.completedAt = new Date().toISOString();
      state.status = 'active';
      updateStrip();
      return;
    }

    if (status) status.textContent = 'Loading the next masked ticker…';
    const operation = beginOperation();
    state.status = 'loading';
    try {
      await loadCandidate(batch, state.runtime, batch.activeIndex + 1, operation);
      assertCurrentOperation(operation);
      state.status = 'active';
      activateCandidatePlayback(batch, state.runtime, batch.activeIndex);
      updateStrip();
    } catch (error) {
      if (isStaleOperation(error, operation)) return;
      console.error('[EntryTrainer] candidate load failed:', error);
      cleanupWorkingOrders('cancelled', 'Candidate load failed.');
      batch.status = 'abandoned';
      batch.abandonedAt = new Date().toISOString();
      state.lastBatch = batch;
      const cleanup = cleanupShell({closeModal:true, restoreFocus:true});
      if (cleanup.ok) {
        state = { status:'idle', batch:null, lastBatch:batch, runtime:null };
        window.alert('Entry Trainer ended because the next masked chart could not be loaded. Your previous chart was restored.');
      }
    } finally {
      finishOperation(operation);
    }
  }

  function skipTicker(){
    const playback = state.runtime && state.runtime.playbackState;
    if (!playback || !playback.flat || playback.attemptCompletePending) return;
    return advanceCandidate('skipped', 'user_skip');
  }

  function finishTicker(reason){
    const runtime = state.runtime;
    const playback = runtime && runtime.playbackState;
    const derivedReason = playback && playback.atHorizon
      ? 'horizon_end'
      : (runtime && runtime.lastAttempt && runtime.lastAttempt.attemptNumber >= MAX_ATTEMPTS)
        ? 'max_attempts'
        : 'user_finish';
    return advanceCandidate('completed', reason || derivedReason);
  }

  function waitOneBar(){
    const runtime = state.runtime;
    const playback = runtime && runtime.playbackState;
    if (!runtime || !playback || !playback.canWait) return false;
    return !!(window.Sim && window.Sim.Ctrl && typeof window.Sim.Ctrl.flatAction === 'function'
      && window.Sim.Ctrl.flatAction('wait'));
  }

  function enterAtClose(){
    if (!state.runtime || !state.runtime.playbackState || !state.runtime.playbackState.canEnter || workingOrder(activeCandidate())) return false;
    return !!(window.Sim && window.Sim.Ctrl && typeof window.Sim.Ctrl.flatAction === 'function'
      && window.Sim.Ctrl.flatAction('enter'));
  }

  function tryAgain(){
    const runtime = state.runtime;
    if (!runtime || !runtime.playbackState || !runtime.playbackState.canTryAgain) return false;
    const continued = !!(window.Sim && window.Sim.Ctrl && typeof window.Sim.Ctrl.flatAction === 'function'
      && window.Sim.Ctrl.flatAction('continue'));
    if (continued) {
      runtime.lastAttempt = null;
      hideAttemptResult();
      updateStrip();
    }
    return continued;
  }

  function open(){
    if (!wired) wire();
    if (state.status === 'restore-error') {
      setSetupOpen(true, {focusTarget:'entry-trainer-cancel'});
      return;
    }
    if (isActive()) {
      byId('entry-trainer-strip')?.focus();
      return;
    }
    setSetupStatus('', false);
    setSetupBusy(false);
    const equity = byId('entry-trainer-equity');
    if (equity && (!equity.value || Number(equity.value) <= 0)) equity.value = String(DEFAULT_EQUITY);
    setSetupOpen(true);
  }

  function isActive(){
    return state.status === 'loading' || state.status === 'restore-error' || !!(state.batch && state.status === 'active');
  }

  function exit(){
    const hadPendingWork = state.status === 'loading' || state.status === 'restore-error' || !!state.batch || !!state.runtime;
    cancelOperations();
    if (!hadPendingWork) {
      setSetupOpen(false, {restoreFocus:true});
      return false;
    }
    const batch = state.batch;
    if (batch && batch.status !== 'completed') {
      batch.status = 'abandoned';
      batch.abandonedAt = new Date().toISOString();
    }
    if (batch) state.lastBatch = batch;
    const cleanup = cleanupShell({closeModal:true, restoreFocus:true, orderReason:'Entry Trainer batch exited.'});
    if (!cleanup.ok) return false;
    state = { status:'idle', batch:null, lastBatch:batch || state.lastBatch, runtime:null };
    return true;
  }

  function openReview(batchId){
    const target = state.batch && state.batch.id === batchId ? state.batch : state.lastBatch;
    if (!target || (batchId && target.id !== batchId)) return false;
    // Review rendering is deliberately reserved for the review task.
    return false;
  }

  function cancelSetup(){
    if (state.status === 'loading' || state.status === 'restore-error') return exit();
    setSetupOpen(false, {restoreFocus:true});
    return true;
  }

  function wire(){
    if (wired) return true;
    const launch = byId('entry-trainer-btn');
    const modal = byId('entry-trainer-setup-modal');
    if (!launch || !modal) {
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire, {once:true});
      return false;
    }
    wired = true;
    launch.addEventListener('click', open);
    byId('entry-trainer-cancel')?.addEventListener('click', cancelSetup);
    byId('entry-trainer-start')?.addEventListener('click', startFromSetup);
    byId('entry-trainer-wait')?.addEventListener('click', waitOneBar);
    byId('entry-trainer-enter')?.addEventListener('click', enterAtClose);
    byId('entry-trainer-cancel-order')?.addEventListener('click', cancelPendingOrder);
    byId('entry-trainer-skip')?.addEventListener('click', skipTicker);
    byId('entry-trainer-try-again')?.addEventListener('click', tryAgain);
    byId('entry-trainer-finish')?.addEventListener('click', function(){ finishTicker(); });
    byId('entry-trainer-exit')?.addEventListener('click', exit);
    modal.addEventListener('click', function(event){
      if (event.target === modal) cancelSetup();
    });
    byId('entry-trainer-equity')?.addEventListener('keydown', function(event){
      if (event.key === 'Enter') {
        event.preventDefault();
        startFromSetup();
      }
    });
    document.addEventListener('keydown', function(event){
      if (event.key === 'Escape' && modal.classList.contains('open')) {
        event.preventDefault();
        event.stopImmediatePropagation();
        cancelSetup();
      }
    }, true);
    document.addEventListener('keydown', trapSetupFocus);
    return true;
  }

  window.EntryTrainer = Object.freeze({ open, isActive, exit, openReview, wire });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire, {once:true});
  else wire();
})();
