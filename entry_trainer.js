(function(){
  'use strict';

  const BATCH_VERSION = 1;
  const BATCH_SIZE = 3;
  const MAX_ATTEMPTS = 3;
  const DEFAULT_EQUITY = 300000;
  const MASK_OWNER = 'entry-trainer';
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
      qualificationDate,
      qualificationBar,
      contextStartDate,
      endDate,
      status: 'pending',
      attempts: [],
      order: { status:'none', activity:[] }
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
      status: 'loading',
      activeIndex: 0,
      candidates: descriptors.candidates.map(function(candidate){ return clone(candidate); })
    };
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
    if (ticker) ticker.textContent = 'Ticker ' + (batch.activeIndex + 1) + ' of ' + BATCH_SIZE;
    if (attempts) attempts.textContent = 'Attempt ' + Math.min(candidate.attempts.length, MAX_ATTEMPTS) + ' of ' + MAX_ATTEMPTS;
    if (status) {
      status.textContent = batch.status === 'completed'
        ? 'Batch shell complete. Trade execution and review are not available in this shell yet.'
        : 'Qualification day · 85 prior daily bars shown · Wait and Enter are not available in this shell yet.';
    }
    const skip = byId('entry-trainer-skip');
    if (skip) skip.disabled = batch.status !== 'active';
    const launch = byId('entry-trainer-btn');
    if (launch) launch.setAttribute('aria-pressed', 'true');
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
    runtime.sessionStarted = true;
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
    runtime.fullBars = fullBars;
    runtime.qualificationIndex = validated.qualificationIndex;
    runtime.contextIndex = validated.contextIndex;
    runtime.endIndex = validated.endIndex;
    runtime.activeSymbol = candidate.symbol;
    candidate.status = 'active';
    batch.activeIndex = index;
  }

  function cleanupShell(options){
    options = options || {};
    const runtime = state.runtime;
    let restored = { ok:true, restored:false, error:null };
    try {
      if (runtime && runtime.chartSession && runtime.sessionStarted) restored = runtime.chartSession.restore();
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
    if (!window.MainChartSession || !window.SimDateMask) {
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

    const operation = beginOperation();
    const runtime = {
      chartSession: window.MainChartSession,
      maskLease: maskAcquisition.lease,
      sessionStarted: false,
      fullBars: null,
      qualificationIndex: null,
      contextIndex: null,
      endIndex: null,
      activeSymbol: null,
      lockedControls: []
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

  async function skipTicker(){
    const batch = state.batch;
    if (!batch || batch.status !== 'active' || state.status !== 'active') return;
    const skip = byId('entry-trainer-skip');
    const status = byId('entry-trainer-shell-status');
    if (skip) skip.disabled = true;
    const current = batch.candidates[batch.activeIndex];
    current.status = 'skipped';
    current.skipReason = 'shell_skip';

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
      updateStrip();
    } catch (error) {
      if (isStaleOperation(error, operation)) return;
      console.error('[EntryTrainer] candidate load failed:', error);
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
    const cleanup = cleanupShell({closeModal:true, restoreFocus:true});
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
    byId('entry-trainer-skip')?.addEventListener('click', skipTicker);
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
      trapSetupFocus(event);
      if (event.key === 'Escape' && modal.classList.contains('open')) {
        event.preventDefault();
        cancelSetup();
      }
    });
    return true;
  }

  window.EntryTrainer = Object.freeze({ open, isActive, exit, openReview, wire });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire, {once:true});
  else wire();
})();
