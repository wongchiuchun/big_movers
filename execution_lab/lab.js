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
  let entryMode="entry", direction="long", picking=null;
  let entryValid=false, stopValid=false, exitValid=false;
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
    for(const id of ['entry','exit','stop']){
      const el=$(`${id}-error`);
      el.hidden=!error||!$(`${id}-dialog`).open;
      el.textContent=error?message:'';
    }
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
    const active=state && !state.ended && !state.failed;
    const live=active && state.api_version===2;
    const qty=Math.abs(state?.account.shares||0),pending=state?.orders.some(o=>!terminal.has(o.status));
    for(const id of ['play','step','minute','finish'])$(id).disabled=!live || (busy&&id!=='play');
    $('create').disabled=busy||!!active;
    $('finish').disabled=busy||!active;
    for(const id of ['regime','volatility','liquidity'])$(id).disabled=busy||!!active;
    for(const id of ['new-long','new-short'])$(id).disabled=busy||!live||!!state?.plan;
    for(const id of ['open-exit','open-add','open-stop'])$(id).disabled=busy||!live||!qty||!!state?.account.exit_intent||(id==='open-add'&&pending);
    $('close-all').disabled=busy||!live||(!qty&&!state?.plan)||!!state?.account.exit_intent;
    for(const id of ['submit-entry','exit-custom','replace-stop'])$(id).disabled=busy||!live;
    $('submit-entry').disabled ||= !entryValid;
    $('replace-stop').disabled ||= !stopValid;
    $('exit-custom').disabled ||= !exitValid;
    $('entry').readOnly=$('order-type').value==='market';
    $('stop').readOnly=$('stop-strategy').value!=='manual';
    for(const button of $('orders-body').querySelectorAll('button'))button.disabled=busy||!live||button.dataset.cancelPending==='1';
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
        const error=new Error(result.error || 'Command was not accepted.');
        error.rejected=true;
        throw error;
      }
      const previousId=state?.session_id;
      state=result.state; render();
      if(previousId!==state.session_id) chart.timeScale().fitContent();
      if(state.ended) pause();
      status(action==='advance' ? (state.ended?'Session complete. Review is saved.':playing?'Session playing.':'Paused. Read, plan, or advance.') :
             action==='create'?'Paused at 09:31 ET. Choose Long or Short to enter.' :
             action==='finish'?'Session ended. Open inventory remains marked; review is saved.' :
             'Command processed. Market fills are shown; limits can remain working.');
      return state;
    } catch(error) {
      pause(); status(error.message+(error.rejected?'':' If the response was interrupted, refresh before resubmitting.'),true);
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
    const levels=[['LOD',state?.lod,'#dfbd77'],['HOD',state?.hod,'#9b8cb9']];
    if(plan){
      levels.push(['Avg',state.account.average_entry,'#82c5a1']);
      if(plan.target!=null)levels.push(['Target',plan.target/100,'#8caaca']);
      for(const stop of state.stops||[])if(!stop.fired)levels.push([`Stop ${stop.percent}%`,stop.price/100,'#e39183']);
    }else if($('entry-dialog').open||picking){
      levels.push(['Entry',Number($('entry').value),'#82c5a1'],['Stop',Number($('stop').value),'#e39183']);
      if($('target').value)levels.push(['Target',Number($('target').value),'#8caaca']);
    }
    if($('stop-dialog').open&&$('new-stop').value)levels.push(['Draft stop',Number($('new-stop').value),'#e39183']);
    for(const [title,value,color] of levels)if(Number.isFinite(value)&&value>0)guides.push(candles.createPriceLine({price:value,color,lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title}));
  }
  function calculatedStop(strategy,parameter,period,reference,dir){
    const sign=dir==='long'?1:-1;
    const bars=(state?.bars||[]).filter(b=>b.time+60<=state.time);
    if(strategy==='manual')return null;
    if(strategy==='lod')return (dir==='long'?state.lod:state.hod)-sign*parameter;
    if(strategy==='pct')return reference*(1-sign*parameter/100);
    if(['swing5','swing10','base'].includes(strategy)){
      const n=strategy==='swing5'?5:strategy==='swing10'?10:bars.length;
      if(!n||bars.length<n)throw new Error(`Need ${n||1} completed one-minute candles.`);
      return (sign===1?Math.min(...bars.slice(-n).map(b=>b.low)):Math.max(...bars.slice(-n).map(b=>b.high)))-sign*parameter;
    }
    if(strategy==='atr'){
      if(bars.length<15)throw new Error('ATR(14) needs 15 completed one-minute candles.');
      let total=0;
      for(let i=bars.length-14;i<bars.length;i++)total+=Math.max(bars[i].high-bars[i].low,Math.abs(bars[i].high-bars[i-1].close),Math.abs(bars[i].low-bars[i-1].close));
      return reference-sign*total/14*parameter;
    }
    if(bars.length<period)throw new Error(`EMA(${period}) needs ${period} completed one-minute candles.`);
    let ema=bars[0].close;
    for(const b of bars.slice(1))ema+=(b.close-ema)*2/(period+1);
    return ema-sign*parameter;
  }
  function preview(){
    if(!state)return;
    const sign=direction==='long'?1:-1;
    if($('order-type').value==='market')$('entry').value=price(direction==='long'?state.ask:state.bid);
    const e=Number($('entry').value);
    let calculationError='';
    if(entryMode==='add')$('stop').value=price(state.account.stop);
    else if($('stop-strategy').value!=='manual'){
      try{$('stop').value=price(calculatedStop($('stop-strategy').value,Number($('buffer').value),Number($('ema-period').value),e,direction));}
      catch(err){$('stop').value='';calculationError=err.message;}
    }
    const stop=Number($('stop').value),mode=$('size-mode').value,value=Number($('size-value').value);
    const target=entryMode==='entry'&&$('target').value?Number($('target').value):null;
    const valid=Number.isFinite(e+stop+value)&&e>0&&stop>0&&sign*(e-stop)>0&&value>0;
    const targetValid=target==null||sign*(target-e)>0;
    const risk=valid?Math.abs(e-stop):null;
    const requested=valid?(mode==='shares'?Math.floor(value):mode==='dollars'?Math.floor(value/e):Math.floor((value+1e-9)/risk)):0;
    const estimate=$('order-type').value==='market'?Math.max(e,(direction==='long'?state.ask:state.bid)||e):e;
    const cap=estimate>0?Math.floor(state.account.buying_power/estimate):0;
    const shares=mode==='risk'?Math.min(requested,cap):requested;
    const rr=valid&&target!=null&&targetValid?sign*(target-e)/risk:null;
    $('preview-shares').textContent=valid?shares.toLocaleString():'—';
    $('preview-notional').textContent=valid?money(shares*e):'—';
    $('preview-risk').textContent=valid?money(risk):'—';
    $('preview-total').textContent=valid?money(shares*risk):'—';
    $('preview-rr').textContent=target==null?'Optional':ratio(rr);
    const low=rr!=null&&rr<Number($('minimum-r').value);
    $('preview-rr').classList.toggle('low',low);
    $('plan-hint').classList.toggle('warning',!valid||!targetValid||requested>cap||low);
    $('plan-hint').textContent=calculationError||(!valid?'Choose a valid stop on the protective side of entry.':!targetValid?'Target must be on the profitable side of entry.':requested>cap?(mode==='risk'?'Risk size capped to buying power.':'Requested size exceeds buying power/collateral.'):low?'Below your preferred reward/risk; you can still deliberately take the trade.':entryMode==='add'?'Same-direction add. Existing stops remain; initial R retains the original stop.':'Market orders process now. Limits may rest. Target and notes are optional.');
    $('ema-entry-label').hidden=!['ema','ema_trail'].includes($('stop-strategy').value);
    $('buffer-label').textContent=$('stop-strategy').value==='pct'?'Distance (%)':$('stop-strategy').value==='atr'?'ATR multiple':'Buffer ($)';
    $('size-label').textContent=mode==='shares'?'Shares':mode==='dollars'?'$ Amount':'$ Risk';
    $('size-value').step=mode==='shares'?'1':'.01';
    $('size-value').min=mode==='shares'?'1':'.01';
    $('submit-entry').textContent=entryMode==='add'?(direction==='short'?'Add Short':'Add'):(direction==='short'?'Sell Short':'Buy Long');
    entryValid=valid&&targetValid&&shares>=1&&(mode==='risk'||requested<=cap);
    controls();
    drawGuides();
  }
  function render(){
    if(!state)return;
    $('symbol').textContent=state.symbol;
    $('session-meta').textContent=`${state.session_date} · ${state.hours}${state.ended?' · Ended':''}`;
    $('clock').textContent=et.format(new Date(state.time*1000))+' ET';
    for(const id of ['last','bid','ask','lod','hod'])$(id).textContent=price(state[id]);
    const a=state.account,qty=Math.abs(a.shares),short=a.direction==='short';
    for(const [id,v]of [['equity',a.equity],['buying-power',a.buying_power],['average',a.average_entry],['realized',a.realized],['unrealized',a.unrealized],['fixed-stop',a.stop],['remaining-risk',a.remaining_risk]]){
      $(id).textContent=money(v);
      if(id==='realized'||id==='unrealized'){$(id).classList.toggle('positive',v>0);$(id).classList.toggle('negative',v<0);}
    }
    $('position').textContent=qty?`${short?'Short':'Long'} ${qty} sh`:'Flat';
    $('open-exit').textContent=short?'Cover':'Sell';
    $('open-add').textContent=short?'Add Short':'Add';
    $('trade-heading').textContent=qty?`${short?'Short':'Long'} position`:state.plan?'Entry working':'Out of position';
    $('trade-facts').textContent=qty?`${qty} shares · Avg ${price(a.average_entry)} · Stop ${price(a.stop)}`:state.plan?'Cancel the working entry in Orders, or Close to cancel it.':'Choose Long or Short. Set size and stop in the entry dialog.';
    $('protection-status').textContent=a.protection_waiting?'Protective exit waiting for fresh liquidity.':a.exit_intent?`${a.exit_intent}: canceling/settling orders and exiting.`:`${money(a.reserved_cash)} entry reservation · ${a.reserved_shares} exit shares reserved${short?` · ${money(a.short_collateral)} short collateral + restricted proceeds`:''}`;
    $('rules-text').textContent=state.rules;
    $('stop-levels').replaceChildren();
    for(const level of state.stops||[]){
      const chip=node('div',null,`stop-chip${level.initial?' initial':''}${level.fired?' fired':''}`);
      chip.append(node('span',`${level.initial?'Initial · ':''}${price(level.price/100)} · ${level.percent}%${level.fired?' · fired':''}${level.strategy==='ema_trail'?' · EMA trail':''}`));
      if(!level.fired){const edit=node('button','Edit');edit.addEventListener('click',()=>openStop(level));chip.append(edit);
        if(!level.initial){const remove=node('button','×');remove.setAttribute('aria-label','Delete stop level');remove.addEventListener('click',()=>request('delete_stop',{stop_id:level.id}));chip.append(remove);}}
      $('stop-levels').append(chip);
    }
    renderOrders();chartData();
    if($('entry-dialog').open)preview();
    if($('stop-dialog').open)stopPreview();
    if($('exit-dialog').open)exitPreview();
    controls();
    if(state.failed){pause();status('Session failed. Restart server; see worker.log.',true);}
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
  function stopPreview(){
    if(!state)return;
    const strategy=$('move-strategy').value,dir=state.account.direction,sign=dir==='long'?1:-1;
    let error='';
    if(strategy!=='manual')try{$('new-stop').value=price(calculatedStop(strategy,Number($('move-parameter').value),Number($('move-ema-period').value),state.last,dir));}catch(e){error=e.message;$('new-stop').value='';}
    $('new-stop').readOnly=strategy!=='manual';
    $('ema-move-label').hidden=!['ema','ema_trail'].includes(strategy);
    $('move-parameter-label').textContent=strategy==='pct'?'Distance (%)':strategy==='atr'?'ATR multiple':'Buffer ($)';
    const mode=$('stop-mode').value;
    const initial=mode==='edit'&&(state.stops||[]).some(s=>s.id===Number($('stop-id').value)&&s.initial);
    $('stop-percent').disabled=mode==='replace'||initial;if(mode==='replace'||initial)$('stop-percent').value=100;
    $('replace-stop').textContent=mode==='add'?'Add Stop':'Save Stop';
    const next=Number($('new-stop').value),a=state.account;
    $('stop-preview').textContent=error||(next>0?`Approx. remaining risk ${money(Math.max(0,sign*((a.average_entry||0)-next))*Math.abs(a.shares))}.${a.stop!=null&&sign*(next-a.stop)<0?' Wider than fallback.':''}${sign*(state.last-next)<=0?' Already crossed: triggers when submitted.':''} 100% closes all; partial % uses original entry size. Initial R stays unchanged.`:'Choose a stop price.');
    const percent=Number($('stop-percent').value);
    stopValid=!error&&Number.isFinite(next)&&next>0&&!!a.shares&&Number.isInteger(percent)&&percent>=1&&percent<=100;
    controls();
    drawGuides();
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
      for(const id of ['regime','volatility','liquidity'])$(id).value=cfg.selections?.[id]||'random';
      $('reviews-dialog').close();status(cfg.profile.model_version===2?'Repeat settings copied. Finish any active session, then Start random session.':'Settings copied from the earlier model. The updated market generator will produce a different path.');
    });
    const download=node('button','Download review JSON');download.addEventListener('click',()=>{
      const url=URL.createObjectURL(new Blob([JSON.stringify(review,null,2)],{type:'application/json'}));
      const link=node('a');link.href=url;link.download=`execution-review-${review.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });actions.append(repeat,download);root.append(actions);
    equityPlot(root,review.equity_curve);
    root.append(node('p',review.notes,'small'));
    for(const trade of review.trades){
      const p=trade.plan,card=node('article',null,'review-card');
      card.append(node('h3',`Trade ${trade.id} · ${p.direction||'long'} · ${trade.status}`));
      const m=node('div',null,'review-metrics');
      for(const [label,value] of [['PLANNED R/R',ratio(p.planned_rr)],['FILL R/R',ratio(trade.actual_rr)],
        ['PLANNED RISK',money(p.planned_risk/100)],['ACTUAL INITIAL RISK',trade.actual_initial_risk==null?'Unavailable':money(trade.actual_initial_risk/100)],
        ['REALIZED P&L',money(trade.realized/100)],['REALIZED R',ratio(trade.realized_r)],
        ['MFE / MAE',`${money(trade.mfe/100)} / ${money(trade.mae/100)}`],
        ['ENTRY SLIPPAGE / SHARE',trade.slippage_per_share==null?'—':money(trade.slippage_per_share/100)]])m.append(metric(label,value));
      const short=p.direction==='short',extreme=short?p.observed_hod:p.observed_lod;
      card.append(m,node('p',`At submission: entry ${price(p.entry/100)} · ${short?'HOD':'LOD'} ${price(extreme/100)} · stop ${price(p.stop/100)} · target ${p.target==null?'not set':price(p.target/100)} · ${p.quantity} shares. Distance to session extreme ${price(Math.abs(p.entry-extreme)/100)}.`));
      card.append(node('p',p.rationale?`Your rationale: ${p.rationale}`:'No target rationale recorded.'));
      if(trade.invalid_risk)card.append(node('p','Entry invalidated on arrival: a fill crossed the original stop. Protection triggered; actual-risk and R metrics are unavailable.','negative'));
      for(const edit of trade.stop_edits)card.append(node('p',`${et.format(new Date(edit.time*1000))} · Stop ${edit.old==null?'new level':price(edit.old/100)} → ${price(edit.new/100)} · ${edit.shares} shares · ${edit.widened?'widened risk':'tightened stop'}`));
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

  function openEntry(dir,mode='entry'){
    pause();entryMode=mode;direction=mode==='add'?state.account.direction:dir;
    $('entry-title').textContent=mode==='add'?(direction==='short'?'Add Short':'Add to Position'):'New Entry';
    for(const button of $('direction-pills').querySelectorAll('button')){button.classList.toggle('active',button.dataset.direction===direction);button.disabled=mode==='add';}
    for(const el of $('entry-form').querySelectorAll('.entry-only'))el.hidden=mode==='add';
    $('stop').required=mode==='entry';
    $('target').value=mode==='entry'?'':state.plan?.target==null?'':price(state.plan.target/100);
    $('entry').value=price(direction==='long'?state.ask:state.bid);
    $('entry-dialog').showModal();preview();
    $('entry-error').hidden=true;
  }
  function openStop(level=null){
    pause();$('stop-mode').value=level?'edit':'add';$('stop-id').value=level?.id||'';
    $('move-strategy').value=level?.strategy||'manual';$('move-parameter').value=level?.parameter??.01;
    $('move-ema-period').value=level?.period||10;$('stop-percent').value=level?.percent||100;
    $('new-stop').value=price(level?level.price/100:state.account.stop);
    $('stop-dialog').showModal();stopPreview();
    $('stop-error').hidden=true;
  }
  function exitPreview(){
    if(!state)return;const a=state.account,q=Number($('exit-quantity').value),sign=a.direction==='long'?1:-1;
    const px=$('exit-type').value==='limit'?Number($('exit-limit').value):(sign===1?state.bid:state.ask);
    exitValid=Number.isInteger(q)&&q>=1&&q<=Math.abs(a.shares)-a.reserved_shares&&Number.isFinite(px)&&px>0;
    $('exit-preview').textContent=`Estimated realized P&L ${money(sign*(px-(a.average_entry||0))*q)} · actual result depends on fills.`;
    controls();
  }
  for(const b of document.querySelectorAll('[data-dismiss]'))b.addEventListener('click',()=>{$(b.dataset.dismiss).close();drawGuides();});
  $('new-long').addEventListener('click',()=>openEntry('long'));
  $('new-short').addEventListener('click',()=>openEntry('short'));
  $('open-add').addEventListener('click',()=>openEntry(state.account.direction,'add'));
  $('open-stop').addEventListener('click',()=>openStop());
  $('open-exit').addEventListener('click',()=>{
    pause();const short=state.account.direction==='short';$('exit-title').textContent=short?'Cover Shares':'Sell Shares';$('exit-custom').textContent=short?'Cover':'Sell';
    $('exit-quantity').value=Math.max(0,Math.abs(state.account.shares)-state.account.reserved_shares);
    $('exit-limit').value=price(short?state.ask:state.bid);$('exit-dialog').showModal();exitPreview();
    $('exit-error').hidden=true;
  });
  for(const b of $('direction-pills').querySelectorAll('button'))b.addEventListener('click',()=>{direction=b.dataset.direction;for(const p of $('direction-pills').querySelectorAll('button'))p.classList.toggle('active',p===b);preview();});
  for(const b of $('size-pills').querySelectorAll('button'))b.addEventListener('click',()=>{$('size-mode').value=b.dataset.size;for(const p of $('size-pills').querySelectorAll('button'))p.classList.toggle('active',p===b);preview();});
  $('create').addEventListener('click',async()=>{pause();status('Starting ABIDES session…');const result=await request('create',{cash:$('cash').value,date:$('date').value||null,seed:$('seed').value||null,
    regime:$('regime').value||'random',volatility:$('volatility').value||'random',liquidity:$('liquidity').value||'random'});if(result){$('target').value='';$('rationale').value='';}});
  $('entry-form').addEventListener('submit',async e=>{
    e.preventDefault();
    const values={direction,order_type:$('order-type').value,entry:$('entry').value,size_mode:$('size-mode').value,size_value:$('size-value').value,
      stop:$('stop').value,stop_strategy:$('stop-strategy').value,stop_parameter:$('buffer').value,ema_period:$('ema-period').value,
      target:$('target').value||null,buffer:$('buffer').value,budget:$('size-mode').value==='risk'?$('size-value').value:100,
      minimum_r:$('minimum-r').value,rationale:$('rationale').value};
    const result=await request(entryMode,values);if(result){$('entry-dialog').close();drawGuides();}
  });
  for(const id of ['entry','stop','target','size-value','buffer','minimum-r','order-type','ema-period'])$(id).addEventListener('input',preview);
  $('stop-strategy').addEventListener('change',()=>{$('buffer').value=['pct','atr'].includes($('stop-strategy').value)?2:.01;preview();});
  for(const id of ['new-stop','move-parameter','move-ema-period','stop-percent','stop-mode'])$(id).addEventListener('input',stopPreview);
  $('move-strategy').addEventListener('change',()=>{$('move-parameter').value=['pct','atr'].includes($('move-strategy').value)?2:.01;stopPreview();});
  $('replace-stop').addEventListener('click',async()=>{const result=await request('stop',{price:$('new-stop').value,mode:$('stop-mode').value,
    stop_id:Number($('stop-id').value)||null,percent:$('stop-percent').value,strategy:$('move-strategy').value,
    parameter:$('move-parameter').value,ema_period:$('move-ema-period').value});if(result)$('stop-dialog').close();});
  for(const [id,fraction]of [['exit-all',1],['exit-half',.5],['exit-third',1/3]])$(id).addEventListener('click',()=>{$('exit-quantity').value=Math.max(1,Math.floor((Math.abs(state.account.shares)-state.account.reserved_shares)*fraction));exitPreview();});
  for(const id of ['exit-quantity','exit-limit','exit-type'])$(id).addEventListener('input',exitPreview);
  $('exit-type').addEventListener('change',()=>{$('exit-limit-label').hidden=$('exit-type').value!=='limit';});
  $('exit-custom').addEventListener('click',async()=>{const result=await request('exit',{quantity:$('exit-quantity').value,order_type:$('exit-type').value,price:$('exit-limit').value});if(result)$('exit-dialog').close();});
  $('close-all').addEventListener('click',()=>request('exit',{all:true}));
  $('play').addEventListener('click',()=>{if(playing)pause();else{playing=true;$('play').textContent='Ⅱ Pause';loop();}});
  $('step').addEventListener('click',()=>{pause();request('advance',{seconds:10});});
  $('minute').addEventListener('click',()=>{pause();request('advance',{seconds:60});});
  $('finish').addEventListener('click',async()=>{pause();const result=await request('finish');if(result)loadReview(result.review_id);});
  $('timeframe').addEventListener('change',chartData);
  $('saved').addEventListener('click',saved);
  $('close-review').addEventListener('click',()=>{$('reviews-dialog').close();shownReview=null;});
  for(const button of document.querySelectorAll('[data-pick]'))button.addEventListener('click',()=>{
    const field=button.dataset.pick,dialog=button.closest('dialog');picking={field,dialog:dialog.id};dialog.close();$('chart-field').value=field==='new-stop'?'stop':field;status(`Click the chart to set ${field.replace('-',' ')}. Press Escape to cancel picking.`);
  });
  chart.subscribeClick(param=>{
    if(!param.point||!state||state.ended)return;
    const value=candles.coordinateToPrice(param.point.y);if(value==null||value<=0)return;
    const field=picking?picking.field:$('chart-field').value;
    if(!picking&&state.plan)return;
    if(field==='entry')$('order-type').value='limit';
    if(field==='stop')$('stop-strategy').value='manual';
    if(field==='new-stop')$('move-strategy').value='manual';
    $(field).value=price(value);
    if(picking){const dialog=picking.dialog;picking=null;$(dialog).showModal();if(dialog==='stop-dialog')stopPreview();else preview();}
    else{openEntry(direction);$(field).value=price(value);preview();}
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&picking){const dialog=picking.dialog;picking=null;$(dialog).showModal();status('Price picking canceled.');}});
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
    if(result.state){state=result.state;for(const id of ['regime','volatility','liquidity'])$(id).value=state.selections?.[id]||'random';render();chart.timeScale().fitContent();status(state.api_version!==2?'The running server uses an older Execution Lab backend. Save with Finish & review, then restart Chart Studies and refresh this page to enable orders.':state.ended?'Previous session ended. Review is saved.':'Reconnected to active session. Playback is paused.',state.api_version!==2);}
    if(result.worker_failed){if(state)state.failed=true;status('Worker failed. Restart the big_movers server.',true);controls();}
  }).catch(e=>status(e.message,true));
  controls();
})();
