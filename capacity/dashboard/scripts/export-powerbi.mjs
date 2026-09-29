import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { calibrateOrders, createAdvEngine } from "../app/adv-migration.ts";
import { migrationShares } from "../app/liquidity-migration.ts";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const out = resolve(root, "powerbi/data");
mkdirSync(out, { recursive: true });

const live = JSON.parse(readFileSync(resolve(here, "../app/bucket-data.json"), "utf8"));
const universe = JSON.parse(readFileSync(resolve(here, "../app/universe-adv-data.json"), "utf8"));
const buckets = live.buckets;
const migrationBuckets = [...buckets, { label: ">100%", lower: 1, upper: Infinity }];
const params = {
  aum0: 3.4, grossAlpha: .5, trackingError: 1.3, turnover: 13.9, holdings: 40,
  scaleElasticity: .85, tailElasticity: 0, dailyParticipation: 10, maxDays: 10,
  halfLife: 10, maxAum: 15, irThreshold: .4, retainedThreshold: 80,
  ...live.calibration, advVolume: 100,
};

const esc = value => {
  const text = value === Infinity ? "Infinity" : String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const csv = (name, rows) => {
  const headers = Object.keys(rows[0]);
  writeFileSync(resolve(out, name), [headers.join(","), ...rows.map(row => headers.map(h => esc(row[h])).join(","))].join("\n") + "\n");
};
const capture = (days, halfLife) => {
  const decay = Math.log(2) / Math.max(halfLife, .01);
  return (1 - Math.exp(-decay * days)) / (days * (1 - Math.exp(-decay)));
};
const ppf = (q, c, d, scale) => scale * Math.pow(Math.pow(1 - q, -1 / d) - 1, 1 / c);

function createBurrEngine(p) {
  const n = 700;
  const qs = Array.from({ length: n }, (_, i) => (i + .5) / n);
  const base = qs.map(q => ppf(q, p.burrC, p.burrD, p.burrScale));
  const baseDays = base.map(x => Math.min(p.maxDays, Math.max(1, Math.ceil(x / (p.dailyParticipation / 100)))));
  const baseCapture = baseDays.map(d => capture(d, p.halfLife));
  const shareTotal = buckets.reduce((s, b) => s + b.share, 0);
  const observedImpact = buckets.reduce((s, b) => s + b.share * b.cost, 0) / shareTotal;
  const curve = x => p.impactA + p.impactB * Math.pow(Math.max(0, x), p.impactGamma);
  const impactScale = observedImpact / (base.reduce((s, x) => s + curve(x), 0) / n);
  const metric = aum => {
    const ratio = aum / p.aum0, scale = p.burrScale * ratio ** p.scaleElasticity, d = p.burrD * ratio ** -p.tailElasticity;
    let impact = 0, alpha = 0, days = 0, multi = 0, three = 0, part = 0;
    for (let i = 0; i < n; i++) {
      const participation = ppf(qs[i], p.burrC, d, scale);
      const required = Math.min(p.maxDays, Math.max(1, Math.ceil(participation / (p.dailyParticipation / 100))));
      impact += curve(participation * baseDays[i] / required);
      alpha += capture(required, p.halfLife) / baseCapture[i];
      days += required; part += participation;
      multi += required >= 2; three += required >= 3;
    }
    impact = impact / n * impactScale;
    const alphaCapture = alpha / n * 100, implementedAlpha = p.grossAlpha * alphaCapture / 100;
    const annualDrag = 2 * p.turnover / 100 * impact, netAlpha = implementedAlpha - annualDrag / 100;
    return { aum, impact, annualDrag, alphaCapture, implementedAlpha, netAlpha, netIr: netAlpha / p.trackingError, retained: netAlpha / p.grossAlpha * 100, avgDays: days / n, multiDay: multi / n * 100, threePlus: three / n * 100, meanParticipation: part / n * 100, unfinished: 0 };
  };
  return { metric, bucketShares: aum => migrationShares(aum, p, migrationBuckets) };
}

const orders = calibrateOrders(buckets, universe.quantiles);
const adv = createAdvEngine(params, buckets, orders);
const burr = createBurrEngine(params);
const aums = Array.from({ length: 150 }, (_, i) => (i + 1) / 10);
const scenarioRows = [];
const migrationRows = [];
const executionRows = [];
for (const [model, engine] of [["ADV calibrated", adv], ["Burr notional", burr]]) {
  for (const aum of aums) {
    const m = engine.metric(aum);
    scenarioRows.push({ Model: model, AUM_USD_bn: aum, Impact_bp: m.impact, Annual_drag_bp: m.annualDrag, Alpha_capture_pct: m.alphaCapture, Implemented_alpha_pct: m.implementedAlpha, Net_alpha_pct: m.netAlpha, Net_IR: m.netIr, Retained_alpha_pct: m.retained, Average_days: m.avgDays, Multi_day_pct: m.multiDay, Three_plus_days_pct: m.threePlus, Mean_participation_pct_ADV: m.meanParticipation, Unfinished_notional_pct: m.unfinished ?? 0 });
    engine.bucketShares(aum).forEach((share, i) => migrationRows.push({ Model: model, View: "Traded dollars", AUM_USD_bn: aum, Bucket_order: i + 1, Participation_bucket: migrationBuckets[i].label, Share_pct: share }));
    if (model === "ADV calibrated") {
      engine.countShares(aum).forEach((share, i) => migrationRows.push({ Model: model, View: "Parent orders", AUM_USD_bn: aum, Bucket_order: i + 1, Participation_bucket: migrationBuckets[i].label, Share_pct: share }));
      engine.executionShares(aum).forEach((share, i) => executionRows.push({ Model: model, AUM_USD_bn: aum, Outcome_order: i + 1, Execution_outcome: ["Completed in 1 day", "Completed in 2–5 days", "Completed in 6+ days", "Beyond maximum horizon"][i], Parent_orders_pct: share }));
    }
  }
}
const countFit = { aum0: params.aum0, ...live.countCalibration };
for (const aum of aums) migrationShares(aum, countFit, migrationBuckets).forEach((share, i) => migrationRows.push({ Model: "Burr count calibrated", View: "Parent orders", AUM_USD_bn: aum, Bucket_order: i + 1, Participation_bucket: migrationBuckets[i].label, Share_pct: share }));

const alphaRows = [];
for (const aum of [3.4, 6.8]) for (let day = 0; day <= 126; day++) for (const halfLife of [5, 10, 20]) alphaRows.push({ AUM_USD_bn: aum, Half_life_days: halfLife, Day: day, Remaining_alpha_pct: 100 * 2 ** (-day / halfLife), Remaining_alpha_pct_times_AUM: 100 * 2 ** (-day / halfLife) * aum / params.aum0 });

csv("scenarios.csv", scenarioRows);
csv("migration.csv", migrationRows);
csv("execution_outcomes.csv", executionRows);
csv("alpha_decay.csv", alphaRows);
csv("buckets.csv", buckets.map((b, i) => ({ Bucket_order: i + 1, Participation_bucket: b.label, Lower_ADV_fraction: b.lower, Upper_ADV_fraction: b.upper, Parent_orders: b.trades, Traded_value_USD_m: b.valueUsdMillion, Notional_share_pct: b.share, Expected_impact_bp: b.cost, Realised_impact_bp: b.realised })));
csv("adv_quantiles.csv", universe.quantiles.map(q => ({ Percentile: q.percentile, ADV_USD: q.advUsd })));
csv("parameters.csv", Object.entries(params).filter(([,v]) => typeof v === "number").map(([name, value]) => ({ Parameter: name, Value: value })));
csv("calibrations.csv", [
  { Calibration: "Burr traded-dollar", c: live.calibration.burrC, d: live.calibration.burrD, Scale: live.calibration.burrScale, Eta: params.scaleElasticity, Kappa: params.tailElasticity, RMSE_pp: "" },
  { Calibration: "Burr parent-order count", c: countFit.burrC, d: countFit.burrD, Scale: countFit.burrScale, Eta: countFit.scaleElasticity, Kappa: countFit.tailElasticity, RMSE_pp: countFit.rmsePercentagePoints },
]);
console.log(`Power BI data written to ${out}`);
