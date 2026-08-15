(function(){
  'use strict';

  const BATCH_VERSION = 1;
  const BATCH_SIZE = 3;
  const MAX_ATTEMPTS = 3;
  const DEFAULT_EQUITY = 300000;
  const MASK_OWNER = 'entry-trainer';
  const STORAGE_KEY = 'bm_entry_trainer_batches_v1';
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
  let lastPersistenceFailure = null;
  let reviewState = {
    batch: null,
    activeTab: 'summary',
    chart: null,
    barsController: null,
    dirty: false,
    opener: null,
    persistenceWarning: null,
    backgroundInert: [],
    modalParent: null,
    modalNextSibling: null
  };

  const REVIEW_ENUMS = Object.freeze({
    stopValidity: ['structural', 'too_tight', 'too_wide', 'unclear'],
    timing: ['early', 'well_timed', 'late'],
    limitAssessment: ['improved', 'neutral', 'hurt_confirmation', 'not_used'],
    trailTiming: ['too_early', 'too_late', 'appropriate', 'not_used'],
    manualExitDriver: ['price_behavior', 'discomfort', 'mixed', 'not_applicable'],
    comparisonActionable: ['yes', 'no', 'unclear']
  });

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

  function safeId(value){
    const id = typeof value === 'string' ? value.trim() : '';
    if (!id || id === '__proto__' || id === 'prototype' || id === 'constructor') return null;
    return /^[A-Za-z0-9_.:-]{1,180}$/.test(id) ? id : null;
  }

  function safeText(value, limit){
    if (value == null) return '';
    return String(value).replace(/\u0000/g, '').slice(0, limit || 8000);
  }

  function safeDate(value){
    const text = safeText(value, 32);
    return /^\d{4}-\d{2}-\d{2}(?:T[^\s]{1,24})?$/.test(text) ? text : null;
  }

  function safeIsoTimestamp(value){
    const text = safeText(value, 40);
    const date = new Date(text);
    return text && !Number.isNaN(date.getTime()) ? date.toISOString() : null;
  }

  function safeInteger(value, minimum){
    const number = finiteNumber(value);
    return Number.isInteger(number) && number >= (minimum == null ? 0 : minimum) ? number : null;
  }

  function safeEnum(value, choices, fallback){
    const text = safeText(value, 80);
    return choices.indexOf(text) >= 0 ? text : (fallback == null ? '' : fallback);
  }

  function safeJsonValue(value, depth){
    depth = depth == null ? 0 : depth;
    if (depth > 5 || value == null) return null;
    if (typeof value === 'string') return safeText(value, 1000);
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value === 'boolean') return value;
    if (Array.isArray(value)) return value.slice(0, 200).map(function(item){ return safeJsonValue(item, depth + 1); });
    if (typeof value !== 'object') return null;
    const output = Object.create(null);
    Object.keys(value).slice(0, 100).forEach(function(key){
      if (key === '__proto__' || key === 'prototype' || key === 'constructor') return;
      output[key] = safeJsonValue(value[key], depth + 1);
    });
    return output;
  }

  function emptyAttemptReview(){
    return {
      entryLocationRating: null,
      stopValidity: '',
      timing: '',
      limitAssessment: '',
      repeatNextTime: '',
      changeNextTime: '',
      trailTiming: '',
      manualExitDriver: '',
      mfeRetained: null
    };
  }

  function sanitizeAttemptReview(raw){
    raw = raw && typeof raw === 'object' ? raw : {};
    const rating = safeInteger(raw.entryLocationRating, 1);
    const retained = finiteNumber(raw.mfeRetained);
    return {
      entryLocationRating: rating != null && rating <= 5 ? rating : null,
      stopValidity: safeEnum(raw.stopValidity, REVIEW_ENUMS.stopValidity),
      timing: safeEnum(raw.timing, REVIEW_ENUMS.timing),
      limitAssessment: safeEnum(raw.limitAssessment, REVIEW_ENUMS.limitAssessment),
      repeatNextTime: safeText(raw.repeatNextTime),
      changeNextTime: safeText(raw.changeNextTime),
      trailTiming: safeEnum(raw.trailTiming, REVIEW_ENUMS.trailTiming),
      manualExitDriver: safeEnum(raw.manualExitDriver, REVIEW_ENUMS.manualExitDriver),
      mfeRetained: retained != null && retained >= 0 && retained <= 100 ? retained : null
    };
  }

  function sanitizeEvent(raw){
    raw = raw && typeof raw === 'object' ? raw : {};
    const output = {};
    [
      'type', 'orderId', 'kind', 'entryKey', 'entryInstanceKey', 'cardId', 'symbol',
      'displaySymbol', 'assetType', 'role', 'direction', 'date', 'reason', 'note',
      'fillTiming', 'executionTiming', 'extremaTiming', 'exitReason', 'stopId'
    ].forEach(function(key){
      if (raw[key] != null) output[key] = safeText(raw[key], key === 'reason' || key === 'note' ? 1000 : 180);
    });
    [
      'qty', 'price', 'barIdx', 'fillBarIdx', 'requestedPrice', 'fillPrice', 'limitPrice',
      'stopPrice', 'newStop', 'pct', 'reservedBuyingPower', 'extremaStartBarIdx'
    ].forEach(function(key){
      const number = finiteNumber(raw[key]);
      if (number != null) output[key] = number;
    });
    ['gapImproved', 'trailUpdate', 'allowFillBarStop'].forEach(function(key){
      if (typeof raw[key] === 'boolean') output[key] = raw[key];
    });
    if (raw.stopTrail) output.stopTrail = safeJsonValue(raw.stopTrail);
    return output;
  }

  function sanitizeAttempt(raw, index){
    raw = raw && typeof raw === 'object' ? raw : {};
    const attempt = {};
    const numberKeys = [
      'entryBarIdx', 'entryPrice', 'riskReferencePrice', 'requestedPrice', 'fillBarIdx',
      'fillPrice', 'initialStop', 'initialStopDistanceDollars', 'initialStopDistancePct',
      'initialRisk', 'initialQty', 'quantity', 'sizeValue', 'exitBarIdx', 'exitPrice',
      'exitQty', 'realizedPnL', 'realizedR', 'barsHeld', 'mfeDollars', 'maeDollars',
      'mfe', 'mae', 'mfeR', 'maeR', 'trailActivationOpenR', 'openRAtTrailActivation'
    ];
    attempt.attemptNumber = safeInteger(raw.attemptNumber, 1) || index + 1;
    [
      'direction', 'executionTiming', 'legId', 'entryDate', 'fillDate', 'orderId',
      'fillTiming', 'extremaTiming', 'sizeMode', 'exitDate', 'exitReason'
    ].forEach(function(key){
      if (raw[key] != null) attempt[key] = safeText(raw[key], 180);
    });
    numberKeys.forEach(function(key){
      const number = finiteNumber(raw[key]);
      attempt[key] = number;
    });
    attempt.stopEvents = (Array.isArray(raw.stopEvents) ? raw.stopEvents : []).slice(0, 200).map(sanitizeEvent);
    attempt.trailEvents = (Array.isArray(raw.trailEvents) ? raw.trailEvents : []).slice(0, 200).map(sanitizeEvent);
    attempt.events = (Array.isArray(raw.events) ? raw.events : []).slice(0, 400).map(sanitizeEvent);
    attempt.trailActivatedAt = raw.trailActivatedAt && typeof raw.trailActivatedAt === 'object'
      ? {
          barIdx: safeInteger(raw.trailActivatedAt.barIdx, 0),
          date: safeDate(raw.trailActivatedAt.date),
          barsFromEntry: safeInteger(raw.trailActivatedAt.barsFromEntry, 0),
          openR: finiteNumber(raw.trailActivatedAt.openR)
        }
      : null;
    attempt.trailSpec = raw.trailSpec ? safeJsonValue(raw.trailSpec) : null;
    attempt.review = sanitizeAttemptReview(raw.review);
    return attempt;
  }

  function sanitizeOrderEvent(raw){
    return sanitizeEvent(raw);
  }

  function sanitizeComparison(raw){
    raw = raw && typeof raw === 'object' ? raw : {};
    const diagnostic = raw.diagnostic && typeof raw.diagnostic === 'object' ? raw.diagnostic : {};
    return {
      rule: safeText(raw.rule, 80),
      date: safeDate(raw.date),
      barIdx: safeInteger(raw.barIdx, 0),
      relativeBarsFromQualification: finiteNumber(raw.relativeBarsFromQualification),
      hypotheticalEntry: finiteNumber(raw.hypotheticalEntry),
      hypotheticalStop: finiteNumber(raw.hypotheticalStop),
      diagnostic: {
        label: COMPARISON_DIAGNOSTIC_LABEL,
        mfeR: finiteNumber(diagnostic.mfeR),
        endReason: safeText(diagnostic.endReason, 80),
        endDate: safeDate(diagnostic.endDate),
        endBarIdx: safeInteger(diagnostic.endBarIdx, 0),
        stopped: typeof diagnostic.stopped === 'boolean' ? diagnostic.stopped : null,
        sequencingAssumption: 'stop_before_high',
        stopBarHighIncluded: false
      }
    };
  }

  function sanitizeCandidateReview(raw, comparisons){
    raw = raw && typeof raw === 'object' ? raw : {};
    const savedActions = Array.isArray(raw.comparisonActionability) ? raw.comparisonActionability : [];
    return {
      betterBuyPoints: safeText(raw.betterBuyPoints),
      secondaryEntryAssessment: safeText(raw.secondaryEntryAssessment),
      trailReasonableness: safeText(raw.trailReasonableness),
      comparisonActionability: comparisons.map(function(point){
        const prior = savedActions.find(function(item){
          return item && item.rule === point.rule && item.date === point.date;
        }) || {};
        return {
          rule: point.rule,
          date: point.date,
          actionable: safeEnum(prior.actionable, REVIEW_ENUMS.comparisonActionable),
          notes: safeText(prior.notes)
        };
      })
    };
  }

  function sanitizeRulesV1(raw){
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    const gainLookback = safeInteger(raw.gainLookback, 1);
    const minGain = finiteNumber(raw.minGain);
    const contextBars = safeInteger(raw.contextBars, 1);
    const forwardBars = safeInteger(raw.forwardBars, 1);
    const emaPeriods = Array.isArray(raw.emaPeriods)
      ? raw.emaPeriods.map(function(period){ return safeInteger(period, 1); })
      : [];
    if (gainLookback == null || gainLookback > 5000
        || minGain == null || minGain < 0 || minGain > 100
        || contextBars == null || contextBars > 5000
        || forwardBars == null || forwardBars > 5000
        || !emaPeriods.length || emaPeriods.length > 10
        || emaPeriods.some(function(period){ return period == null || period > 1000; })
        || new Set(emaPeriods).size !== emaPeriods.length) return null;
    return {
      gainLookback: gainLookback,
      minGain: minGain,
      emaPeriods: emaPeriods.slice(),
      contextBars: contextBars,
      forwardBars: forwardBars
    };
  }

  function sanitizePersistedBatchV1(raw){
    if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Number(raw.version) !== 1) return null;
    const id = safeId(raw.id);
    const status = safeEnum(raw.status, ['completed', 'abandoned']);
    const startingEquity = finiteNumber(raw.startingEquity);
    const createdAt = safeIsoTimestamp(raw.createdAt);
    const completedAt = safeIsoTimestamp(raw.completedAt);
    const abandonedAt = safeIsoTimestamp(raw.abandonedAt);
    if (!id || !status || startingEquity == null || startingEquity <= 0 || !createdAt
        || (status === 'completed' && !completedAt) || (status === 'abandoned' && !abandonedAt)) return null;
    const rules = sanitizeRulesV1(raw.rules);
    if (!rules) return null;
    const rawCandidates = Array.isArray(raw.candidates) ? raw.candidates : [];
    if (rawCandidates.length !== BATCH_SIZE) return null;
    const candidates = [];
    for (let index = 0; index < rawCandidates.length; index += 1) {
      const candidate = rawCandidates[index] && typeof rawCandidates[index] === 'object' ? rawCandidates[index] : {};
      const symbol = safeText(candidate.symbol, 30).trim().toUpperCase();
      const qualificationDate = safeDate(candidate.qualificationDate);
      const contextStartDate = safeDate(candidate.contextStartDate);
      const endDate = safeDate(candidate.endDate);
      if (!/^[A-Z0-9.^_-]{1,30}$/.test(symbol) || !qualificationDate || !contextStartDate || !endDate) return null;
      const comparisons = (Array.isArray(candidate.comparisonPoints) ? candidate.comparisonPoints : []).slice(0, 200).map(sanitizeComparison);
      const attempts = (Array.isArray(candidate.attempts) ? candidate.attempts : []).slice(0, MAX_ATTEMPTS).map(sanitizeAttempt);
      candidates.push({
        symbol: symbol,
        qualificationDate: qualificationDate,
        contextStartDate: contextStartDate,
        endDate: endDate,
        qualificationBar: safeInteger(candidate.qualificationBar, 0),
        status: safeEnum(candidate.status, ['pending', 'active', 'completed', 'skipped', 'abandoned'], 'pending'),
        skipReason: safeText(candidate.skipReason, 500),
        finishReason: safeText(candidate.finishReason, 500),
        exitReason: safeText(candidate.exitReason, 500),
        attempts: attempts,
        orderEvents: (Array.isArray(candidate.orderEvents) ? candidate.orderEvents : []).slice(0, 500).map(sanitizeOrderEvent),
        comparisonPoints: comparisons,
        review: sanitizeCandidateReview(candidate.review, comparisons)
      });
    }
    if (new Set(candidates.map(function(candidate){ return candidate.symbol; })).size !== BATCH_SIZE) return null;
    const batchReview = raw.review && typeof raw.review === 'object' ? raw.review : {};
    return {
      version: BATCH_VERSION,
      id: id,
      createdAt: createdAt,
      completedAt: completedAt,
      abandonedAt: abandonedAt,
      savedAt: safeIsoTimestamp(raw.savedAt),
      status: status,
      exitReason: safeText(raw.exitReason, 500),
      abandonReason: safeText(raw.abandonReason, 500),
      startingEquity: startingEquity,
      rules: rules,
      candidates: candidates,
      review: {
        recurringEntryHabit: safeText(batchReview.recurringEntryHabit),
        nextDrillFocus: safeText(batchReview.nextDrillFocus)
      }
    };
  }

  const PERSISTED_BATCH_READERS = Object.freeze({
    1: sanitizePersistedBatchV1
  });

  function sanitizePersistedBatch(raw){
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    const version = safeInteger(raw.version, 1);
    const reader = version == null ? null : PERSISTED_BATCH_READERS[version];
    return typeof reader === 'function' ? reader(raw) : null;
  }

  function readSavedBatches(){
    let parsed = null;
    try { parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
    catch (error) { return []; }
    if (!Array.isArray(parsed)) return [];
    return parsed.map(sanitizePersistedBatch).filter(Boolean);
  }

  function writeSavedBatches(records){
    const clean = (Array.isArray(records) ? records : []).map(sanitizePersistedBatch).filter(Boolean);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(clean));
      return { ok:true, quota:false, error:null };
    } catch (error) {
      console.warn('[EntryTrainer] save failed:', error);
      const quota = !!(error && (
        error.name === 'QuotaExceededError'
        || error.name === 'NS_ERROR_DOM_QUOTA_REACHED'
        || error.code === 22
        || error.code === 1014
      ));
      return { ok:false, quota:quota, error:error || new Error('Storage write failed') };
    }
  }

  function saveBatch(raw){
    const draft = Object.assign({}, raw || {}, { savedAt:new Date().toISOString() });
    const record = sanitizePersistedBatch(draft);
    if (!record) return { ok:false, quota:false, error:new Error('Batch record is invalid'), record:null };
    const records = readSavedBatches().filter(function(item){ return item.id !== record.id; });
    records.unshift(record);
    const result = writeSavedBatches(records);
    return {
      ok: result.ok,
      quota: result.quota,
      error: result.error,
      record: clone(record)
    };
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
      if (options.preserveFocus) return;
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
    trapFocusWithin(modal, event);
  }

  function handleReviewKeydown(event){
    const modal = byId('entry-trainer-review-modal');
    if (!modal || !modal.classList.contains('open')) return false;
    event.stopImmediatePropagation();
    if (event.key === 'Tab') trapFocusWithin(modal, event);
    else if (event.key === 'Escape') {
      event.preventDefault();
      closeReview();
    } else if (!modal.contains(event.target)) {
      event.preventDefault();
      byId('entry-trainer-review-close')?.focus();
    }
    return true;
  }

  function trapFocusWithin(modal, event){
    const focusable = Array.from(modal.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
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
      exitReason: '',
      abandonReason: '',
      activeIndex: 0,
      candidates: descriptors.candidates.map(function(candidate){ return clone(candidate); }),
      review: { recurringEntryHabit:'', nextDrillFocus:'' }
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
        ? 'Batch complete · opening review…'
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

  function closeOpenAttemptForAbandonment(){
    const runtime = state.runtime;
    const playback = runtime && runtime.playbackState;
    if (!playback || !playback.attemptActive) return true;
    const ctrl = window.Sim && window.Sim.Ctrl;
    if (!ctrl || typeof ctrl.closeFlatAttemptAtPausedClose !== 'function') return false;
    const candidate = activeCandidate();
    const priorAttempts = candidate && Array.isArray(candidate.attempts) ? candidate.attempts.length : 0;
    const closed = ctrl.closeFlatAttemptAtPausedClose('abandoned') === true;
    return !!(closed && candidate && candidate.attempts.length === priorAttempts + 1);
  }

  function finalizeBatch(status, options){
    options = options || {};
    const batch = state.batch;
    if (!batch || (status !== 'completed' && status !== 'abandoned')) return false;
    if (batch._finalized) {
      if (options.openReview !== false) openReview(batch.id);
      return true;
    }
    if (batch._finalizing) return false;
    batch._finalizing = true;
    cancelOperations();
    if (status === 'abandoned') {
      const abandonReason = safeText(options.abandonReason || options.exitReason || 'user_exit', 500) || 'user_exit';
      batch.exitReason = abandonReason;
      batch.abandonReason = abandonReason;
      if (!closeOpenAttemptForAbandonment()) {
        batch._finalizing = false;
        setSetupStatus('The open attempt could not be captured at the paused close. Retry Exit batch.', true);
        return false;
      }
      const current = batch.candidates && batch.candidates[batch.activeIndex];
      if (current && current.status !== 'completed' && current.status !== 'skipped') {
        current.status = 'abandoned';
        current.exitReason = options.exitReason || 'abandoned';
      }
    } else {
      batch.exitReason = batch.exitReason || 'completed';
      batch.abandonReason = '';
    }
    cleanupWorkingOrders(
      status === 'completed' ? 'expired' : 'cancelled',
      status === 'completed' ? 'Entry Trainer batch completed.' : 'Entry Trainer batch abandoned.'
    );
    batch.status = status;
    if (status === 'completed') batch.completedAt = batch.completedAt || new Date().toISOString();
    else batch.abandonedAt = batch.abandonedAt || new Date().toISOString();
    const cleanup = cleanupShell({
      closeModal:true,
      restoreFocus:true,
      orderReason: status === 'completed' ? 'Entry Trainer batch completed.' : 'Entry Trainer batch abandoned.'
    });
    if (!cleanup.ok) {
      batch._finalizing = false;
      return false;
    }
    const saveResult = saveBatch(batch);
    const saved = saveResult.record;
    if (!saved) {
      batch._finalizing = false;
      window.alert('The batch ended and the chart was restored, but the review record could not be prepared.');
      return false;
    }
    batch._finalized = true;
    state = { status:'idle', batch:null, lastBatch:saved, runtime:null };
    lastPersistenceFailure = saveResult.ok ? null : {
      batchId:saved.id,
      quota:saveResult.quota,
      message:saveResult.quota
        ? 'This batch is not saved because browser storage is full. Delete older saved batches, then choose Save Review to retry.'
        : 'This batch is not saved because browser storage failed. Choose Save Review to retry or export it now.'
    };
    renderSavedBatches();
    if (options.openReview !== false) openReview(saved.id);
    if (options.alertMessage) window.alert(options.alertMessage);
    return true;
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

    if (batch.activeIndex >= BATCH_SIZE - 1) return finalizeBatch('completed');

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
      finalizeBatch('abandoned', {
        exitReason:'candidate_load_failed',
        alertMessage:'Entry Trainer ended because the next masked chart could not be loaded. Your previous chart was restored.'
      });
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
    renderSavedBatches();
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
    if (batch) return finalizeBatch(batch.status === 'completed' ? 'completed' : 'abandoned', {
      exitReason:batch.status === 'completed' ? 'completed' : 'user_exit',
      abandonReason:batch.status === 'completed' ? '' : 'user_exit'
    });
    const cleanup = cleanupShell({closeModal:true, restoreFocus:true, orderReason:'Entry Trainer batch exited.'});
    if (!cleanup.ok) return false;
    state = { status:'idle', batch:null, lastBatch:state.lastBatch, runtime:null };
    return true;
  }

  function esc(value){
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatNumber(value, digits){
    const number = finiteNumber(value);
    return number == null ? '—' : number.toFixed(digits == null ? 2 : digits);
  }

  function formatR(value){
    const number = finiteNumber(value);
    if (number == null) return '—';
    return (number > 0 ? '+' : '') + number.toFixed(2) + 'R';
  }

  function formatMoney(value){
    const number = finiteNumber(value);
    if (number == null) return '—';
    return (number < 0 ? '−' : number > 0 ? '+' : '') + '$' + Math.abs(number).toLocaleString('en-US', {
      minimumFractionDigits:2,
      maximumFractionDigits:2
    });
  }

  function median(values){
    const clean = values.map(finiteNumber).filter(function(value){ return value != null; }).sort(function(a,b){ return a-b; });
    if (!clean.length) return null;
    const middle = Math.floor(clean.length / 2);
    return clean.length % 2 ? clean[middle] : (clean[middle - 1] + clean[middle]) / 2;
  }

  function allAttempts(batch){
    const rows = [];
    (batch.candidates || []).forEach(function(candidate, candidateIndex){
      (candidate.attempts || []).forEach(function(attempt, attemptIndex){
        rows.push({ candidate:candidate, candidateIndex:candidateIndex, attempt:attempt, attemptIndex:attemptIndex });
      });
    });
    return rows;
  }

  function metricsForAttempts(attempts, skippedNoTrade){
    attempts = Array.isArray(attempts) ? attempts : [];
    const realizedAttempts = attempts.filter(function(attempt){ return finiteNumber(attempt.realizedR) != null; });
    const totalR = realizedAttempts.reduce(function(sum, attempt){ return sum + Number(attempt.realizedR); }, 0);
    const totalPnL = attempts.reduce(function(sum, attempt){ return sum + (finiteNumber(attempt.realizedPnL) || 0); }, 0);
    const ratings = attempts.map(function(attempt){ return finiteNumber(attempt.review && attempt.review.entryLocationRating); }).filter(function(value){ return value != null; });
    return {
      totalR: totalR,
      averageR: realizedAttempts.length ? totalR / realizedAttempts.length : null,
      positiveRate: realizedAttempts.length ? realizedAttempts.filter(function(attempt){ return attempt.realizedR > 0; }).length / realizedAttempts.length * 100 : null,
      totalPnL: totalPnL,
      medianBarsHeld: median(attempts.map(function(attempt){ return attempt.barsHeld; })),
      attemptsUsed: attempts.length,
      skippedNoTrade: skippedNoTrade || 0,
      averageRating: ratings.length ? ratings.reduce(function(sum, value){ return sum + value; }, 0) / ratings.length : null
    };
  }

  function batchMetrics(batch){
    const attempts = allAttempts(batch).map(function(row){ return row.attempt; });
    const skippedNoTrade = (batch.candidates || []).filter(function(candidate){
      return candidate.status === 'skipped' || !(candidate.attempts || []).length;
    }).length;
    return metricsForAttempts(attempts, skippedNoTrade);
  }

  function candidateMetrics(candidate){
    const attempts = candidate && Array.isArray(candidate.attempts) ? candidate.attempts : [];
    const skippedNoTrade = candidate && (candidate.status === 'skipped' || !attempts.length) ? 1 : 0;
    return metricsForAttempts(attempts, skippedNoTrade);
  }

  function compactTickerSummaryHtml(candidate){
    const metrics = candidateMetrics(candidate);
    return '<div class="entry-trainer-ticker-summary">'
      + '<div class="entry-trainer-metric is-primary"><strong>' + esc(formatR(metrics.totalR)) + '</strong><span>Total realized R</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(formatR(metrics.averageR)) + '</strong><span>Average R per attempt</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(metrics.positiveRate == null ? '—' : metrics.positiveRate.toFixed(1) + '%') + '</strong><span>Positive-R rate</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(formatMoney(metrics.totalPnL)) + '</strong><span>Total dollar P&amp;L</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(metrics.medianBarsHeld == null ? '—' : formatNumber(metrics.medianBarsHeld, 1)) + '</strong><span>Median bars held</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + metrics.attemptsUsed + '</strong><span>Attempts used</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + (metrics.skippedNoTrade ? 'YES (1)' : 'NO (0)') + '</strong><span>Skipped / no-trade</span></div>'
      + '</div>';
  }

  function selectHtml(field, value, options, blankLabel, scope){
    const data = scope || '';
    return '<select data-review-field="' + esc(field) + '" ' + data + '>'
      + '<option value="">' + esc(blankLabel || 'Choose…') + '</option>'
      + options.map(function(option){
          const item = typeof option === 'string' ? {value:option,label:option} : option;
          return '<option value="' + esc(item.value) + '"' + (value === item.value ? ' selected' : '') + '>' + esc(item.label) + '</option>';
        }).join('')
      + '</select>';
  }

  function textFieldHtml(label, field, value, scope, placeholder, wide){
    return '<div class="entry-trainer-review-field' + (wide ? ' is-wide' : '') + '">'
      + '<label>' + esc(label) + '</label>'
      + '<textarea data-review-field="' + esc(field) + '" ' + scope + ' placeholder="' + esc(placeholder || '') + '">' + esc(value || '') + '</textarea>'
      + '</div>';
  }

  function disclosureHtml(){
    return '<div class="entry-trainer-disclosure"><strong>State disclosure:</strong> Daily OHLC cannot determine intraday sequence. Comparison diagnostics use a stop-before-high convention, so the stop bar high is excluded. Entry quality self-rating is separate from outcome: a profitable chase may be low quality, while a structured stopped entry may be high quality. If a batch is exited with a position open, that attempt is closed and captured at the currently paused daily close with exitReason <code>abandoned</code>.</div>';
  }

  function persistenceWarningHtml(){
    const warning = reviewState.persistenceWarning;
    return warning
      ? '<div class="entry-trainer-persistence-warning" role="alert"><strong>Not saved locally.</strong> ' + esc(warning.message) + '</div>'
      : '';
  }

  function renderReviewTabs(){
    const tabs = byId('entry-trainer-review-tabs');
    const batch = reviewState.batch;
    if (!tabs || !batch) return;
    const rows = [{id:'summary', label:'Batch Summary'}].concat(batch.candidates.map(function(candidate, index){
      return {id:'ticker-' + index, label:(index + 1) + '. ' + candidate.symbol};
    }));
    tabs.innerHTML = rows.map(function(row){
      return '<button type="button" class="entry-trainer-review-tab' + (reviewState.activeTab === row.id ? ' is-active' : '')
        + '" data-review-tab="' + esc(row.id) + '" role="tab" aria-selected="' + (reviewState.activeTab === row.id ? 'true' : 'false') + '">' + esc(row.label) + '</button>';
    }).join('');
  }

  function renderSummaryReview(){
    const batch = reviewState.batch;
    const metrics = batchMetrics(batch);
    const body = byId('entry-trainer-review-body');
    if (!body) return;
    const batchScope = 'data-review-scope="batch"';
    body.innerHTML = persistenceWarningHtml() + disclosureHtml()
      + '<div class="entry-trainer-summary-r">'
      + '<div class="entry-trainer-metric is-primary"><strong>' + esc(formatR(metrics.totalR)) + '</strong><span>Total realized R</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(formatR(metrics.averageR)) + '</strong><span>Average R per attempt</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(metrics.positiveRate == null ? '—' : metrics.positiveRate.toFixed(1) + '%') + '</strong><span>Positive-R rate</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(formatMoney(metrics.totalPnL)) + '</strong><span>Total dollar P&amp;L</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(metrics.medianBarsHeld == null ? '—' : formatNumber(metrics.medianBarsHeld, 1)) + '</strong><span>Median bars held</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + metrics.attemptsUsed + '</strong><span>Attempts used</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + metrics.skippedNoTrade + '</strong><span>Skipped / no-trade</span></div>'
      + '<div class="entry-trainer-metric"><strong>' + esc(metrics.averageRating == null ? '—' : metrics.averageRating.toFixed(2) + ' / 5') + '</strong><span>Self-rated entry quality</span></div>'
      + '</div>'
      + '<h4>Batch</h4>'
      + '<div class="entry-trainer-candidate-card"><strong>' + esc(batch.status) + '</strong>'
      + (batch.exitReason ? '<br>Batch exit reason: ' + esc(batch.exitReason) : '')
      + (batch.abandonReason ? '<br>Abandon reason: ' + esc(batch.abandonReason) : '') + '</div>'
      + '<div class="entry-trainer-candidate-list">' + batch.candidates.map(function(candidate){
          return '<div class="entry-trainer-candidate-card"><strong>' + esc(candidate.symbol) + '</strong><br>'
            + esc(candidate.qualificationDate) + ' qualification · ' + esc(candidate.endDate) + ' horizon<br>'
            + esc(candidate.status) + ' · ' + (candidate.attempts || []).length + ' attempt(s)'
            + (candidate.skipReason ? '<br>Skip: ' + esc(candidate.skipReason) : '')
            + (candidate.exitReason ? '<br>Exit: ' + esc(candidate.exitReason) : '') + '</div>';
        }).join('') + '</div>'
      + '<h4>Batch reflection</h4><div class="entry-trainer-review-grid">'
      + textFieldHtml('Recurring entry habit', 'recurringEntryHabit', batch.review.recurringEntryHabit, batchScope, 'What entry habit repeated across the three charts?', true)
      + textFieldHtml('Next drill focus', 'nextDrillFocus', batch.review.nextDrillFocus, batchScope, 'What will the next three-ticker drill isolate?', true)
      + '</div>';
  }

  function attemptTableHtml(candidate){
    const attempts = candidate.attempts || [];
    if (!attempts.length) return '<div class="entry-trainer-review-empty">No filled attempts for this ticker.</div>';
    return '<div class="entry-trainer-review-table-wrap"><table class="entry-trainer-review-table"><thead><tr>'
      + '<th>Attempt</th><th>Entry</th><th>Initial stop</th><th>Stop distance</th><th>Exit</th><th>Realized R</th><th>$ P&amp;L</th><th>Bars</th><th>MFE $ / R</th><th>MAE $ / R</th><th>Exit efficiency</th><th>Trail activation</th>'
      + '</tr></thead><tbody>' + attempts.map(function(attempt){
        const efficiency = exitEfficiencyRatio(attempt);
        const trail = attempt.trailActivatedAt;
        return '<tr><td>' + esc(attempt.attemptNumber) + '</td>'
          + '<td>' + esc(attempt.entryDate || attempt.fillDate || '—') + ' @ ' + esc(formatNumber(attempt.entryPrice || attempt.fillPrice, 2)) + '</td>'
          + '<td>$' + esc(formatNumber(attempt.initialStop, 2)) + '</td>'
          + '<td>' + esc(formatMoney(attempt.initialStopDistanceDollars)) + ' / ' + esc(formatNumber(attempt.initialStopDistancePct, 2)) + '%</td>'
          + '<td>' + esc(attempt.exitDate || '—') + ' @ ' + esc(formatNumber(attempt.exitPrice, 2)) + '<br>' + esc(attempt.exitReason || '—') + '</td>'
          + '<td>' + esc(formatR(attempt.realizedR)) + '</td><td>' + esc(formatMoney(attempt.realizedPnL)) + '</td><td>' + esc(attempt.barsHeld == null ? '—' : attempt.barsHeld) + '</td>'
          + '<td>' + esc(formatMoney(attempt.mfeDollars)) + ' / ' + esc(formatR(attempt.mfeR)) + '</td>'
          + '<td>' + esc(formatMoney(attempt.maeDollars)) + ' / ' + esc(formatR(attempt.maeR)) + '</td>'
          + '<td>' + esc(efficiency == null ? '—' : efficiency.toFixed(2) + '×') + '</td>'
          + '<td>' + (trail ? esc((trail.date || '—') + ' · bar ' + trail.barIdx + ' / +' + trail.barsFromEntry + ' · ' + formatR(trail.openR) + ' · ' + JSON.stringify(attempt.trailSpec || {})) : 'Not activated') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  function exitEfficiencyRatio(attempt){
    const realizedR = finiteNumber(attempt && attempt.realizedR);
    const mfeR = finiteNumber(attempt && attempt.mfeR);
    return mfeR != null && mfeR > 0 && realizedR != null ? realizedR / mfeR : null;
  }

  function orderLifecycleHtml(candidate){
    const events = candidate.orderEvents || [];
    if (!events.length) return '<div class="entry-trainer-review-empty">No limit-order lifecycle events.</div>';
    return '<div class="entry-trainer-review-table-wrap"><table class="entry-trainer-review-table"><thead><tr><th>Date</th><th>Lifecycle</th><th>Order</th><th>Qty</th><th>Requested / actual</th><th>Reason</th></tr></thead><tbody>'
      + events.map(function(event){
          const requested = orderRequestedPrice(event);
          const actual = orderActualPrice(event);
          return '<tr><td>' + esc(event.date || '—') + '</td><td>' + esc(event.type || '—') + '</td><td>' + esc(event.orderId || '—') + '</td><td>' + esc(event.qty == null ? '—' : event.qty) + '</td>'
            + '<td>' + esc(requested == null ? '—' : '$' + formatNumber(requested, 2)) + ' / ' + esc(actual == null ? '—' : '$' + formatNumber(actual, 2)) + '</td><td>' + esc(event.reason || '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
  }

  function orderRequestedPrice(event){
    const explicit = finiteNumber(event && event.requestedPrice);
    if (explicit != null) return explicit;
    const limit = finiteNumber(event && event.limitPrice);
    if (limit != null) return limit;
    return event && event.type !== 'gap_stop' ? finiteNumber(event.price) : null;
  }

  function orderActualPrice(event){
    if (!event || (event.type !== 'filled' && event.type !== 'gap_stop')) return null;
    return finiteNumber(event.fillPrice) != null ? finiteNumber(event.fillPrice) : finiteNumber(event.price);
  }

  function comparisonHtml(candidate, candidateIndex){
    const points = candidate.comparisonPoints || [];
    if (!points.length) return '<div class="entry-trainer-review-empty">No rule-labelled comparison points were detected.</div>';
    const actions = candidate.review.comparisonActionability || [];
    return '<div class="entry-trainer-review-table-wrap"><table class="entry-trainer-review-table"><thead><tr><th>Date / rule</th><th>Entry / 5-bar stop</th><th>' + esc(COMPARISON_DIAGNOSTIC_LABEL) + '</th><th>End reason</th><th>Daily-OHLC convention</th></tr></thead><tbody>'
      + points.map(function(point){
          return '<tr><td>' + esc(point.date || '—') + '<br>' + esc(point.rule || '—') + '</td><td>$' + esc(formatNumber(point.hypotheticalEntry, 2)) + ' / $' + esc(formatNumber(point.hypotheticalStop, 2)) + '</td>'
            + '<td>' + esc(formatR(point.diagnostic && point.diagnostic.mfeR)) + '</td><td>' + esc(point.diagnostic && point.diagnostic.endReason || '—') + '</td>'
            + '<td>sequencingAssumption: stop_before_high<br>stopBarHighIncluded: false</td></tr>';
        }).join('') + '</tbody></table></div>'
      + '<div class="entry-trainer-review-grid">' + points.map(function(point, pointIndex){
          const action = actions[pointIndex] || {};
          const scope = 'data-review-scope="comparison" data-candidate-index="' + candidateIndex + '" data-point-index="' + pointIndex + '"';
          return '<div class="entry-trainer-review-field"><label>' + esc((point.date || '—') + ' ' + point.rule) + ': Was this comparison point actionable using only the candles visible at that time?</label>'
            + selectHtml('actionable', action.actionable, [
                {value:'yes',label:'Yes'}, {value:'no',label:'No'}, {value:'unclear',label:'Unclear'}
              ], 'Choose…', scope) + '</div>'
            + textFieldHtml('Why / why not?', 'notes', action.notes, scope, 'Use only information visible through that candle.', false);
        }).join('') + '</div>';
  }

  function attemptReviewHtml(attempt, candidateIndex, attemptIndex){
    const review = attempt.review || emptyAttemptReview();
    const scope = 'data-review-scope="attempt" data-candidate-index="' + candidateIndex + '" data-attempt-index="' + attemptIndex + '"';
    return '<div class="entry-trainer-review-attempt"><div class="entry-trainer-review-attempt-head"><strong>Attempt ' + esc(attempt.attemptNumber) + '</strong><span>' + esc(formatR(attempt.realizedR)) + ' · ' + esc(attempt.exitReason || '—') + '</span></div>'
      + '<div class="entry-trainer-review-grid">'
      + '<div class="entry-trainer-review-field"><label>Self-rated entry quality (1–5)</label><input type="number" min="1" max="5" step="1" data-review-field="entryLocationRating" ' + scope + ' value="' + esc(review.entryLocationRating == null ? '' : review.entryLocationRating) + '"></div>'
      + '<div class="entry-trainer-review-field"><label>Stop validity</label>' + selectHtml('stopValidity', review.stopValidity, [
          {value:'structural',label:'Structural'}, {value:'too_tight',label:'Too tight'}, {value:'too_wide',label:'Too wide'}, {value:'unclear',label:'Unclear'}
        ], 'Choose…', scope) + '</div>'
      + '<div class="entry-trainer-review-field"><label>Timing</label>' + selectHtml('timing', review.timing, [
          {value:'early',label:'Early'}, {value:'well_timed',label:'Well timed'}, {value:'late',label:'Late'}
        ], 'Choose…', scope) + '</div>'
      + '<div class="entry-trainer-review-field"><label>Limit assessment</label>' + selectHtml('limitAssessment', review.limitAssessment, [
          {value:'improved',label:'Improved'}, {value:'neutral',label:'Neutral'}, {value:'hurt_confirmation',label:'Hurt confirmation'}, {value:'not_used',label:'Not used'}
        ], 'Choose…', scope) + '</div>'
      + '<div class="entry-trainer-review-field"><label>Was the EMA trail activated too early, too late, or appropriately?</label>' + selectHtml('trailTiming', review.trailTiming, [
          {value:'too_early',label:'Too early'}, {value:'too_late',label:'Too late'}, {value:'appropriate',label:'Appropriate'}, {value:'not_used',label:'Not used'}
        ], 'Choose…', scope) + '</div>'
      + '<div class="entry-trainer-review-field"><label>Did the manual exit follow observable price behavior or discomfort?</label>' + selectHtml('manualExitDriver', review.manualExitDriver, [
          {value:'price_behavior',label:'Price behavior'}, {value:'discomfort',label:'Discomfort'}, {value:'mixed',label:'Mixed'}, {value:'not_applicable',label:'Not applicable'}
        ], 'Choose…', scope) + '</div>'
      + '<div class="entry-trainer-review-field"><label>MFE retained (%)</label><input type="number" min="0" max="100" step="0.1" data-review-field="mfeRetained" ' + scope + ' value="' + esc(review.mfeRetained == null ? '' : review.mfeRetained) + '"></div>'
      + textFieldHtml('Repeat next time', 'repeatNextTime', review.repeatNextTime, scope, 'What deserves repetition?', true)
      + textFieldHtml('Change next time', 'changeNextTime', review.changeNextTime, scope, 'What specific decision changes next time?', true)
      + '</div></div>';
  }

  function renderTickerReview(candidateIndex){
    const batch = reviewState.batch;
    const candidate = batch && batch.candidates[candidateIndex];
    const body = byId('entry-trainer-review-body');
    if (!candidate || !body) return;
    const candidateScope = 'data-review-scope="candidate" data-candidate-index="' + candidateIndex + '"';
    body.innerHTML = persistenceWarningHtml() + disclosureHtml()
      + '<div class="entry-trainer-review-attempt-head"><strong>' + esc(candidate.symbol) + '</strong><span>Qualification ' + esc(candidate.qualificationDate) + ' · context ' + esc(candidate.contextStartDate) + ' · horizon ' + esc(candidate.endDate) + ' · status ' + esc(candidate.status) + '</span></div>'
      + compactTickerSummaryHtml(candidate)
      + '<div class="entry-trainer-review-chart" id="entry-trainer-review-chart"><div class="entry-trainer-review-placeholder">Loading local daily chart…</div></div>'
      + '<h4>Actual attempts</h4>' + attemptTableHtml(candidate)
      + (candidate.attempts || []).map(function(attempt, attemptIndex){ return attemptReviewHtml(attempt, candidateIndex, attemptIndex); }).join('')
      + '<h4>Order lifecycle</h4>' + orderLifecycleHtml(candidate)
      + '<h4>Comparison diagnostics</h4>' + comparisonHtml(candidate, candidateIndex)
      + '<h4>Ticker reflection</h4><div class="entry-trainer-review-grid">'
      + textFieldHtml('Better buy points', 'betterBuyPoints', candidate.review.betterBuyPoints, candidateScope, 'Which buy locations had better geometry, and why?', true)
      + textFieldHtml('Secondary entry assessment', 'secondaryEntryAssessment', candidate.review.secondaryEntryAssessment, candidateScope, 'Were later attempts genuine secondary entries or reactions to the prior outcome?', true)
      + textFieldHtml('Trail reasonableness', 'trailReasonableness', candidate.review.trailReasonableness, candidateScope, 'Was trail activation reasonable using only then-visible price behavior?', true)
      + '</div>';
    loadReviewChart(candidate);
  }

  function destroyReviewChart(){
    if (reviewState.barsController) {
      try { reviewState.barsController.abort(); } catch (error) {}
      reviewState.barsController = null;
    }
    const record = reviewState.chart;
    reviewState.chart = null;
    if (!record) return;
    if (record.resizeObserver) {
      try { record.resizeObserver.disconnect(); } catch (error) {}
    }
    try { record.chart.remove(); } catch (error) {}
  }

  function reviewMarkers(candidate){
    const markers = [];
    let sequence = 0;
    function push(date, position, color, shape, text){
      if (!date) return;
      markers.push({ time:date, position:position, color:color, shape:shape, text:text, _sequence:sequence++ });
    }
    (candidate.orderEvents || []).forEach(function(event){
      const markerPrice = finiteNumber(event.price) != null ? finiteNumber(event.price) : orderRequestedPrice(event);
      if (event.type === 'placed') push(event.date, 'belowBar', '#60a5fa', 'arrowUp', 'Limit requested ' + formatNumber(orderRequestedPrice(event), 2));
      else if (event.type === 'filled') push(event.date, 'belowBar', '#6ee7b7', 'arrowUp', 'Limit fill ' + formatNumber(orderActualPrice(event), 2));
      else if (event.type === 'gap_stop') push(event.date, 'aboveBar', '#fb7185', 'arrowDown', 'gap_stop ' + formatNumber(event.price, 2));
      else if (event.type === 'cancelled') push(event.date, 'aboveBar', '#94a3b8', 'circle', 'Limit cancelled ' + formatNumber(markerPrice, 2));
      else if (event.type === 'expired') push(event.date, 'aboveBar', '#f59e0b', 'circle', 'Limit expired ' + formatNumber(markerPrice, 2));
      else if (event.type === 'invalidated') push(event.date, 'aboveBar', '#fb7185', 'circle', 'Limit invalidated ' + formatNumber(markerPrice, 2));
    });
    (candidate.attempts || []).forEach(function(attempt){
      const prefix = 'A' + attempt.attemptNumber + ' ';
      push(attempt.entryDate || attempt.fillDate, 'belowBar', '#6ee7b7', 'arrowUp', prefix + (attempt.orderId ? 'fill ' : 'market entry ') + formatNumber(attempt.entryPrice, 2));
      push(attempt.entryDate || attempt.fillDate, 'aboveBar', '#f5c842', 'circle', prefix + 'initial stop ' + formatNumber(attempt.initialStop, 2));
      (attempt.stopEvents || []).forEach(function(event){
        if (event.type === 'initial_stop') return;
        if (event.type === 'movestop') push(event.date, 'aboveBar', event.stopTrail ? '#d4a574' : '#f5c842', 'circle', prefix + (event.stopTrail ? 'EMA trail on ' : 'stop change ') + formatNumber(event.price || event.newStop, 2));
        if (event.type === 'stop') push(event.date, 'aboveBar', '#fb7185', 'arrowDown', prefix + 'stop ' + formatNumber(event.price, 2));
      });
      if (attempt.exitReason !== 'stop') push(attempt.exitDate, 'aboveBar', '#fb7185', 'arrowDown', prefix + (attempt.exitReason || 'exit') + ' ' + formatNumber(attempt.exitPrice, 2));
    });
    (candidate.comparisonPoints || []).forEach(function(point){
      push(point.date, 'belowBar', '#a78bfa', 'circle', point.rule + ' comparison');
    });
    const seen = Object.create(null);
    return markers.sort(function(left, right){
      if (left.time !== right.time) return left.time < right.time ? -1 : 1;
      return left._sequence - right._sequence;
    }).filter(function(marker){
      const key = [marker.time, marker.position, marker.text].join('|');
      if (seen[key]) return false;
      seen[key] = true;
      delete marker._sequence;
      return true;
    });
  }

  function loadReviewChart(candidate){
    destroyReviewChart();
    const host = byId('entry-trainer-review-chart');
    if (!host) return;
    if (!window.LightweightCharts || typeof window.LightweightCharts.createChart !== 'function') {
      host.innerHTML = '<div class="entry-trainer-review-placeholder">Chart library is unavailable.</div>';
      return;
    }
    const controller = new AbortController();
    reviewState.barsController = controller;
    fetch('/api/ohlcv?symbol=' + encodeURIComponent(candidate.symbol), {signal:controller.signal, headers:{Accept:'application/json'}})
      .then(function(response){ if (!response.ok) throw new Error('HTTP ' + response.status); return response.json(); })
      .then(function(payload){
        if (reviewState.barsController !== controller || controller.signal.aborted || !host.isConnected) return;
        const source = Array.isArray(payload) ? payload : (payload && Array.isArray(payload.bars) ? payload.bars : []);
        const bars = source.filter(function(bar){
          return bar && bar.time >= candidate.contextStartDate && bar.time <= candidate.endDate
            && [bar.open, bar.high, bar.low, bar.close].every(function(value){ return finiteNumber(value) != null; });
        });
        if (!bars.length) throw new Error('No saved local bars cover the trainer window');
        host.innerHTML = '';
        let chart = null;
        let resizeObserver = null;
        try {
          chart = window.LightweightCharts.createChart(host, {
            width:host.clientWidth || 900,
            height:host.clientHeight || 390,
            layout:{background:{color:'transparent'},textColor:'#888'},
            grid:{horzLines:{color:'#1a1c22'},vertLines:{color:'#1a1c22'}},
            rightPriceScale:{borderColor:'#262932',scaleMargins:{top:0.05,bottom:0.18}},
            timeScale:{borderColor:'#262932',timeVisible:false},
            crosshair:{mode:window.LightweightCharts.CrosshairMode.Normal}
          });
          reviewState.chart = {chart:chart, resizeObserver:null};
          const candles = chart.addCandlestickSeries({
            upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'
          });
          candles.setData(bars.map(function(bar){ return {time:bar.time,open:+bar.open,high:+bar.high,low:+bar.low,close:+bar.close}; }));
          const volume = chart.addHistogramSeries({priceScaleId:'',priceFormat:{type:'volume'},scaleMargins:{top:0.85,bottom:0},color:'rgba(120,140,160,0.4)'});
          volume.setData(bars.map(function(bar){ return {time:bar.time,value:+bar.volume || 0}; }));
          try { candles.setMarkers(reviewMarkers(candidate)); } catch (error) { console.warn('[EntryTrainer] review markers:', error); }
          try { chart.timeScale().fitContent(); } catch (error) {}
          if (typeof ResizeObserver !== 'undefined') {
            resizeObserver = new ResizeObserver(function(){
              if (host.clientWidth && host.clientHeight) chart.resize(host.clientWidth, host.clientHeight);
            });
            reviewState.chart.resizeObserver = resizeObserver;
            resizeObserver.observe(host);
          }
          reviewState.barsController = null;
        } catch (error) {
          if (resizeObserver) {
            try { resizeObserver.disconnect(); } catch (disconnectError) {}
          }
          if (chart) {
            try { chart.remove(); } catch (removeError) {}
          }
          if (reviewState.chart && reviewState.chart.chart === chart) reviewState.chart = null;
          if (reviewState.barsController === controller) reviewState.barsController = null;
          throw error;
        }
      })
      .catch(function(error){
        if (error && error.name === 'AbortError') return;
        if (reviewState.barsController === controller) reviewState.barsController = null;
        if (host.isConnected) host.innerHTML = '<div class="entry-trainer-review-placeholder">Could not load ' + esc(candidate.symbol) + ' from local OHLCV: ' + esc(error && error.message || error) + '</div>';
      });
  }

  function renderReview(){
    destroyReviewChart();
    renderReviewTabs();
    if (reviewState.activeTab === 'summary') renderSummaryReview();
    else {
      const index = Number(reviewState.activeTab.replace('ticker-', ''));
      renderTickerReview(index);
    }
  }

  function setReviewStatus(message, saved){
    const node = byId('entry-trainer-review-status');
    if (!node) return;
    node.textContent = message || '';
    node.classList.toggle('is-saved', !!saved);
  }

  function markReviewDirty(){
    reviewState.dirty = true;
    setReviewStatus('Unsaved changes', false);
  }

  function updateReviewField(target){
    if (!target || !target.dataset || !target.dataset.reviewField || !reviewState.batch) return;
    const field = target.dataset.reviewField;
    const scope = target.dataset.reviewScope;
    const candidateIndex = Number(target.dataset.candidateIndex);
    const attemptIndex = Number(target.dataset.attemptIndex);
    const pointIndex = Number(target.dataset.pointIndex);
    let owner = null;
    if (scope === 'batch') owner = reviewState.batch.review;
    if (scope === 'candidate' && reviewState.batch.candidates[candidateIndex]) owner = reviewState.batch.candidates[candidateIndex].review;
    if (scope === 'attempt' && reviewState.batch.candidates[candidateIndex] && reviewState.batch.candidates[candidateIndex].attempts[attemptIndex]) owner = reviewState.batch.candidates[candidateIndex].attempts[attemptIndex].review;
    if (scope === 'comparison' && reviewState.batch.candidates[candidateIndex]) owner = reviewState.batch.candidates[candidateIndex].review.comparisonActionability[pointIndex];
    if (!owner) return;
    let value = target.value;
    if (field === 'entryLocationRating') {
      const number = safeInteger(value, 1);
      value = number != null && number <= 5 ? number : null;
    } else if (field === 'mfeRetained') {
      const number = finiteNumber(value);
      value = number != null && number >= 0 && number <= 100 ? number : null;
    } else if (field === 'actionable') {
      value = safeEnum(value, REVIEW_ENUMS.comparisonActionable);
    } else if (REVIEW_ENUMS[field]) {
      value = safeEnum(value, REVIEW_ENUMS[field]);
    } else value = safeText(value);
    owner[field] = value;
    markReviewDirty();
  }

  function saveCurrentReview(){
    if (!reviewState.batch) return false;
    const result = saveBatch(reviewState.batch);
    if (!result.record) {
      setReviewStatus('Save failed · export available', false);
      return false;
    }
    reviewState.batch = result.record;
    if (state.lastBatch && state.lastBatch.id === result.record.id) state.lastBatch = clone(result.record);
    if (!result.ok) {
      state.lastBatch = clone(result.record);
      lastPersistenceFailure = {
        batchId:result.record.id,
        quota:result.quota,
        message:result.quota
          ? 'This batch is not saved because browser storage is full. Delete older saved batches, then choose Save Review to retry.'
          : 'This batch is not saved because browser storage failed. Choose Save Review to retry or export it now.'
      };
      reviewState.persistenceWarning = clone(lastPersistenceFailure);
      reviewState.dirty = true;
      setReviewStatus(result.quota ? 'Not saved · storage full' : 'Not saved · storage error', false);
      renderReview();
      renderReviewSavedBatches();
      return false;
    }
    if (lastPersistenceFailure && lastPersistenceFailure.batchId === result.record.id) lastPersistenceFailure = null;
    reviewState.persistenceWarning = null;
    reviewState.dirty = false;
    setReviewStatus('Saved', true);
    if (!refreshSavedBatchRows(result.record)) renderSavedBatches();
    renderReviewSavedBatches();
    renderReview();
    return true;
  }

  function restoreReviewEnvironment(modal){
    (reviewState.backgroundInert || []).forEach(function(item){
      if (!item.node || !item.node.isConnected) return;
      item.node.inert = item.inert;
      if (item.hadAttribute) item.node.setAttribute('inert', '');
      else item.node.removeAttribute('inert');
    });
    const parent = reviewState.modalParent;
    const sibling = reviewState.modalNextSibling;
    if (modal && parent && parent.isConnected) {
      if (sibling && sibling.parentNode === parent) parent.insertBefore(modal, sibling);
      else parent.appendChild(modal);
    }
  }

  function closeReview(){
    if (reviewState.batch && (reviewState.dirty || reviewState.persistenceWarning) && !saveCurrentReview()) {
      setReviewStatus('Not saved · review remains open', false);
      if (!window.confirm('This review is not saved locally. It remains available during this page session, and you can export it now. Close anyway?')) return false;
    }
    destroyReviewChart();
    const modal = byId('entry-trainer-review-modal');
    if (modal) {
      modal.classList.remove('open');
      modal.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('entry-trainer-review-open');
    const tabs = byId('entry-trainer-review-tabs');
    const body = byId('entry-trainer-review-body');
    const storage = byId('entry-trainer-review-storage');
    const manage = byId('entry-trainer-review-manage');
    if (tabs) tabs.innerHTML = '';
    if (body) body.innerHTML = '';
    storage?.classList.remove('is-visible');
    if (manage) manage.setAttribute('aria-expanded', 'false');
    setReviewStatus('', false);
    const opener = reviewState.opener;
    const reopenSetup = !!(opener && opener.closest && opener.closest('#entry-trainer-setup-modal'));
    restoreReviewEnvironment(modal);
    reviewState = {
      batch:null,activeTab:'summary',chart:null,barsController:null,dirty:false,opener:null,
      persistenceWarning:null,backgroundInert:[],modalParent:null,modalNextSibling:null
    };
    if (reopenSetup) setSetupOpen(true, {preserveFocus:true});
    if (opener && opener.isConnected && typeof opener.focus === 'function') opener.focus();
    else if (reopenSetup) byId('entry-trainer-saved')?.focus();
    return true;
  }

  function deleteSavedBatch(batchId){
    const id = safeId(batchId);
    if (!id || !window.confirm('Delete this saved Entry Trainer batch? This cannot be undone.')) return false;
    const records = readSavedBatches();
    const remaining = records.filter(function(record){ return record.id !== id; });
    if (remaining.length === records.length) return false;
    const result = writeSavedBatches(remaining);
    if (!result.ok) {
      if (reviewState.batch) setReviewStatus('Could not delete saved batch', false);
      else setSetupStatus('Could not delete the saved batch from local browser storage.', true);
      return false;
    }
    if (reviewState.batch && reviewState.batch.id === id) {
      state.lastBatch = clone(reviewState.batch);
      lastPersistenceFailure = {
        batchId:id,
        quota:false,
        message:'This open batch was deleted from local storage. Choose Save Review to save it again, or export it now.'
      };
      reviewState.persistenceWarning = clone(lastPersistenceFailure);
      reviewState.dirty = true;
      setReviewStatus('Deleted locally · save to restore', false);
      renderReview();
    }
    document.querySelectorAll('[data-saved-batch-id="' + id.replace(/"/g, '') + '"]').forEach(function(row){ row.remove(); });
    [byId('entry-trainer-saved-list'), byId('entry-trainer-review-saved-list')].forEach(function(host){
      if (host && !host.querySelector('.entry-trainer-saved-row')) {
        host.innerHTML = '<div class="entry-trainer-saved-empty">No completed or abandoned batches saved yet.</div>';
      }
    });
    renderReviewSavedBatches();
    if (reviewState.persistenceWarning) setReviewStatus('Storage freed · choose Save Review', false);
    return true;
  }

  function reviewableBatchRows(){
    const stored = readSavedBatches();
    const rows = stored.map(function(record){ return {record:record, unsaved:false, persisted:true}; });
    if (lastPersistenceFailure && state.lastBatch && state.lastBatch.id === lastPersistenceFailure.batchId) {
      const current = sanitizePersistedBatch(state.lastBatch);
      if (current) {
        const index = rows.findIndex(function(item){ return item.record.id === current.id; });
        const row = {record:current, unsaved:true, persisted:index >= 0};
        if (index >= 0) rows.splice(index, 1);
        rows.unshift(row);
      }
    }
    return rows;
  }

  function savedBatchButtonLabel(record, unsaved){
    const metric = batchMetrics(record);
    return (unsaved ? 'NOT SAVED · ' : '') + record.status.toUpperCase() + ' · '
      + record.candidates.map(function(candidate){ return candidate.symbol; }).join(' / ') + ' · ' + formatR(metric.totalR);
  }

  function refreshSavedBatchRows(record){
    const selector = '[data-saved-batch-id="' + record.id.replace(/"/g, '') + '"]';
    const rows = Array.from(document.querySelectorAll(selector));
    rows.forEach(function(row){
      const openButton = row.querySelector('button:not(.entry-trainer-saved-delete)');
      const priorAction = row.children[2];
      if (openButton) openButton.textContent = savedBatchButtonLabel(record, false);
      if (priorAction) priorAction.remove();
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'entry-trainer-saved-delete';
      remove.textContent = 'Delete';
      remove.setAttribute('aria-label', 'Delete saved batch ' + record.id);
      remove.addEventListener('click', function(){ deleteSavedBatch(record.id); });
      row.appendChild(remove);
    });
    return rows.length;
  }

  function renderSavedBatchRows(host, rows){
    if (!host) return;
    host.innerHTML = '';
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'entry-trainer-saved-empty';
      empty.textContent = 'No completed or abandoned batches saved yet.';
      host.appendChild(empty);
      return;
    }
    rows.forEach(function(item){
      const record = item.record;
      const row = document.createElement('div');
      row.className = 'entry-trainer-saved-row';
      row.dataset.savedBatchId = record.id;
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = savedBatchButtonLabel(record, item.unsaved);
      button.addEventListener('click', function(){
        openReview(record.id, {opener:button});
      });
      const meta = document.createElement('span');
      meta.className = 'entry-trainer-saved-meta';
      meta.textContent = (record.completedAt || record.abandonedAt || record.createdAt).slice(0, 10);
      row.appendChild(button);
      row.appendChild(meta);
      if (item.persisted) {
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'entry-trainer-saved-delete';
        remove.textContent = 'Delete';
        remove.setAttribute('aria-label', 'Delete saved batch ' + record.id);
        remove.addEventListener('click', function(){ deleteSavedBatch(record.id); });
        row.appendChild(remove);
      } else {
        const retry = document.createElement('span');
        retry.className = 'entry-trainer-saved-meta';
        retry.textContent = 'Open to retry';
        row.appendChild(retry);
      }
      host.appendChild(row);
    });
  }

  function renderSavedBatches(){
    renderSavedBatchRows(byId('entry-trainer-saved-list'), reviewableBatchRows());
  }

  function renderReviewSavedBatches(){
    renderSavedBatchRows(byId('entry-trainer-review-saved-list'), reviewableBatchRows());
  }

  function toggleSavedBatches(){
    const host = byId('entry-trainer-saved-list');
    const button = byId('entry-trainer-saved');
    if (!host || !button) return false;
    const visible = !host.classList.contains('is-visible');
    host.classList.toggle('is-visible', visible);
    button.setAttribute('aria-expanded', visible ? 'true' : 'false');
    if (visible) renderSavedBatches();
    return true;
  }

  function activateReviewEnvironment(modal){
    reviewState.modalParent = modal.parentNode;
    reviewState.modalNextSibling = modal.nextSibling;
    document.body.appendChild(modal);
    reviewState.backgroundInert = Array.from(document.body.children).filter(function(node){ return node !== modal; }).map(function(node){
      const snapshot = {node:node, inert:!!node.inert, hadAttribute:node.hasAttribute('inert')};
      node.inert = true;
      node.setAttribute('inert', '');
      return snapshot;
    });
  }

  function openReview(batchId, options){
    options = options || {};
    if (isActive()) return false;
    const id = safeId(batchId || (state.lastBatch && state.lastBatch.id));
    if (!id) return false;
    let target = state.lastBatch && state.lastBatch.id === id ? sanitizePersistedBatch(state.lastBatch) : null;
    if (!target) target = readSavedBatches().find(function(record){ return record.id === id; }) || null;
    if (!target) return false;
    const modal = byId('entry-trainer-review-modal');
    if (!modal) return false;
    const alreadyOpen = modal.classList.contains('open');
    if (alreadyOpen && reviewState.batch && reviewState.batch.id === id) return true;
    if (alreadyOpen && reviewState.batch && reviewState.batch.id !== id
        && (reviewState.dirty || reviewState.persistenceWarning) && !saveCurrentReview()
        && !window.confirm('The current review is not saved locally. Switch batches anyway?')) return false;
    const environment = alreadyOpen ? {
      opener:reviewState.opener,
      backgroundInert:reviewState.backgroundInert,
      modalParent:reviewState.modalParent,
      modalNextSibling:reviewState.modalNextSibling
    } : null;
    const opener = options.opener || document.activeElement;
    if (!alreadyOpen) setSetupOpen(false, {restoreFocus:false});
    destroyReviewChart();
    reviewState = {
      batch:clone(target),
      activeTab:'summary',
      chart:null,
      barsController:null,
      dirty:false,
      opener:environment ? environment.opener : opener,
      persistenceWarning:lastPersistenceFailure && lastPersistenceFailure.batchId === id ? clone(lastPersistenceFailure) : null,
      backgroundInert:environment ? environment.backgroundInert : [],
      modalParent:environment ? environment.modalParent : null,
      modalNextSibling:environment ? environment.modalNextSibling : null
    };
    if (!alreadyOpen) activateReviewEnvironment(modal);
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('entry-trainer-review-open');
    setReviewStatus(reviewState.persistenceWarning
      ? (reviewState.persistenceWarning.quota ? 'Not saved · storage full' : 'Not saved · storage error')
      : 'Saved', !reviewState.persistenceWarning);
    renderReviewSavedBatches();
    renderReview();
    byId('entry-trainer-review-close')?.focus();
    return true;
  }

  function mdCell(value){
    return safeText(value, 12000).replace(/\\/g, '\\\\').replace(/\|/g, '\\|').replace(/\r?\n/g, '<br>');
  }

  function reviewValue(value){
    if (value == null || value === '') return '—';
    return String(value);
  }

  function buildMarkdown(batch){
    const metrics = batchMetrics(batch);
    const lines = [];
    lines.push('# Entry Trainer Batch Review');
    lines.push('');
    lines.push('- **Batch ID:** ' + mdCell(batch.id));
    lines.push('- **Status:** ' + mdCell(batch.status));
    lines.push('- **Batch exit reason:** ' + mdCell(batch.exitReason || '—'));
    lines.push('- **Abandon reason:** ' + mdCell(batch.abandonReason || '—'));
    lines.push('- **Created:** ' + mdCell(batch.createdAt));
    lines.push('- **Finished:** ' + mdCell(batch.completedAt || batch.abandonedAt || '—'));
    lines.push('');
    lines.push('> Daily OHLC cannot determine intraday sequence. Comparison diagnostics use sequencingAssumption `stop_before_high`; `stopBarHighIncluded` is false. Entry quality self-rating is separate from outcome: a profitable chase may be low quality, while a structured stopped entry may be high quality. Early batch exit closes and captures an open attempt at the currently paused daily close with exitReason `abandoned`.');
    lines.push('');
    lines.push('## R-first summary');
    lines.push('');
    lines.push('| Metric | Value |');
    lines.push('|---|---:|');
    lines.push('| Total realized R | ' + formatR(metrics.totalR) + ' |');
    lines.push('| Average R per attempt | ' + formatR(metrics.averageR) + ' |');
    lines.push('| Positive-R rate | ' + (metrics.positiveRate == null ? '—' : metrics.positiveRate.toFixed(1) + '%') + ' |');
    lines.push('| Total dollar P&L | ' + formatMoney(metrics.totalPnL) + ' |');
    lines.push('| Median bars held | ' + (metrics.medianBarsHeld == null ? '—' : formatNumber(metrics.medianBarsHeld, 1)) + ' |');
    lines.push('| Attempts used | ' + metrics.attemptsUsed + ' |');
    lines.push('| Skipped / no-trade | ' + metrics.skippedNoTrade + ' |');
    lines.push('| Self-rated entry quality | ' + (metrics.averageRating == null ? '—' : metrics.averageRating.toFixed(2) + ' / 5') + ' |');
    lines.push('');
    lines.push('## Drill configuration');
    lines.push('');
    lines.push('- **Starting equity (sizing/notional validation only):** ' + formatMoney(batch.startingEquity));
    lines.push('- **Rules snapshot:** `' + JSON.stringify(batch.rules) + '`');
    lines.push('');
    lines.push('## Batch reflection');
    lines.push('');
    lines.push('- **Recurring entry habit:** ' + mdCell(reviewValue(batch.review.recurringEntryHabit)));
    lines.push('- **Next drill focus:** ' + mdCell(reviewValue(batch.review.nextDrillFocus)));
    lines.push('');
    (batch.candidates || []).forEach(function(candidate){
      lines.push('## ' + mdCell(candidate.symbol));
      lines.push('');
      lines.push('- **Window:** ' + mdCell(candidate.contextStartDate) + ' → ' + mdCell(candidate.endDate));
      lines.push('- **Qualification date:** ' + mdCell(candidate.qualificationDate));
      lines.push('- **Status:** ' + mdCell(candidate.status));
      if (candidate.skipReason) lines.push('- **Skip reason:** ' + mdCell(candidate.skipReason));
      if (candidate.finishReason) lines.push('- **Finish reason:** ' + mdCell(candidate.finishReason));
      if (candidate.exitReason) lines.push('- **Exit reason:** ' + mdCell(candidate.exitReason));
      lines.push('');
      lines.push('### Actual attempts');
      lines.push('');
      if (!(candidate.attempts || []).length) lines.push('_No filled attempts._');
      else {
        lines.push('| # | Entry | Initial stop | Stop distance $ / % | Exit | Reason | Realized R | $ P&L | Bars | MFE $ / R | MAE $ / R | Exit efficiency | Trail activation |');
        lines.push('|---:|---|---:|---|---|---|---:|---:|---:|---|---|---:|---|');
        candidate.attempts.forEach(function(attempt){
          const efficiency = exitEfficiencyRatio(attempt);
          const trail = attempt.trailActivatedAt;
          lines.push('| ' + attempt.attemptNumber
            + ' | ' + mdCell(attempt.entryDate || attempt.fillDate || '—') + ' @ ' + formatNumber(attempt.entryPrice || attempt.fillPrice, 2)
            + ' | ' + formatNumber(attempt.initialStop, 2)
            + ' | ' + formatMoney(attempt.initialStopDistanceDollars) + ' / ' + formatNumber(attempt.initialStopDistancePct, 2) + '%'
            + ' | ' + mdCell(attempt.exitDate || '—') + ' @ ' + formatNumber(attempt.exitPrice, 2)
            + ' | ' + mdCell(attempt.exitReason || '—')
            + ' | ' + formatR(attempt.realizedR)
            + ' | ' + formatMoney(attempt.realizedPnL)
            + ' | ' + reviewValue(attempt.barsHeld)
            + ' | ' + formatMoney(attempt.mfeDollars) + ' / ' + formatR(attempt.mfeR)
            + ' | ' + formatMoney(attempt.maeDollars) + ' / ' + formatR(attempt.maeR)
            + ' | ' + (efficiency == null ? '—' : efficiency.toFixed(2) + '×')
            + ' | ' + (trail ? mdCell((trail.date || '—') + ', bar ' + trail.barIdx + ' / +' + trail.barsFromEntry + ', ' + formatR(trail.openR) + ', ' + JSON.stringify(attempt.trailSpec || {})) : 'Not activated') + ' |');
        });
      }
      lines.push('');
      candidate.attempts.forEach(function(attempt){
        const review = attempt.review || emptyAttemptReview();
        lines.push('#### Attempt ' + attempt.attemptNumber + ' structured review');
        lines.push('');
        lines.push('- **entryLocationRating:** ' + reviewValue(review.entryLocationRating));
        lines.push('- **stopValidity:** ' + mdCell(reviewValue(review.stopValidity)));
        lines.push('- **timing:** ' + mdCell(reviewValue(review.timing)));
        lines.push('- **limitAssessment:** ' + mdCell(reviewValue(review.limitAssessment)));
        lines.push('- **repeatNextTime:** ' + mdCell(reviewValue(review.repeatNextTime)));
        lines.push('- **changeNextTime:** ' + mdCell(reviewValue(review.changeNextTime)));
        lines.push('- **trailTiming:** ' + mdCell(reviewValue(review.trailTiming)));
        lines.push('- **manualExitDriver:** ' + mdCell(reviewValue(review.manualExitDriver)));
        lines.push('- **mfeRetained:** ' + (review.mfeRetained == null ? '—' : formatNumber(review.mfeRetained, 1) + '%'));
        lines.push('');
      });
      lines.push('### Order lifecycle');
      lines.push('');
      if (!(candidate.orderEvents || []).length) lines.push('_No limit-order lifecycle events._');
      else {
        lines.push('| Date | Type | Order ID | Qty | Requested limit | Actual / price | Reason |');
        lines.push('|---|---|---|---:|---:|---:|---|');
        candidate.orderEvents.forEach(function(event){
          lines.push('| ' + mdCell(event.date || '—') + ' | ' + mdCell(event.type || '—') + ' | ' + mdCell(event.orderId || '—')
            + ' | ' + reviewValue(event.qty) + ' | ' + formatNumber(orderRequestedPrice(event), 2)
            + ' | ' + formatNumber(orderActualPrice(event), 2) + ' | ' + mdCell(event.reason || '—') + ' |');
        });
      }
      lines.push('');
      lines.push('### Comparison diagnostics');
      lines.push('');
      if (!(candidate.comparisonPoints || []).length) lines.push('_No rule-labelled comparison points._');
      else {
        lines.push('| Date | Rule label | Entry | 5-bar stop | Hindsight MFE R using 5-bar-low stop | endReason | sequencingAssumption | stopBarHighIncluded | Actionable then? | Notes |');
        lines.push('|---|---|---:|---:|---:|---|---|---|---|---|');
        candidate.comparisonPoints.forEach(function(point, index){
          const action = candidate.review.comparisonActionability[index] || {};
          lines.push('| ' + mdCell(point.date || '—') + ' | ' + mdCell(point.rule || '—') + ' | ' + formatNumber(point.hypotheticalEntry, 2)
            + ' | ' + formatNumber(point.hypotheticalStop, 2) + ' | ' + formatR(point.diagnostic && point.diagnostic.mfeR)
            + ' | ' + mdCell(point.diagnostic && point.diagnostic.endReason || '—') + ' | stop_before_high | false | '
            + mdCell(reviewValue(action.actionable)) + ' | ' + mdCell(reviewValue(action.notes)) + ' |');
        });
      }
      lines.push('');
      lines.push('### Ticker reflection');
      lines.push('');
      lines.push('- **betterBuyPoints:** ' + mdCell(reviewValue(candidate.review.betterBuyPoints)));
      lines.push('- **secondaryEntryAssessment:** ' + mdCell(reviewValue(candidate.review.secondaryEntryAssessment)));
      lines.push('- **trailReasonableness:** ' + mdCell(reviewValue(candidate.review.trailReasonableness)));
      lines.push('');
    });
    return lines.join('\n');
  }

  function csvEscape(value){
    if (value == null) return '';
    let text = String(value);
    if (typeof value === 'string' && /^[\t\r\n ]*[=+\-@]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }

  function buildCsv(batch){
    const columns = [
      'schema_version','row_type','batch_id','batch_status','batch_exit_reason','batch_abandon_reason','batch_created_at','batch_finished_at',
      'total_realized_r','average_r_per_attempt','positive_r_rate_pct','total_realized_pnl_dollars','median_bars_held','attempts_used','skipped_no_trade_count','self_rated_entry_quality',
      'starting_equity_dollars','recurring_entry_habit','next_drill_focus','candidate_symbol','candidate_status','qualification_date','context_start_date','horizon_end_date','skip_reason','finish_reason','candidate_exit_reason',
      'attempt_number','entry_date','entry_price_dollars','requested_price_dollars','fill_price_dollars','initial_stop_dollars','initial_stop_distance_dollars','initial_stop_distance_pct','initial_risk_dollars','quantity','exit_date','exit_price_dollars','exit_reason','realized_r','realized_pnl_dollars','bars_held','mfe_dollars','mfe_r','mae_dollars','mae_r','exit_efficiency_ratio','trail_activation_date','trail_activation_bar','trail_spec','trail_activation_open_r',
      'entry_location_rating','stop_validity','timing','limit_assessment','repeat_next_time','change_next_time','trail_timing','manual_exit_driver','mfe_retained_pct','better_buy_points','secondary_entry_assessment','trail_reasonableness',
      'order_event_type','order_id','order_event_date','order_event_bar','order_qty','order_requested_limit_dollars','order_actual_price_dollars','order_reason',
      'comparison_rule_label','comparison_date','comparison_entry_dollars','comparison_5_bar_stop_dollars','hindsight_mfe_r_using_5_bar_low_stop','comparison_end_reason','sequencing_assumption','stop_bar_high_included','comparison_actionable_then','comparison_actionability_notes','candidates_status_json'
    ];
    const metrics = batchMetrics(batch);
    const finishedAt = batch.completedAt || batch.abandonedAt || '';
    const base = {
      schema_version:BATCH_VERSION,batch_id:batch.id,batch_status:batch.status,batch_exit_reason:batch.exitReason,
      batch_abandon_reason:batch.abandonReason,batch_created_at:batch.createdAt,batch_finished_at:finishedAt,
      starting_equity_dollars:batch.startingEquity,recurring_entry_habit:batch.review.recurringEntryHabit,next_drill_focus:batch.review.nextDrillFocus
    };
    const rows = [];
    rows.push(Object.assign({}, base, {
      row_type:'batch',total_realized_r:metrics.totalR,average_r_per_attempt:metrics.averageR,positive_r_rate_pct:metrics.positiveRate,
      total_realized_pnl_dollars:metrics.totalPnL,median_bars_held:metrics.medianBarsHeld,attempts_used:metrics.attemptsUsed,
      skipped_no_trade_count:metrics.skippedNoTrade,self_rated_entry_quality:metrics.averageRating,
      candidates_status_json:JSON.stringify(batch.candidates.map(function(candidate){
        return {symbol:candidate.symbol,status:candidate.status,skipReason:candidate.skipReason,finishReason:candidate.finishReason,exitReason:candidate.exitReason,attempts:(candidate.attempts || []).length};
      }))
    }));
    batch.candidates.forEach(function(candidate){
      const candidateBase = Object.assign({}, base, {
        candidate_symbol:candidate.symbol,candidate_status:candidate.status,qualification_date:candidate.qualificationDate,
        context_start_date:candidate.contextStartDate,horizon_end_date:candidate.endDate,skip_reason:candidate.skipReason,
        finish_reason:candidate.finishReason,candidate_exit_reason:candidate.exitReason,better_buy_points:candidate.review.betterBuyPoints,
        secondary_entry_assessment:candidate.review.secondaryEntryAssessment,trail_reasonableness:candidate.review.trailReasonableness
      });
      (candidate.attempts || []).forEach(function(attempt){
        const review = attempt.review || emptyAttemptReview();
        const trail = attempt.trailActivatedAt || {};
        rows.push(Object.assign({}, candidateBase, {
          row_type:'attempt',attempt_number:attempt.attemptNumber,entry_date:attempt.entryDate || attempt.fillDate,
          entry_price_dollars:attempt.entryPrice,requested_price_dollars:attempt.requestedPrice,fill_price_dollars:attempt.fillPrice,
          initial_stop_dollars:attempt.initialStop,initial_stop_distance_dollars:attempt.initialStopDistanceDollars,
          initial_stop_distance_pct:attempt.initialStopDistancePct,initial_risk_dollars:attempt.initialRisk,quantity:attempt.quantity,
          exit_date:attempt.exitDate,exit_price_dollars:attempt.exitPrice,exit_reason:attempt.exitReason,realized_r:attempt.realizedR,
          realized_pnl_dollars:attempt.realizedPnL,bars_held:attempt.barsHeld,mfe_dollars:attempt.mfeDollars,mfe_r:attempt.mfeR,
          mae_dollars:attempt.maeDollars,mae_r:attempt.maeR,exit_efficiency_ratio:exitEfficiencyRatio(attempt),
          trail_activation_date:trail.date,trail_activation_bar:trail.barIdx,trail_spec:attempt.trailSpec ? JSON.stringify(attempt.trailSpec) : '',trail_activation_open_r:trail.openR,
          entry_location_rating:review.entryLocationRating,stop_validity:review.stopValidity,timing:review.timing,
          limit_assessment:review.limitAssessment,repeat_next_time:review.repeatNextTime,change_next_time:review.changeNextTime,
          trail_timing:review.trailTiming,manual_exit_driver:review.manualExitDriver,mfe_retained_pct:review.mfeRetained
        }));
      });
      (candidate.orderEvents || []).forEach(function(event){
        rows.push(Object.assign({}, candidateBase, {
          row_type:'order_event',order_event_type:event.type,order_id:event.orderId,order_event_date:event.date,order_event_bar:event.barIdx,
          order_qty:event.qty,order_requested_limit_dollars:orderRequestedPrice(event),
          order_actual_price_dollars:orderActualPrice(event),order_reason:event.reason
        }));
      });
      (candidate.comparisonPoints || []).forEach(function(point, index){
        const action = candidate.review.comparisonActionability[index] || {};
        rows.push(Object.assign({}, candidateBase, {
          row_type:'comparison',comparison_rule_label:point.rule,comparison_date:point.date,comparison_entry_dollars:point.hypotheticalEntry,
          comparison_5_bar_stop_dollars:point.hypotheticalStop,hindsight_mfe_r_using_5_bar_low_stop:point.diagnostic && point.diagnostic.mfeR,
          comparison_end_reason:point.diagnostic && point.diagnostic.endReason,sequencing_assumption:'stop_before_high',stop_bar_high_included:false,
          comparison_actionable_then:action.actionable,comparison_actionability_notes:action.notes
        }));
      });
    });
    return [columns.map(csvEscape).join(',')].concat(rows.map(function(row){
      return columns.map(function(column){ return csvEscape(row[column]); }).join(',');
    })).join('\r\n');
  }

  function downloadReviewFile(contents, filename, mime){
    try {
      const blob = new Blob([contents], {type:mime + ';charset=utf-8'});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      setTimeout(function(){
        try { document.body.removeChild(anchor); } catch (error) {}
        try { URL.revokeObjectURL(url); } catch (error) {}
      }, 100);
      return true;
    } catch (error) {
      console.error('[EntryTrainer] export failed:', error);
      return false;
    }
  }

  function exportMarkdown(){
    if (!reviewState.batch) return false;
    const filename = 'entry_trainer_' + reviewState.batch.createdAt.slice(0, 10) + '_' + reviewState.batch.id.replace(/[^A-Za-z0-9_-]/g, '_') + '.md';
    const ok = downloadReviewFile(buildMarkdown(clone(reviewState.batch)), filename, 'text/markdown');
    const unsaved = reviewState.dirty || reviewState.persistenceWarning;
    setReviewStatus(ok ? (unsaved ? 'Exported · not saved locally' : 'Saved · exported') : 'Export failed', ok && !unsaved);
    return ok;
  }

  function exportCsv(){
    if (!reviewState.batch) return false;
    const filename = 'entry_trainer_' + reviewState.batch.createdAt.slice(0, 10) + '_' + reviewState.batch.id.replace(/[^A-Za-z0-9_-]/g, '_') + '.csv';
    const ok = downloadReviewFile(buildCsv(clone(reviewState.batch)), filename, 'text/csv');
    const unsaved = reviewState.dirty || reviewState.persistenceWarning;
    setReviewStatus(ok ? (unsaved ? 'Exported · not saved locally' : 'Saved · exported') : 'Export failed', ok && !unsaved);
    return ok;
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
    byId('entry-trainer-saved')?.addEventListener('click', toggleSavedBatches);
    byId('entry-trainer-start')?.addEventListener('click', startFromSetup);
    byId('entry-trainer-wait')?.addEventListener('click', waitOneBar);
    byId('entry-trainer-enter')?.addEventListener('click', enterAtClose);
    byId('entry-trainer-cancel-order')?.addEventListener('click', cancelPendingOrder);
    byId('entry-trainer-skip')?.addEventListener('click', skipTicker);
    byId('entry-trainer-try-again')?.addEventListener('click', tryAgain);
    byId('entry-trainer-finish')?.addEventListener('click', function(){ finishTicker(); });
    byId('entry-trainer-exit')?.addEventListener('click', exit);
    byId('entry-trainer-review-close')?.addEventListener('click', closeReview);
    byId('entry-trainer-review-save')?.addEventListener('click', saveCurrentReview);
    byId('entry-trainer-review-manage')?.addEventListener('click', function(){
      const panel = byId('entry-trainer-review-storage');
      const button = byId('entry-trainer-review-manage');
      if (!panel || !button) return;
      const visible = !panel.classList.contains('is-visible');
      panel.classList.toggle('is-visible', visible);
      button.setAttribute('aria-expanded', visible ? 'true' : 'false');
      if (visible) renderReviewSavedBatches();
    });
    byId('entry-trainer-review-md')?.addEventListener('click', exportMarkdown);
    byId('entry-trainer-review-csv')?.addEventListener('click', exportCsv);
    byId('entry-trainer-review-tabs')?.addEventListener('click', function(event){
      const button = event.target && event.target.closest('[data-review-tab]');
      if (!button || !reviewState.batch) return;
      reviewState.activeTab = button.dataset.reviewTab;
      renderReview();
    });
    byId('entry-trainer-review-body')?.addEventListener('input', function(event){ updateReviewField(event.target); });
    byId('entry-trainer-review-body')?.addEventListener('change', function(event){ updateReviewField(event.target); });
    modal.addEventListener('click', function(event){
      if (event.target === modal) cancelSetup();
    });
    byId('entry-trainer-review-modal')?.addEventListener('click', function(event){
      if (event.target === event.currentTarget) closeReview();
    });
    byId('entry-trainer-equity')?.addEventListener('keydown', function(event){
      if (event.key === 'Enter') {
        event.preventDefault();
        startFromSetup();
      }
    });
    window.addEventListener('keydown', function(event){
      if (handleReviewKeydown(event)) return;
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
