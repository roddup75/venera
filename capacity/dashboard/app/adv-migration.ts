/** Synthetic weighted parent orders, calibrated to count and dollar totals.
 * ADV percentiles define a prior, not a constraint on traded-stock frequencies.
 * Minimum-relative-entropy tilting within each participation bucket matches its mean ticket.
 */
export type ObservedBucket = { lower: number; upper: number; trades: number; valueUsdMillion: number; cost: number; label: string };
export type AdvPoint = { percentile: number; advUsd: number };
export type Order = { adv: number; ticket: number; count: number; bucket: number };
export const HISTORICAL_AUM = 3.4e9;
export const HISTORICAL_HOLDINGS = 40;
export function advAt(q: number, points: AdvPoint[]) {
  const hi = points.findIndex(p => p.percentile >= q * 100);
  if (hi <= 0) return points[Math.max(hi, 0)].advUsd;
  const a = points[hi - 1], b = points[hi];
  const t = (q * 100 - a.percentile) / (b.percentile - a.percentile);
  return Math.exp(Math.log(a.advUsd) * (1 - t) + Math.log(b.advUsd) * t);
}
export function calibrateOrders(buckets: ObservedBucket[], points: AdvPoint[], preference = 0) {
  return buckets.flatMap((b, bucket): Order[] => {
    const mean = b.valueUsdMillion * 1e6 / b.trades;
    const cells: { adv: number; ticket: number; prior: number }[] = [];
    for (let j = 0; j < 100; j++) {
      const q = (j + .5) / 100, adv = advAt(q, points);
      for (let k = 0; k < 16; k++) {
        const part = b.lower + (b.upper - b.lower) * (k + .5) / 16;
        const ticket = part * adv;
        // Broad log-ticket prior around observed bucket mean; fixed log SD = 1.5.
        const prior = preference * (2 * q - 1) - .5 * (Math.log(ticket / mean) / 1.5) ** 2;
        cells.push({ adv, ticket, prior });
      }
    }
    const maximum = Math.max(...cells.map(c => c.ticket));
    if (!(mean > Math.min(...cells.map(c => c.ticket)) && mean < maximum)) throw new Error(`Cannot reconcile ${b.label} with supplied ADV support`);
    const weights = (tilt: number) => {
      const logs = cells.map(c => c.prior + tilt * c.ticket / maximum);
      const top = Math.max(...logs), ws = logs.map(x => Math.exp(x - top));
      const total = ws.reduce((s,x) => s+x,0);
      return ws.map(x => x / total);
    };
    const expectation = (t: number) => weights(t).reduce((s,w,i) => s+w*cells[i].ticket,0);
    let lo = -1, hi = 1;
    while (expectation(lo) > mean && lo > -1e9) lo *= 2;
    while (expectation(hi) < mean && hi < 1e9) hi *= 2;
    for (let i = 0; i < 70; i++) { const mid = (lo+hi)/2; if (expectation(mid) < mean) lo = mid; else hi = mid; }
    const ws = weights((lo+hi)/2);
    return cells.map((c,i) => ({ adv: c.adv, ticket: c.ticket, count: ws[i]*b.trades, bucket }));
  });
}
export type AdvScenario = { holdings: number; turnover: number; dailyParticipation: number; maxDays: number; halfLife: number; grossAlpha: number; trackingError: number; impactA: number; impactB: number; impactGamma: number; advVolume: number };
const capture = (d: number, h: number) => { const z = Math.log(2)/Math.max(h,.01); return -Math.expm1(-z*d)/(d * -Math.expm1(-z)); };
export function createAdvEngine(p: AdvScenario, buckets: ObservedBucket[], orders: Order[]) {
  const baseValue = buckets.reduce((s,b) => s+b.valueUsdMillion*1e6,0);
  const historicalTurnover = baseValue / (2*HISTORICAL_AUM);
  const rho = Math.max(p.dailyParticipation/100,.0001), horizon = Math.max(1,Math.floor(p.maxDays));
  const cost = (x: number) => p.impactA+p.impactB*Math.pow(x,p.impactGamma);
  const execution = (part: number, demonstrated: number) => {
    const dailyCapacity = Math.max(rho,demonstrated);
    const required = Math.max(1,Math.ceil(part/dailyCapacity-1e-12));
    const days = Math.min(horizon,required), fraction = Math.min(1,horizon*dailyCapacity/part);
    return { required, fraction, alpha: fraction*capture(days,p.halfLife), cost: cost(Math.min(part,dailyCapacity)) };
  };
  let baseAlpha=0, baseCost=0;
  for (const o of orders) { const demonstrated=o.ticket/o.adv, e=execution(demonstrated,demonstrated), w=o.ticket*o.count/baseValue; baseAlpha+=w*e.alpha; baseCost+=w*e.fraction*e.cost; }
  const observedCost=buckets.reduce((s,b)=>s+b.valueUsdMillion*1e6*b.cost,0)/baseValue;
  const costScale=observedCost/Math.max(baseCost,1e-12);
  const distribution = (aum: number) => {
    const size=Math.max(aum,.0001)*1e9/HISTORICAL_AUM*HISTORICAL_HOLDINGS/Math.max(p.holdings,1);
    const frequency=Math.max(p.holdings,1)/HISTORICAL_HOLDINGS*Math.max(p.turnover,0)/100/historicalTurnover;
    const counts=Array(buckets.length+1).fill(0), values=Array(buckets.length+1).fill(0);
    let alpha=0, impact=0, days=0, multi=0, three=0, participation=0, unfinished=0;
    for (const o of orders) {
      const ticket=o.ticket*size, part=ticket/(o.adv*Math.max(p.advVolume,.01)/100);
      const index=buckets.findIndex(b=>part<=b.upper), b=index<0?buckets.length:index;
      counts[b]+=o.count*frequency; values[b]+=ticket*o.count*frequency;
      const w=o.ticket*o.count/baseValue, e=execution(part,o.ticket/o.adv);
      alpha+=w*e.alpha; impact+=w*e.fraction*e.cost; days+=w*e.required;
      multi+=w*(e.required>=2?1:0); three+=w*(e.required>=3?1:0);
      participation+=w*part; unfinished+=w*(1-e.fraction);
    }
    return { counts, values, alpha, impact, days, multi, three, participation, unfinished };
  };
  const shares=(xs:number[])=>{const total=xs.reduce((s,x)=>s+x,0);return xs.map(x=>total?100*x/total:0);};
  const metric=(aum:number)=>{
    const d=distribution(aum), impact=d.impact*costScale, alphaCapture=100*d.alpha/Math.max(baseAlpha,1e-12);
    const implementedAlpha=p.grossAlpha*alphaCapture/100, annualDrag=2*p.turnover/100*impact, netAlpha=implementedAlpha-annualDrag/100;
    return {aum,impact,annualDrag,alphaCapture,implementedAlpha,netAlpha,netIr:netAlpha/Math.max(p.trackingError,.01),retained:100*netAlpha/Math.max(p.grossAlpha,.01),avgDays:d.days,multiDay:100*d.multi,threePlus:100*d.three,meanParticipation:100*d.participation,unfinished:100*d.unfinished,annualOrders:d.counts.reduce((s,x)=>s+x,0),annualValue:d.values.reduce((s,x)=>s+x,0)};
  };
  const executionShares=(aum:number)=>{
    const size=Math.max(aum,.0001)*1e9/HISTORICAL_AUM*HISTORICAL_HOLDINGS/Math.max(p.holdings,1);
    const frequency=Math.max(p.holdings,1)/HISTORICAL_HOLDINGS*Math.max(p.turnover,0)/100/historicalTurnover;
    const groups=[0,0,0,0];
    for(const o of orders){
      const part=o.ticket*size/(o.adv*Math.max(p.advVolume,.01)/100);
      const dailyCapacity=Math.max(rho,o.ticket/o.adv);
      const required=Math.max(1,Math.ceil(part/dailyCapacity-1e-12));
      const group=required>horizon?3:required===1?0:required<=5?1:2;
      groups[group]+=o.count*frequency;
    }
    return shares(groups);
  };
  return { metric, distribution, bucketShares:(aum:number)=>shares(distribution(aum).values), countShares:(aum:number)=>shares(distribution(aum).counts), executionShares };
}
