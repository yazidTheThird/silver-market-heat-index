/* Shared browser/Node release-readiness rules. No asking-price input affects the verdict. */
(function(root) {
  'use strict';
  const DAY = 86400000;
  const profiles = [
    {id:'eagle', name:'Colorized 1 oz Silver Eagles', query:'(colorized OR colourised OR colourized) "silver eagle" "1 oz" -plated -replica -copy -lot -set'},
    {id:'maple', name:'Colorized 1 oz Silver Maples', query:'(colorized OR colourised OR colourized) "silver maple" "1 oz" -plated -replica -copy -lot -set'},
    {id:'libertad', name:'Colorized 1 oz Silver Libertads', query:'(colorized OR colourised OR colourized) silver libertad ("1 oz" OR "1 onza") -plated -replica -copy -lot -set'},
    {id:'custom', name:'My comparable coin group', query:''}
  ];
  function day(s) {
    if(typeof s!=='string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) throw Error('Use dates in YYYY-MM-DD format.');
    const n=Date.parse(s+'T00:00:00Z');
    if(!Number.isFinite(n) || new Date(n).toISOString().slice(0,10)!==s) throw Error('Invalid calendar date.');
    return n;
  }
  const iso = n => new Date(n).toISOString().slice(0,10);
  function periods(end) {
    const n=day(end);
    return {current:{start:iso(n-27*DAY),end},previous:{start:iso(n-55*DAY),end:iso(n-28*DAY)}};
  }
  function number(v,label,integer=false,optional=false) {
    if((typeof v==='string' && v.trim()==='') || v===null || v===undefined) {
      if(optional)return null;
      throw Error(label+' is required; enter 0 only when the report explicitly shows zero.');
    }
    if(typeof v==='boolean' || !['string','number'].includes(typeof v))throw Error('Invalid '+label+'.');
    const n=Number(v);
    if(!Number.isFinite(n) || n<0 || (integer&&!Number.isInteger(n)))throw Error('Invalid '+label+'.');
    return n;
  }
  function validate(input,today=iso(Date.now())) {
    if(!input || typeof input!=='object')throw Error('A report is required.');
    const r=JSON.parse(JSON.stringify(input));
    for(const k of ['profile','query','filters','marketplace','currency','source_url','end']) {
      if(typeof r[k]!=='string' || !r[k].trim())throw Error(k.replaceAll('_',' ')+' is required.');
      r[k]=r[k].trim();
    }
    if(!profiles.some(p=>p.id===r.profile))throw Error('Choose a supported coin group.');
    if(!/^[A-Z]{3}$/.test(r.currency))throw Error('Use a three-letter currency such as USD.');
    const u=new URL(r.source_url);
    if(u.protocol!=='https:' || u.username || u.password)throw Error('Use a public HTTPS source link without credentials.');
    if(day(r.end)>=day(today))throw Error('Use a completed period ending before today.');
    if(r.confirmed!==true)throw Error('Confirm both full periods use identical filters and actual units sold.');
    r.periods=periods(r.end);
    for(const key of ['current','previous']) {
      const p=r[key];if(!p || typeof p!=='object')throw Error('Both periods are required.');
      p.units=number(p.units,key+' units sold',true);
      p.sellers=number(p.sellers,key+' selling sellers',true);
      p.price=number(p.price,key+' average sold price',false,true);
      p.sellthrough=number(p.sellthrough,key+' sell-through percentage',false,true);
      if(p.units===0 && (p.sellers!==0 || p.price!==null))throw Error('With zero sales, enter 0 sellers and leave sold price blank.');
      if(p.units>0 && (p.sellers<1 || p.sellers>p.units))throw Error('Selling sellers must be between 1 and units sold.');
      if(p.price!==null && p.price<=0)throw Error('Average sold price must be positive or blank.');
      // eBay sell-through definitions can exceed 100%; never use this as a probability.
    }
    r.planned_units=number(r.planned_units,'planned run',true,true);
    r.planned_price=number(r.planned_price,'planned retail price',false,true);
    if(r.planned_units===0 || r.planned_price===0)throw Error('Planned run and price must be positive or blank.');
    return r;
  }
  function evaluate(input,today=iso(Date.now())) {
    const r=validate(input,today), c=r.current,p=r.previous;
    const rounded=n=>Math.round(n*1e8)/1e8;
    const volume=p.units ? rounded((c.units/p.units-1)*100) : null;
    const price=c.price!==null&&p.price!==null ? rounded((c.price/p.price-1)*100) : null;
    const sellthrough=c.sellthrough!==null&&p.sellthrough!==null ? c.sellthrough-p.sellthrough : null;
    const result={report:r,status:'gray',label:'Not enough evidence',reasons:[],volume,price,sellthrough,
      action:'Use a small test or secure dealer commitments before choosing the full run.',
      age_days:(day(today)-day(r.end))/DAY,
      run_share:c.units&&r.planned_units ? 100*r.planned_units/c.units : null,
      price_gap:c.price&&r.planned_price ? 100*(r.planned_price/c.price-1) : null};
    if(result.age_days>10)result.reasons.push('The latest period is more than 10 days old. Refresh it before using the signal.');
    if(p.units<30 || c.units+p.units<60)result.reasons.push('Need at least 30 prior-period units and 60 units across both periods.');
    if(p.sellers<3 || (c.units>0 && c.sellers<3))result.reasons.push('Sales are concentrated in fewer than three selling sellers in a period.');
    if(result.reasons.length)return result;
    if(c.units===0 || volume<=-50 || (volume<=-20 && price!==null && price<=-5)) {
      result.status='red';result.label='Buying is weak';
      result.action='Reduce the initial run or wait for stronger orders; avoid relying on a fast sellout.';
      result.reasons.push(c.units===0?'No comparable units sold in the latest complete period.':volume<=-50?'Comparable units sold fell by at least 50%.':'Units sold fell at least 20% and realized prices fell at least 5%.');
    } else if(price===null) {
      result.reasons.push('Average realized prices are missing; volume alone cannot earn a favorable launch signal.');
    } else if(volume>=20 && price>=-5 && (sellthrough===null || sellthrough>=-5)) {
      result.status='green';result.label='Buying is improving';
      result.action='Conditions support testing this coin group. Size the run using your own dealer orders and audience response.';
      result.reasons.push('Units sold rose at least 20% while average realized prices held within 5%.');
    } else {
      result.status='amber';result.label='Buying is steady or mixed';
      result.action='Launch selectively: test the design and secure initial orders before committing the full run.';
      result.reasons.push('The comparable sales do not meet the improving or weak thresholds.');
    }
    if(sellthrough!==null && sellthrough<-5)result.reasons.push('Reported sell-through fell by more than 5 percentage points.');
    if(result.price_gap!==null && result.price_gap>20)result.reasons.push('Your planned price is over 20% above the comparable average; test willingness to pay for your design.');
    return result;
  }
  const api={profiles,periods,validate,evaluate};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.Readiness=api;
})(typeof globalThis!=='undefined'?globalThis:this);
