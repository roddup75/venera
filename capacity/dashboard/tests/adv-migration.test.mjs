import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {calibrateOrders,createAdvEngine,advAt} from '../app/adv-migration.ts';
import {migrationShares} from '../app/liquidity-migration.ts';
const {buckets,calibration}=JSON.parse(readFileSync(new URL('../app/bucket-data.json',import.meta.url)));
const {quantiles}=JSON.parse(readFileSync(new URL('../app/universe-adv-data.json',import.meta.url)));
const value=buckets.reduce((s,b)=>s+b.valueUsdMillion*1e6,0);
const params={holdings:40,turnover:value/(2*3.4e9)*100,dailyParticipation:20,maxDays:10,halfLife:10,grossAlpha:.5,trackingError:1.3,...calibration,advVolume:100};
const near=(a,b,tol=1e-7)=>assert.ok(Math.abs(a-b)<=tol*Math.max(1,Math.abs(b)),`${a} != ${b}`);
for (const preference of [-2,0,2]) test(`Joint calibration reconciles both marginals, preference ${preference}`,()=>{
 const orders=calibrateOrders(buckets,quantiles,preference);
 buckets.forEach((b,i)=>{const rows=orders.filter(o=>o.bucket===i);near(rows.reduce((s,o)=>s+o.count,0),b.trades);near(rows.reduce((s,o)=>s+o.count*o.ticket,0),b.valueUsdMillion*1e6);assert.ok(rows.every(o=>o.ticket/o.adv>b.lower && o.ticket/o.adv<b.upper));});
 const e=createAdvEngine(params,buckets,orders); const m=e.metric(3.4);
 near(m.annualOrders,971);near(m.annualValue,value);near(m.alphaCapture,100);near(m.multiDay,0);near(m.threePlus,0);near(m.unfinished,0);near(e.bucketShares(3.4).reduce((s,x)=>s+x,0),100);
 buckets.forEach((b,i)=>near(e.bucketShares(3.4)[i],b.valueUsdMillion*1e6/value*100));
});
const orders=calibrateOrders(buckets,quantiles);
test('Scaling preserves trading identity and changes frequency independently of ticket size',()=>{
 for(const holdings of [20,40,80])for(const turnover of [0,13.9,40]){const e=createAdvEngine({...params,holdings,turnover},buckets,orders);near(e.metric(6.8).annualValue,2*6.8e9*turnover/100);assert.ok(Number.isFinite(e.metric(6.8).netIr));}
 const e=createAdvEngine(params,buckets,orders),twice=createAdvEngine({...params,turnover:params.turnover*2},buckets,orders);near(twice.metric(3.4).annualOrders,1942);e.bucketShares(3.4).forEach((x,i)=>near(x,twice.bucketShares(3.4)[i]));
});
test('Stress preserves incomplete orders and uncapped required horizons',()=>{
 const normal=createAdvEngine(params,buckets,orders), stressed=createAdvEngine({...params,advVolume:50},buckets,orders);
 near(normal.metric(6.8).meanParticipation,stressed.metric(3.4).meanParticipation);
 assert.ok(stressed.metric(27.2).unfinished>0);assert.ok(stressed.metric(27.2).alphaCapture<100);
 assert.ok(stressed.metric(27.2).avgDays>normal.metric(27.2).avgDays);
});
test('Daily participation and maximum horizon change execution outcomes, not participation buckets',()=>{
 const base=createAdvEngine(params,buckets,orders), slow=createAdvEngine({...params,dailyParticipation:10},buckets,orders), short=createAdvEngine({...params,maxDays:2},buckets,orders);
 base.countShares(6.8).forEach((x,i)=>near(x,slow.countShares(6.8)[i]));
 assert.notDeepEqual(base.executionShares(6.8),slow.executionShares(6.8));
 assert.ok(short.executionShares(13.6)[3]>base.executionShares(13.6)[3]);
 near(base.executionShares(6.8).reduce((s,x)=>s+x,0),100);
});
test('Quantile interpolation preserves all supplied boundaries',()=>quantiles.forEach(q=>near(advAt(q.percentile/100,quantiles),q.advUsd)));
test('Impossible bucket means report calibration failure',()=>assert.throws(()=>calibrateOrders([{...buckets[0],valueUsdMillion:1e9}],quantiles),/Cannot reconcile/));
test('Count-calibrated Burr improves the fit to ADV parent-order migration',()=>{
 const orders=calibrateOrders(buckets,quantiles), engine=createAdvEngine(params,buckets,orders);
 const edges=[...buckets,{lower:1,upper:Infinity}], fit={aum0:3.4,...JSON.parse(readFileSync(new URL('../app/bucket-data.json',import.meta.url))).countCalibration};
 const old={aum0:3.4,burrC:calibration.burrC,burrD:calibration.burrD,burrScale:calibration.burrScale,scaleElasticity:.85,tailElasticity:0};
 const targets=[3.4,6.8,13.6].map(a=>engine.countShares(a));
 const rmse=model=>Math.sqrt(targets.flatMap((target,j)=>migrationShares([3.4,6.8,13.6][j],model,edges).map((x,i)=>(x-target[i])**2)).reduce((s,x)=>s+x,0)/21);
 assert.ok(rmse(fit)<rmse(old));
 near(rmse(fit),fit.rmsePercentagePoints,2e-3);
});
