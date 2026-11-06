const assert=require('node:assert/strict');
const R=require('../mhi/readiness.js');
const today='2026-11-06';
function report(){return {profile:'eagle',query:'colorized silver eagle',filters:'single 1oz, USD, US buyers, ungraded, item price excluding shipping',marketplace:'EBAY_US',currency:'USD',source_url:'https://www.ebay.com/sh/research',end:'2026-11-05',confirmed:true,current:{units:150,price:150,sellers:8,sellthrough:60},previous:{units:100,price:150,sellers:5,sellthrough:55},planned_units:199,planned_price:175};}
const test=(name,fn)=>{fn();console.log('PASS',name);};
test('exact 28-day adjacent windows',()=>assert.deepEqual(R.periods('2026-11-05'),{current:{start:'2026-10-09',end:'2026-11-05'},previous:{start:'2026-09-11',end:'2026-10-08'}}));
test('volume and prices support green',()=>{const s=R.evaluate(report(),today);assert.equal(s.status,'green');assert.equal(s.volume,50);assert.equal(s.run_share,199/150*100);});
test('current sales zero is weak, not missing',()=>{const r=report();r.current={units:0,sellers:0,price:'',sellthrough:0};assert.equal(R.evaluate(r,today).status,'red');});
test('a missing count is not zero',()=>{const r=report();r.current.units='';assert.throws(()=>R.evaluate(r,today),/required/);});
test('small sample stays gray',()=>{const r=report();r.previous.units=10;assert.equal(R.evaluate(r,today).status,'gray');});
test('seller concentration stays gray',()=>{const r=report();r.current.sellers=1;assert.equal(R.evaluate(r,today).status,'gray');});
test('falling volume and prices is red',()=>{const r=report();r.current.units=70;r.current.price=140;assert.equal(R.evaluate(r,today).status,'red');});
test('missing prices cannot make green',()=>{const r=report();r.current.price='';assert.equal(R.evaluate(r,today).status,'gray');});
test('stale favorable data stays gray',()=>{const r=report();r.end='2026-10-20';assert.equal(R.evaluate(r,today).status,'gray');});
test('partial and invalid calendar dates rejected',()=>{for(const d of ['2026-11-06','2026-12-01','2026-02-30']){const r=report();r.end=d;assert.throws(()=>R.evaluate(r,today));}});
test('different or unconfirmed filters blocked',()=>{const r=report();r.confirmed=false;assert.throws(()=>R.evaluate(r,today),/Confirm/);});
test('zero previous period is not infinite growth',()=>{const r=report();r.previous={units:0,sellers:0,price:'',sellthrough:0};const s=R.evaluate(r,today);assert.equal(s.status,'gray');assert.equal(s.volume,null);});
test('sellthrough deterioration blocks green',()=>{const r=report();r.current.sellthrough=40;assert.equal(R.evaluate(r,today).status,'amber');});
test('planned price does not rewrite market demand',()=>{const r=report();r.planned_price=300;const s=R.evaluate(r,today);assert.equal(s.status,'green');assert.equal(s.price_gap,100);assert(s.reasons.some(x=>x.includes('planned price')));});
test('unsafe source URL rejected',()=>{const r=report();r.source_url='javascript:alert(1)';assert.throws(()=>R.evaluate(r,today));});
test('negative fractional and blank whitespace counts rejected',()=>{for(const n of [-1,1.2,' ',true]){const r=report();r.current.units=n;assert.throws(()=>R.evaluate(r,today));}});
test('missing price retained null after roundtrip',()=>{const r=report();r.current.price='';assert.equal(R.validate(R.validate(r,today),today).current.price,null);});

test('exact green threshold is stable',()=>{const r=report();r.current.units=120;r.previous.price=100;r.current.price=95;assert.equal(R.evaluate(r,today).status,'green');});
