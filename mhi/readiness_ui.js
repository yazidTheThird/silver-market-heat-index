/* Local aggregate reports stay in this browser until explicitly exported. */
function initReadiness(published) {
  const $=id=>document.getElementById(id), key='blackbird-release-reports-v1';
  const today=new Date().toISOString().slice(0,10);
  const yesterday=new Date(Date.parse(today+'T00:00:00Z')-86400000).toISOString().slice(0,10);
  let local=[], storageOK=true;
  try { const raw=JSON.parse(localStorage.getItem(key)||'[]'); if(!Array.isArray(raw))throw Error();local=raw.map(r=>Readiness.validate(r,today)); }
  catch(e) { storageOK=false;local=[]; }
  let active=null;
  $('readiness').innerHTML=`<h2>Should I release?</h2>
    <label class="field">Compare my release with<select id="release-profile">${Readiness.profiles.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></label>
    <div id="release-verdict" aria-live="polite"></div>
    <details id="release-editor"><summary>Add or update completed-sales figures</summary>
      <p>Open <a href="https://www.ebay.com/sh/research" target="_blank" rel="noopener">eBay Product Research</a> in your account. Run the same search for the two date ranges below. Copy <strong>total units sold, average sold price and sellers with sales</strong>. No export is required.</p>
      <form id="release-form">
        <label class="field">Exact search<input id="release-query" required maxlength="600"></label>
        <label class="field">Matching details and filters<textarea id="release-filters" required rows="2" placeholder="Example: single 1 oz coins, US buyers, USD, ungraded, premium artwork, exclude sets; item price excluding shipping. Keep these identical for both periods."></textarea></label>
        <div class="formgrid"><label class="field">Latest period ends<input id="release-end" type="date" required max="${yesterday}"></label>
        <label class="field">Marketplace<input id="release-marketplace" value="EBAY_US" required></label>
        <label class="field">Currency<input id="release-currency" value="USD" required pattern="[A-Z]{3}" maxlength="3"></label></div>
        <p class="meta">Review results for the same weight, finish, grading and price range as your planned release. Preset searches are starting points; check their matches.</p>
        <div class="formgrid periods">${['current','previous'].map(p=>`<fieldset><legend>${p==='current'?'Latest':'Previous'} 28 days</legend><p id="${p}-dates" class="meta"></p>
          <label class="field">Units sold<input id="${p}-units" type="number" min="0" step="1" required></label>
          <label class="field">Average sold price<input id="${p}-price" type="number" min="0.01" step="any" placeholder="Leave blank if unavailable"></label>
          <label class="field">Sellers with sales<input id="${p}-sellers" type="number" min="0" step="1" required></label>
          <label class="field">Sell-through % (optional)<input id="${p}-sellthrough" type="number" min="0" step="any"></label></fieldset>`).join('')}</div>
        <details><summary>Compare with my planned release (optional)</summary><div class="formgrid">
          <label class="field">Planned number of coins<input id="release-planned-units" type="number" min="1" step="1" placeholder="199"></label>
          <label class="field">Planned retail price, same currency<input id="release-planned-price" type="number" min="0.01" step="any"></label></div></details>
        <label class="field">Public source/reference URL<input id="release-source" type="url" required value="https://www.ebay.com/sh/research"></label>
        <label class="checkline"><input id="release-confirmed" type="checkbox" required> These are actual units sold for both full date ranges, with identical search filters and price definitions. I checked the results for comparable products.</label>
        <p class="meta">Use 0 only when the report shows zero. With zero sales, enter 0 sellers and leave average price blank.</p>
        <button class="primary" type="submit">Calculate &amp; save on this browser</button>
      </form>
    </details>
    <div class="report-tools"><button id="release-export" type="button">Download saved reports</button><label class="file-button">Load saved reports<input id="release-import" type="file" accept=".json,application/json"></label></div>
    <p id="release-message" class="meta" role="status"></p>
    <details><summary>What the signal means</summary><p class="meta">Compares two complete, consecutive 28-day periods. At least 30 units in the prior period, 60 combined, and three selling sellers per period (except an explicitly zero-sales period). Green: units +20% or more, average sold price no worse than −5%, and optional sell-through no worse than −5 percentage points. Red: zero sales, units −50% or worse, or units −20% with prices −5% or worse. Other sufficient samples are amber. Stale or incomplete evidence stays gray. These are practical screening rules, not a validated forecast or probability of selling out. Averages can change with the mix of designs and sellers. Figures entered here are not independently verified. eBay covers one channel, not the whole market.</p></details>`;
  const val=id=>$(id).value;
  const put=(id,v)=>{$(id).value=v??'';};
  const pct=v=>v===null?'Not provided':(v>0?'+':'')+v.toFixed(1)+'%';
  function dates() {
    try { const p=Readiness.periods(val('release-end'));for(const k of ['current','previous'])$(k+'-dates').textContent=p[k].start+' → '+p[k].end; }
    catch(e) { for(const k of ['current','previous'])$(k+'-dates').textContent='Choose a valid end date'; }
  }
  function report() {
    const r={profile:val('release-profile'),query:val('release-query'),filters:val('release-filters'),marketplace:val('release-marketplace'),currency:val('release-currency'),end:val('release-end'),source_url:val('release-source'),confirmed:$('release-confirmed').checked,planned_units:val('release-planned-units'),planned_price:val('release-planned-price')};
    for(const p of ['current','previous']) {r[p]={};for(const f of ['units','price','sellers','sellthrough'])r[p][f]=val(p+'-'+f);}
    return r;
  }
  function render(r,origin) {
    active=r;
    if(!r) {
      $('release-verdict').innerHTML='<div class="signal gray"><strong>Buying signal: not connected yet</strong><p>Add the two sales summaries below to get a decision for this coin group. Store inventory and eBay asking prices cannot fill these fields.</p><p><b>For now:</b> test the concept or secure dealer commitments before sizing the full run.</p></div>';
      $('release-editor').open=false;return;
    }
    const s=Readiness.evaluate(r,today), c=s.report.current,p=s.report.previous;
    const money=n=>n===null?'—':esc(r.currency)+' '+n.toFixed(2);
    $('release-verdict').innerHTML=`<div class="signal ${s.status}"><strong>${esc(s.label)}</strong><p>${esc(s.action)}</p>
      <ul>${s.reasons.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>
      <p class="meta">${esc(origin)} · ${esc(r.marketplace)} · period ended ${esc(r.end)} · ${s.age_days} day(s) old · <a href="${esc(r.source_url)}" target="_blank" rel="noopener">Source</a></p>
      <div class="tablewrap"><table><tr><th>Completed sales</th><th>Previous 28 days</th><th>Latest 28 days</th><th>Change</th></tr>
      <tr><td>Units sold</td><td>${p.units.toLocaleString()}</td><td>${c.units.toLocaleString()}</td><td>${pct(s.volume)}</td></tr>
      <tr><td>Average realized price</td><td>${money(p.price)}</td><td>${money(c.price)}</td><td>${pct(s.price)}</td></tr>
      <tr><td>Sellers with sales</td><td>${p.sellers}</td><td>${c.sellers}</td><td>—</td></tr>
      <tr><td>Reported sell-through</td><td>${p.sellthrough===null?'—':p.sellthrough+'%'}</td><td>${c.sellthrough===null?'—':c.sellthrough+'%'}</td><td>${s.sellthrough===null?'—':s.sellthrough.toFixed(1)+' pp'}</td></tr></table></div>
      <p class="meta">${esc(r.query)} · ${esc(r.filters)}</p>
      ${r.planned_units?`<p>Your planned run: <b>${r.planned_units} coins</b>${s.run_share===null?'':` — ${s.run_share.toFixed(1)}% of all comparable units sold in the latest 28 days`}. This is market scale, not your expected share or sellout time.</p>`:''}
      ${s.price_gap!==null?`<p>Your planned price: <b>${money(r.planned_price)}</b> (${pct(s.price_gap)} versus the comparable average). Your artwork and packaging still need their own price test.</p>`:''}`;
  }
  function loadProfile() {
    const id=val('release-profile');
    const choices=[...(published||[]).map(r=>({r,origin:'Published aggregate report'})),...local.map(r=>({r,origin:'Saved on this browser · user-entered'}))].filter(x=>x.r.profile===id).sort((a,b)=>b.r.end.localeCompare(a.r.end)||(a.origin.startsWith('Saved')?-1:1));
    let chosen=choices[0],r=null;
    if(chosen) { try {r=Readiness.validate(chosen.r,today);}catch(e){$('release-message').textContent='Saved report is invalid: '+e.message;} }
    $('release-form').reset();
    put('release-query',r?.query??Readiness.profiles.find(p=>p.id===id).query);
    put('release-filters',r?.filters);put('release-end',r?.end??yesterday);
    put('release-marketplace',r?.marketplace??'EBAY_US');put('release-currency',r?.currency??'USD');
    put('release-source',r?.source_url??'https://www.ebay.com/sh/research');
    put('release-planned-units',r?.planned_units);put('release-planned-price',r?.planned_price);
    for(const p of ['current','previous'])for(const f of ['units','price','sellers','sellthrough'])put(p+'-'+f,r?.[p]?.[f]);
    $('release-confirmed').checked=!!r;dates();render(r,chosen?.origin);
    if(r)$('release-editor').open=false;
  }
  function save() {
    try {localStorage.setItem(key,JSON.stringify(local));storageOK=true;}
    catch(e){storageOK=false;}
    $('release-message').textContent=storageOK?'Saved on this browser only. Download a backup to move it to another device. Nothing is uploaded to GitHub or eBay.':'Browser storage is unavailable. Download the reports now to keep them.';
  }
  $('release-profile').onchange=loadProfile;
  $('release-form').oninput=()=>{dates();if(active){$('release-verdict').innerHTML='<div class="signal gray"><strong>Inputs changed</strong><p>Calculate again to update the buying signal.</p></div>';active=null;}};
  $('release-form').onsubmit=event=>{
    event.preventDefault();
    try {const r=Readiness.validate(report(),today);local=local.filter(x=>!(x.profile===r.profile&&x.end===r.end&&x.query===r.query&&x.filters===r.filters&&x.marketplace===r.marketplace&&x.currency===r.currency));local.push(r);save();render(r,'Saved on this browser · user-entered');$('release-editor').open=false;}
    catch(e){$('release-message').textContent=e.message;}
  };
  $('release-export').onclick=()=>{
    const reports=local.length?local:published||[];
    if(!reports.length){$('release-message').textContent='No reports saved yet. Enter completed-sales figures first.';return;}
    const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(reports,null,2)],{type:'application/json'}));a.href=url;a.download='blackbird-release-reports.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  $('release-import').onchange=async event=>{
    try {
      const file=event.target.files[0];if(!file)return;if(file.size>1000000)throw Error('Report file must be under 1 MB.');
      const raw=JSON.parse(await file.text());if(!Array.isArray(raw)||raw.length>500)throw Error('Use a saved report array with at most 500 entries.');
      const incoming=raw.map(r=>Readiness.validate(r,today));
      const merged=new Map([...local,...incoming].map(r=>[JSON.stringify([r.profile,r.end,r.query,r.filters,r.marketplace,r.currency]),r]));
      local=[...merged.values()];save();if(incoming.length)$('release-profile').value=incoming[incoming.length-1].profile;loadProfile();
    }catch(e){$('release-message').textContent='Import failed: '+e.message;}
    finally{event.target.value='';}
  };
  loadProfile();
  if(!storageOK)$('release-message').textContent='Browser storage could not be read. Reports can still be calculated and downloaded.';
}
