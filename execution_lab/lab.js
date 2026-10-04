/* Execution Lab: display and intent only. The worker owns time, fills and risk. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const terminal = new Set(['filled', 'cancelled', 'expired']);
  const money = v => v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString('en-US', {style:'currency',currency:'USD'});
  const price = v => v == null ? '—' : Number(v).toFixed(2);
  const ratio = v => v == null || !Number.isFinite(Number(v)) ? '—' : `${Number(v).toFixed(2)}R`;
  const et = new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  const etShort = new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false});
  let state = null, busy = false, playing = false, timer = null, shownReview = null;
  let guides = [];
  const chart = LightweightCharts.createChart($('chart'), {
    width:$('chart').clientWidth,height:$('chart').clientHeight,
    layout:{backgroundColor:'#191916',textColor:'#a7a394',fontFamily:'ui-monospace, Menlo, monospace',fontSize:11},
    grid:{vertLines:{color:'#25251f'},horzLines:{color:'#25251f'}},
    rightPriceScale:{borderColor:'#35352d',scaleMargins:{top:.08,bottom:.22}},
    timeScale:{borderColor:'#35352d',timeVisible:true,secondsVisible:false,
               tickMarkFormatter:t=>etShort.format(new Date(Number(t)*1000))},
    localization:{timeFormatter:t=>et.format(new Date(Number(t)*1000))},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal}
  });
  const candles = chart.addCandlestickSeries({upColor:'#82c5a1',downColor:'#e39183',borderVisible:false,wickUpColor:'#82c5a1',wickDownColor:'#e39183'});
  const volumes = chart.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'volume'});
  chart.priceScale('volume').applyOptions({scaleMargins:{top:.83,bottom:0},visible:false});
  new ResizeObserver(()=>chart.resize($('chart').clientWidth,$('chart').clientHeight)).observe($('chart'));

  function status(message, error=false) {
    $('status').textContent=message;
    $('status').classList.toggle('error',error);
  }
  function node(tag, text, className) {
    const el=document.createElement(tag);
    if(text != null) el.textContent=text;
    if(className) el.className=className;
    return el;
  }
  function pause() {
    playing=false; clearTimeout(timer); timer=null; $('play').textContent='▶ Play';
  }
  function controls() {
    const live=state && !state.ended && !state.failed;
    for(const id of ['play','step','minute','finish']) $(id).disabled=!live || (busy && id!=='play');
    $('create').disabled=busy || !!live;
    $('submit-entry').disabled=busy || !live || !!state?.plan;
    for(const id of ['exit-quarter','exit-half','exit-custom','replace-stop']) {
      $(id).disabled=busy || !live || !state?.account.shares || !!state?.account.exit_intent;
    }
    $('close-all').disabled=busy || !live || (!state?.account.shares && !state?.orders.some(o=>o.side==='buy'&&!terminal.has(o.status))) || !!state?.account.exit_intent;
    for(const id of ['order-type','entry','buffer','stop','target','budget','follow-lod','minimum-r','rationale']) {
      $(id).disabled=!!state?.plan || busy;
    }
    $('entry').readOnly=$('order-type').value==='market';
    $('stop').readOnly=$('follow-lod').checked;
    for(const button of $('orders-body').querySelectorAll('button')) {
      button.disabled=busy || !live || button.dataset.cancelPending==='1';
    }
  }
  async function request(action, values={}) {
    if(busy) return null;
    busy=true; controls();
    const body={...values,action,command_id:crypto.randomUUID()};
    if(action!=='create') body.session_id=state?.session_id;
    try {
      const response=await fetch('/execution-lab/api/command',{method:'POST',
        headers:{'Content-Type':'application/json','X-Execution-Lab':'1'},body:JSON.stringify(body)});
      const result=await response.json();
      if(!response.ok || !result.ok) {
        if(result.fatal){pause();if(state)state.failed=true;}
        throw new Error(result.error || 'Command was not accepted.');
      }
      const previousId=state?.session_id;
      state=result.state; render();
      if(previousId!==state.session_id) chart.timeScale().fitContent();
      if(state.ended) pause();
      status(action==='advance' ? (state.ended?'Session complete. Review is saved.':playing?'Session playing.':'Paused. Read, plan, or advance.') :
             action==='create'?'Paused at 09:31 ET with one observed minute. Choose your target and risk.' :
             action==='finish'?'Session ended. Open inventory remains marked; review is saved.' :
             'Command queued. Resume or advance time to process it.');
      return state;
    } catch(error) {
      pause(); status(error.message+' If the response was interrupted, refresh before resubmitting.',true);
      return null;
    } finally {busy=false;controls();}
  }

  function aggregate(bars, minutes) {
    if(minutes===1) return bars;
    const out=[];
    for(const b of bars){
      const t=Math.floor(b.time/(minutes*60))*minutes*60;
      const last=out[out.length-1];
      if(last && last.time===t){last.high=Math.max(last.high,b.high);last.low=Math.min(last.low,b.low);last.close=b.close;last.volume+=b.volume;}
      else out.push({...b,time:t});
    }
    return out;
  }
  function chartData() {
    const bars=aggregate(state?.bars || [],Number($('timeframe').value));
    candles.setData(bars.map(({time,open,high,low,close})=>({time,open,high,low,close})));
    volumes.setData(bars.map(b=>({time:b.time,value:b.volume,color:b.close>=b.open?'#82c5a14d':'#e391834d'})));
    candles.setMarkers((state?.fills || []).map(f=>({
      time:Math.floor(f.time/(Number($('timeframe').value)*60))*Number($('timeframe').value)*60,
      position:f.side==='buy'?'belowBar':'aboveBar',color:f.side==='buy'?'#82c5a1':'#e39183',
      shape:f.side==='buy'?'arrowUp':'arrowDown',text:`${f.side} ${f.quantity}`
    })).filter(f=>bars.some(b=>b.time===f.time)).sort((a,b)=>a.time-b.time));
    drawGuides();
  }
  function drawGuides() {
    for(const line of guides)candles.removePriceLine(line);
    guides=[];
    const plan=state?.plan;
    const levels=[['LOD',state?.lod,'#dfbd77'],
      ['Entry',plan?plan.entry/100:Number($('entry').value),'#82c5a1'],
      ['Stop',plan?state.account.stop:Number($('stop').value),'#e39183'],
      ['Target',plan?plan.target/100:Number($('target').value),'#8caaca']];
    for(const [title,value,color] of levels){
      if(Number.isFinite(value)&&value>0)guides.push(candles.createPriceLine({price:value,color,lineWidth:1,
        lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title}));
    }
  }

  function preview() {
    if(!state?.plan){
      if($('order-type').value==='market' && state?.ask!=null) $('entry').value=price(state.ask);
      if($('follow-lod').checked && state?.lod!=null) $('stop').value=price(state.lod-Number($('buffer').value));
    }
    const e=Number($('entry').value),s=Number($('stop').value),t=Number($('target').value),b=Number($('budget').value);
    const valid=Number.isFinite(e+s+t+b) && s>0 && e>s && t>e && b>0;
    const rr=valid?(t-e)/(e-s):null;
    const planned=valid?Math.floor((b+1e-9)/(e-s)):0;
    const estimate=$('order-type').value==='market'?Math.max(e,state?.ask||e):e;
    const cashCap=estimate>0?Math.floor((state?.account.buying_power||0)/estimate):0;
    const shares=Math.min(planned,cashCap,1000000);
    $('preview-rr').textContent=ratio(rr);
    $('preview-risk').textContent=valid?money(e-s):'—';
    $('preview-shares').textContent=valid?shares.toLocaleString():'—';
    $('preview-total').textContent=valid?money(shares*(e-s)):'—';
    const low=valid && rr<Number($('minimum-r').value);
    $('preview-rr').classList.toggle('low',low);
    $('plan-hint').classList.toggle('warning',low);
    $('plan-hint').textContent=state?.plan ? `Submitted plan: ${ratio(state.plan.planned_rr)} · ${state.plan.quantity} shares · ${money(state.plan.planned_risk/100)} initial planned risk. Stop stays fixed.` :
      !valid?'Choose a target above entry and a stop below entry. Click the chart to mark a level.':
      low?'Below your preferred ratio. Wait for a better entry, revisit the target rationale, or deliberately accept the trade.':
      shares<planned?'Share size is capped by available cash. Actual market fills may change your risk.':
      'Ratio meets your preference. Judge the target from visible structure; reaching it is not guaranteed.';
    controls();drawGuides();
  }
  function render() {
    if(!state)return;
    $('symbol').textContent=state.symbol;
    $('session-meta').textContent=`${state.session_date} · ${state.hours}${state.ended?' · Ended':''}`;
    $('clock').textContent=et.format(new Date(state.time*1000))+' ET';
    for(const id of ['last','bid','ask','lod'])$(id).textContent=price(state[id]);
    const a=state.account;
    for(const [id,value] of [['equity',a.equity],['buying-power',a.buying_power],['average',a.average_entry],
      ['realized',a.realized],['unrealized',a.unrealized],['fixed-stop',a.stop],['remaining-risk',a.remaining_risk]]){
      $(id).textContent=money(value);
      if(id==='realized'||id==='unrealized'){$(id).classList.toggle('positive',value>0);$(id).classList.toggle('negative',value<0);}
    }
    $('position').textContent=`${a.shares.toLocaleString()} sh`;
    $('protection-status').textContent=a.protection_waiting?'Protective exit waiting for liquidity. Unfilled market quantity expired; protection retries on later prints.':
      a.exit_intent?`${a.exit_intent==='stop'?'Stop triggered':'Close requested'}: settling/canceling working orders and exiting remaining inventory.`:
      `${money(a.reserved_cash)} cash reserved · ${a.reserved_shares} shares reserved · fills change account balances.`;
    $('rules-text').textContent=state.rules;
    if(state.plan){
      const p=state.plan;
      for(const [id,v] of [['entry',p.entry],['stop',p.stop],['target',p.target],['budget',p.budget],['buffer',p.buffer]])$(id).value=price(v/100);
      $('rationale').value=p.rationale;
    }
    renderOrders();chartData();preview();stopPreview();
    if(state.failed){pause();status('Session failed. Restart the local server; see execution_lab/data/worker.log.',true);}
  }
  function renderOrders() {
    $('orders-body').replaceChildren();
    for(const o of [...state.orders].reverse()){
      const tr=node('tr');
      for(const value of [`${o.side.toUpperCase()}${o.protective?' · stop':''}`,o.type,o.quantity,o.filled,
        o.limit==null?'market':price(o.limit/100),o.status.replaceAll('_',' ')])tr.append(node('td',value));
      const td=node('td');
      if(!terminal.has(o.status) && !(o.type==='market' && o.status!=='queued')){
        const b=node('button','Cancel');b.dataset.cancelPending=o.status==='cancel_pending'?'1':'0';
        b.disabled=busy||state.ended||o.status==='cancel_pending';
        b.addEventListener('click',()=>request('cancel',{order_id:o.id}));td.append(b);
      }
      tr.append(td);$('orders-body').append(tr);
    }
    if(!state.orders.length){const tr=node('tr');const td=node('td','No orders. Plan an entry or wait.');td.colSpan=7;tr.append(td);$('orders-body').append(tr);}
    $('recent-fills').replaceChildren();
    for(const f of state.fills.slice(-8).reverse())$('recent-fills').append(node('div',`${et.format(new Date(f.time*1000))} · ${f.side.toUpperCase()} ${f.quantity} @ ${price(f.price/100)}${f.protective?' · protective exit':''}`));
    if(!state.fills.length)$('recent-fills').textContent='No confirmed fills yet.';
  }
  function stopPreview() {
    const next=Number($('new-stop').value),a=state?.account;
    $('stop-preview').textContent=next>0&&a?.shares?
      `Approx. remaining risk ${money(Math.max(0,(a.average_entry||0)-next)*a.shares)}.${a.stop!=null&&next<a.stop?' This widens your stop.':''}${state.last!=null&&next>=state.last?' At/above last trade: protection triggers when processed.':''} Initial R stays unchanged.`:
      'Submitted stops stay fixed when LOD moves. Changes are recorded; initial R stays unchanged.';
  }
  async function loop() {
    if(!playing)return;
    if(busy){timer=setTimeout(loop,100);return;}
    const result=await request('advance',{seconds:Number($('speed').value)});
    if(result && playing && !state.ended)timer=setTimeout(loop,1000);
  }

  function metric(label,value){const d=node('div');d.append(node('span',label),node('strong',value));return d;}
  function renderReview(review) {
    shownReview=review;
    const root=$('review-content');root.replaceChildren();
    const cfg=review.configuration,a=review.state.account;
    root.append(node('p',`${cfg.date} · ${review.reason} · Seed ${review.seed}`),node('p',review.state.rules,'small'));
    const metrics=node('div',null,'review-metrics');
    for(const [label,value] of [['REALIZED',money(a.realized)],['UNREALIZED',money(a.unrealized)],['FINAL EQUITY',money(a.equity)],['SAMPLED DRAWDOWN',money(review.sampled_max_drawdown)]])metrics.append(metric(label,value));
    root.append(metrics);
    const actions=node('div',null,'review-actions');
    const repeat=node('button','Use this seed again');repeat.addEventListener('click',()=>{
      $('seed').value=review.seed;$('date').value=cfg.date;$('cash').value=cfg.cash;
      $('reviews-dialog').close();status('Repeat settings copied. Finish any active session, then Start random session.');
    });
    const download=node('button','Download review JSON');download.addEventListener('click',()=>{
      const url=URL.createObjectURL(new Blob([JSON.stringify(review,null,2)],{type:'application/json'}));
      const link=node('a');link.href=url;link.download=`execution-review-${review.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });actions.append(repeat,download);root.append(actions);
    equityPlot(root,review.equity_curve);
    root.append(node('p',review.notes,'small'));
    for(const trade of review.trades){
      const p=trade.plan,card=node('article',null,'review-card');
      card.append(node('h3',`Trade ${trade.id} · ${trade.status}`));
      const m=node('div',null,'review-metrics');
      for(const [label,value] of [['PLANNED R/R',ratio(p.planned_rr)],['FILL R/R',ratio(trade.actual_rr)],
        ['PLANNED RISK',money(p.planned_risk/100)],['ACTUAL INITIAL RISK',trade.actual_initial_risk==null?'Unavailable':money(trade.actual_initial_risk/100)],
        ['REALIZED P&L',money(trade.realized/100)],['REALIZED R',ratio(trade.realized_r)],
        ['MFE / MAE',`${money(trade.mfe/100)} / ${money(trade.mae/100)}`],
        ['ENTRY SLIPPAGE / SHARE',trade.slippage_per_share==null?'—':money(trade.slippage_per_share/100)]])m.append(metric(label,value));
      card.append(m,node('p',`At submission: entry ${price(p.entry/100)} · LOD ${price(p.observed_lod/100)} · stop ${price(p.stop/100)} · target ${price(p.target/100)} · ${p.quantity} shares. Entry-to-LOD distance ${price((p.entry-p.observed_lod)/100)}.`));
      card.append(node('p',p.rationale?`Your rationale: ${p.rationale}`:'No target rationale recorded.'));
      if(trade.invalid_risk)card.append(node('p','Entry invalidated on arrival: a fill was at/below the initial stop. Protection triggered; actual-risk and R metrics are unavailable.','negative'));
      for(const edit of trade.stop_edits)card.append(node('p',`${et.format(new Date(edit.time*1000))} · Stop ${price(edit.old/100)} → ${price(edit.new/100)} · ${edit.shares} shares · ${edit.widened?'widened risk':'tightened stop'}`));
      const detail=node('details');detail.append(node('summary','Fills and execution decisions'));
      for(const event of trade.events)detail.append(node('p',`${et.format(new Date(event.time*1000))} · ${event.kind.replaceAll('_',' ')} · ${JSON.stringify(Object.fromEntries(Object.entries(event).filter(([k])=>k!=='time'&&k!=='kind')))}`,'small'));
      card.append(detail);root.append(card);
    }
    if(!review.trades.length)root.append(node('p','No trades submitted. Observing and passing are valid practice decisions.'));
    const profile=node('details');profile.append(node('summary','Reproducibility and hidden profile'),node('p',JSON.stringify(cfg.profile),'small'),node('p',`Pinned ABIDES revision: ${review.engine_revision}`,'small'));root.append(profile);
    $('reviews-dialog').showModal();
  }
  function equityPlot(root,points){
    if(!points?.length)return;
    const box=node('div',null,'review-equity'),ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 900 140');svg.setAttribute('role','img');svg.setAttribute('aria-label','Equity curve sampled at simulation advances');
    const values=points.map(p=>Number(p.value)).filter(Number.isFinite);if(!values.length)return;
    const low=Math.min(...values),high=Math.max(...values),range=Math.max(1,high-low);
    const path=document.createElementNS(ns,'path');path.setAttribute('d',values.map((v,i)=>`${i?'L':'M'} ${10+i*880/Math.max(1,values.length-1)} ${125-(v-low)*110/range}`).join(' '));path.setAttribute('fill','none');path.setAttribute('stroke','#dfbd77');path.setAttribute('stroke-width','2');svg.append(path);box.append(svg);root.append(box,node('p',`Equity range ${money(low)} – ${money(high)} · sampled at advance boundaries`,'small'));
  }
  async function loadReview(id){
    try{const r=await fetch(`/execution-lab/api/reviews/${encodeURIComponent(id)}`);const data=await r.json();if(!r.ok)throw new Error(data.error);renderReview(data);}catch(e){status(e.message,true);}
  }
  async function saved(){
    pause();
    try{
      const response=await fetch('/execution-lab/api/reviews');const result=await response.json();
      const root=$('review-content');root.replaceChildren();shownReview=null;
      const list=node('div',null,'review-list');
      for(const row of result.reviews){const b=node('button',`${row.date} · ${row.trades} planned trades · realized ${money(row.realized)} · ${row.reason}`);b.addEventListener('click',()=>{$('reviews-dialog').close();loadReview(row.id);});list.append(b);}
      root.append(list);if(!result.reviews.length)root.append(node('p','No completed sessions saved yet.'));
      $('reviews-dialog').showModal();
    }catch(e){status(e.message,true);}
  }

  $('create').addEventListener('click',async()=>{
    pause();status('Starting isolated ABIDES session…');
    const result=await request('create',{cash:$('cash').value,date:$('date').value||null,seed:$('seed').value||null});
    if(result){$('target').value='';$('rationale').value='';$('new-stop').value='';preview();}
  });
  $('entry-form').addEventListener('submit',e=>{e.preventDefault();request('entry',{
    order_type:$('order-type').value,entry:$('entry').value,stop:$('stop').value,target:$('target').value,
    buffer:$('buffer').value,budget:$('budget').value,minimum_r:$('minimum-r').value,rationale:$('rationale').value
  });});
  for(const id of ['entry','stop','target','budget','buffer','minimum-r','follow-lod','order-type'])$(id).addEventListener('input',preview);
  $('stop').addEventListener('input',()=>{if(!$('stop').readOnly)$('follow-lod').checked=false;});
  $('new-stop').addEventListener('input',stopPreview);
  $('replace-stop').addEventListener('click',()=>request('stop',{price:$('new-stop').value}));
  function sell(quantity){return request('exit',{quantity,order_type:$('exit-type').value,price:$('exit-limit').value});}
  $('exit-quarter').addEventListener('click',()=>sell(Math.max(1,Math.floor((state.account.shares-state.account.reserved_shares)/4))));
  $('exit-half').addEventListener('click',()=>sell(Math.max(1,Math.floor((state.account.shares-state.account.reserved_shares)/2))));
  $('exit-custom').addEventListener('click',()=>sell($('exit-quantity').value));
  $('exit-type').addEventListener('change',()=>{$('exit-limit-label').hidden=$('exit-type').value!=='limit';});
  $('close-all').addEventListener('click',()=>request('exit',{all:true}));
  $('play').addEventListener('click',()=>{if(playing)pause();else{playing=true;$('play').textContent='Ⅱ Pause';loop();}});
  $('step').addEventListener('click',()=>{pause();request('advance',{seconds:10});});
  $('minute').addEventListener('click',()=>{pause();request('advance',{seconds:60});});
  $('finish').addEventListener('click',async()=>{pause();const result=await request('finish');if(result)loadReview(result.review_id);});
  $('timeframe').addEventListener('change',chartData);
  $('saved').addEventListener('click',saved);
  $('close-review').addEventListener('click',()=>{$('reviews-dialog').close();shownReview=null;});
  chart.subscribeClick(param=>{
    if(!param.point || !state || state.ended || state.plan)return;
    const value=candles.coordinateToPrice(param.point.y);
    if(value==null || value<=0)return;
    const field=$('chart-field').value;
    if(field==='entry')$('order-type').value='limit';
    if(field==='stop')$('follow-lod').checked=false;
    $(field).value=price(value);preview();
  });
  function theme(light){
    document.body.classList.toggle('light',light);$('theme').textContent=light?'Dark':'Light';
    chart.applyOptions({layout:{backgroundColor:light?'#fffdf7':'#191916',textColor:light?'#696c60':'#a7a394'},
      grid:{vertLines:{color:light?'#eeeee3':'#25251f'},horzLines:{color:light?'#eeeee3':'#25251f'}}});
    try{localStorage.setItem('execution_lab_theme',light?'light':'dark');}catch(_){/* optional */}
  }
  $('theme').addEventListener('click',()=>theme(!document.body.classList.contains('light')));
  try{theme(localStorage.getItem('execution_lab_theme')==='light');}catch(_){theme(false);}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  window.addEventListener('beforeunload',pause);
  fetch('/execution-lab/api/state').then(r=>r.json()).then(result=>{
    if(result.state){state=result.state;render();chart.timeScale().fitContent();status(state.ended?'Previous session ended. Review is saved.':'Reconnected to active session. Playback is paused.');}
    if(result.worker_failed){if(state)state.failed=true;status('Worker failed. Restart the big_movers server.',true);controls();}
  }).catch(e=>status(e.message,true));
  controls();
})();
