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
    if (cancel) cancel.disabled = !!busy;
    if (equity) equity.disabled = !!busy;
  }

  function setSetupOpen(open){
    const modal = byId('entry-trainer-setup-modal');
    if (!modal) return;
    modal.classList.toggle('open', !!open);
    modal.setAttribute('aria-hidden', open ? 'false' : 'true');
    if (open) {
      const equity = byId('entry-trainer-equity');
      setTimeout(function(){ equity?.focus(); equity?.select(); }, 30);
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

  async function fetchBatchDescriptors(){
    const response = await fetch('/api/entry-trainer/candidates?count=3', { headers:{Accept:'application/json'} });
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

  async function loadCandidate(batch, runtime, index){
    const candidate = batch.candidates[index];
    let validated = null;
    const fullBars = await runtime.chartSession.loadSymbol(candidate.symbol, {
      displayFrom: candidate.contextStartDate,
      displayThrough: candidate.qualificationDate,
      mask: {
        symbolLabel: '🎯 MASKED TICKER',
        conditionLabel: 'LONG · DAILY',
        rangeLabel: 'Day −' + batch.rules.contextBars + ' → Day 0'
      },
      validateBars: function(bars){
        validated = verifyCandidateBars(candidate, batch.rules, bars);
        window.SimDateMask.install(MASK_OWNER, createDateAdapter(bars, validated));
      }
    });
    if (!validated) throw new Error('Candidate validation did not complete');
    runtime.fullBars = fullBars;
    runtime.qualificationIndex = validated.qualificationIndex;
    runtime.contextIndex = validated.contextIndex;
    runtime.endIndex = validated.endIndex;
    runtime.activeSymbol = candidate.symbol;
    candidate.status = 'active';
    batch.activeIndex = index;
  }

  function cleanupShell(){
    try { window.SimDateMask?.remove(MASK_OWNER); } catch (error) {}
    try { state.runtime?.chartSession?.restore(); } catch (error) { console.error('[EntryTrainer] chart restore failed:', error); }
    unlockOrdinaryControls(state.runtime);
    document.body.classList.remove('entry-trainer-active');
    byId('entry-trainer-strip')?.classList.remove('is-active');
    const launch = byId('entry-trainer-btn');
    if (launch) launch.setAttribute('aria-pressed', 'false');
    setSetupBusy(false);
  }

  async function startFromSetup(){
    if (state.status === 'loading' || state.status === 'active') return;
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

    state.status = 'loading';
    setSetupBusy(true);
    setSetupStatus('Selecting three point-in-time candidates…', false);
    let draft = null;
    let runtime = null;
    try {
      const descriptors = await fetchBatchDescriptors();
      draft = createBatch(descriptors, startingEquity);
      runtime = {
        chartSession: window.MainChartSession,
        fullBars: null,
        qualificationIndex: null,
        contextIndex: null,
        endIndex: null,
        activeSymbol: null,
        lockedControls: []
      };
      setSetupStatus('Loading the first masked chart…', false);
      await loadCandidate(draft, runtime, 0);
      draft.status = 'active';
      state = { status:'active', batch:draft, lastBatch:state.lastBatch, runtime };
      lockOrdinaryControls(runtime);
      document.body.classList.add('entry-trainer-active');
      setSetupOpen(false);
      setSetupStatus('', false);
      updateStrip();
    } catch (error) {
      console.error('[EntryTrainer] start failed:', error);
      try { window.SimDateMask?.remove(MASK_OWNER); } catch (ignored) {}
      try { runtime?.chartSession?.restore(); } catch (ignored) {}
      unlockOrdinaryControls(runtime);
      state.status = 'idle';
      state.batch = null;
      state.runtime = null;
      document.body.classList.remove('entry-trainer-active');
      byId('entry-trainer-strip')?.classList.remove('is-active');
      setSetupStatus('Could not start the batch. The previous chart was preserved.', true);
    } finally {
      setSetupBusy(false);
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
    state.status = 'loading';
    try {
      await loadCandidate(batch, state.runtime, batch.activeIndex + 1);
      state.status = 'active';
      updateStrip();
    } catch (error) {
      console.error('[EntryTrainer] candidate load failed:', error);
      batch.status = 'abandoned';
      batch.abandonedAt = new Date().toISOString();
      state.lastBatch = batch;
      cleanupShell();
      state = { status:'idle', batch:null, lastBatch:batch, runtime:null };
      window.alert('Entry Trainer ended because the next masked chart could not be loaded. Your previous chart was restored.');
    }
  }

  function open(){
    if (!wired) wire();
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
    return !!(state.batch && (state.status === 'active' || state.status === 'loading'));
  }

  function exit(){
    if (!state.batch) {
      setSetupOpen(false);
      return false;
    }
    const batch = state.batch;
    if (batch.status !== 'completed') {
      batch.status = 'abandoned';
      batch.abandonedAt = new Date().toISOString();
    }
    state.lastBatch = batch;
    cleanupShell();
    state = { status:'idle', batch:null, lastBatch:batch, runtime:null };
    return true;
  }

  function openReview(batchId){
    const target = state.batch && state.batch.id === batchId ? state.batch : state.lastBatch;
    if (!target || (batchId && target.id !== batchId)) return false;
    // Review rendering is deliberately reserved for the review task.
    return false;
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
    byId('entry-trainer-cancel')?.addEventListener('click', function(){ if (state.status !== 'loading') setSetupOpen(false); });
    byId('entry-trainer-start')?.addEventListener('click', startFromSetup);
    byId('entry-trainer-skip')?.addEventListener('click', skipTicker);
    byId('entry-trainer-exit')?.addEventListener('click', exit);
    modal.addEventListener('click', function(event){
      if (event.target === modal && state.status !== 'loading') setSetupOpen(false);
    });
    byId('entry-trainer-equity')?.addEventListener('keydown', function(event){
      if (event.key === 'Enter') {
        event.preventDefault();
        startFromSetup();
      }
    });
    document.addEventListener('keydown', function(event){
      if (event.key !== 'Escape') return;
      if (modal.classList.contains('open') && state.status !== 'loading') setSetupOpen(false);
    });
    return true;
  }

  window.EntryTrainer = Object.freeze({ open, isActive, exit, openReview, wire });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire, {once:true});
  else wire();
})();
