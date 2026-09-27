"use client";

import { Fragment, useMemo, useState } from "react";
import liveBucketData from "./bucket-data.json";
import { migrationShares } from "./liquidity-migration";
import ImpactDemo from "./impact-demo";
import AlphaDecayDemo from "./alpha-decay-demo";
import {
  Activity,
  ArrowDownToLine,
  BarChart3,
  ChevronDown,
  CircleGauge,
  Clock3,
  Info,
  RefreshCcw,
  Settings2,
  TrendingDown,
  WalletCards,
} from "lucide-react";

type Params = {
  aum0: number;
  grossAlpha: number;
  trackingError: number;
  turnover: number;
  holdings: number;
  scaleElasticity: number;
  tailElasticity: number;
  dailyParticipation: number;
  maxDays: number;
  halfLife: number;
  burrC: number;
  burrD: number;
  burrScale: number;
  impactA: number;
  impactB: number;
  impactGamma: number;
  maxAum: number;
  irThreshold: number;
  retainedThreshold: number;
};

type Bucket = { label: string; lower: number; upper: number; p: number; share: number; cost: number; realised: number; trades: number; valueUsdMillion: number };
type Metric = {
  aum: number;
  impact: number;
  annualDrag: number;
  alphaCapture: number;
  implementedAlpha: number;
  netAlpha: number;
  netIr: number;
  retained: number;
  avgDays: number;
  multiDay: number;
  threePlus: number;
  meanParticipation: number;
};

const DEFAULTS: Params = {
  aum0: 4,
  grossAlpha: 0.5,
  trackingError: 1.3,
  turnover: 40,
  holdings: 40,
  scaleElasticity: 0.85,
  tailElasticity: 0,
  dailyParticipation: 10,
  maxDays: 10,
  halfLife: 10,
  ...liveBucketData.calibration,
  maxAum: 15,
  irThreshold: 0.4,
  retainedThreshold: 80,
};

const DEFAULT_BUCKETS: Bucket[] = liveBucketData.buckets;
const MIGRATION_BUCKETS = [...DEFAULT_BUCKETS, { label: ">100%", lower: 1, upper: Infinity }];

const COLORS = ["#172f2a", "#1d6f61", "#d7a339", "#bc5a3c"];

function burrCdf(x: number, c: number, d: number, scale: number) {
  if (x <= 0) return 0;
  return 1 - Math.pow(1 + Math.pow(x / Math.max(scale, 1e-8), c), -d);
}

function burrPpf(q: number, c: number, d: number, scale: number) {
  return scale * Math.pow(Math.pow(1 - q, -1 / d) - 1, 1 / c);
}

function alphaCapture(days: number, halfLife: number) {
  const decay = Math.log(2) / Math.max(halfLife, 0.01);
  return (1 - Math.exp(-decay * days)) / (days * (1 - Math.exp(-decay)));
}

function makeEngine(p: Params, buckets: Bucket[]) {
  const n = 700;
  const quantiles = Array.from({ length: n }, (_, i) => (i + 0.5) / n);
  const basePart = quantiles.map((q) => burrPpf(q, p.burrC, p.burrD, p.burrScale));
  const baseDays = basePart.map((x) => Math.min(p.maxDays, Math.max(1, Math.ceil(x / (p.dailyParticipation / 100)))));
  const baseCapture = baseDays.map((d) => alphaCapture(d, p.halfLife));
  const shareTotal = buckets.reduce((s, b) => s + Math.max(0, b.share), 0) || 1;
  const observedImpact = buckets.reduce((s, b) => s + Math.max(0, b.share) * b.cost, 0) / shareTotal;
  const curve = (x: number) => p.impactA + p.impactB * Math.pow(Math.max(0, x), p.impactGamma);
  const baseModelImpact = basePart.reduce((s, x) => s + curve(x), 0) / n;
  const impactCalibration = observedImpact / Math.max(baseModelImpact, 1e-8);

  const metric = (aum: number): Metric => {
    const ratio = Math.max(aum, 0.01) / Math.max(p.aum0, 0.01);
    const scale = p.burrScale * Math.pow(ratio, p.scaleElasticity);
    const d = p.burrD * Math.pow(ratio, -p.tailElasticity);
    let impactSum = 0;
    let captureSum = 0;
    let daysSum = 0;
    let multi = 0;
    let three = 0;
    let partSum = 0;
    for (let i = 0; i < n; i++) {
      const part = burrPpf(quantiles[i], p.burrC, d, scale);
      const days = Math.min(p.maxDays, Math.max(1, Math.ceil(part / (p.dailyParticipation / 100))));
      const effective = part * baseDays[i] / days;
      impactSum += curve(effective);
      captureSum += alphaCapture(days, p.halfLife) / baseCapture[i];
      daysSum += days;
      partSum += part;
      if (days >= 2) multi++;
      if (days >= 3) three++;
    }
    const impact = (impactSum / n) * impactCalibration;
    const alphaCapturePct = (captureSum / n) * 100;
    const implementedAlpha = p.grossAlpha * alphaCapturePct / 100;
    const annualDrag = 2 * (p.turnover / 100) * impact;
    const netAlpha = implementedAlpha - annualDrag / 100;
    return {
      aum,
      impact,
      annualDrag,
      alphaCapture: alphaCapturePct,
      implementedAlpha,
      netAlpha,
      netIr: netAlpha / Math.max(p.trackingError, 0.01),
      retained: netAlpha / Math.max(p.grossAlpha, 0.01) * 100,
      avgDays: daysSum / n,
      multiDay: multi / n * 100,
      threePlus: three / n * 100,
      meanParticipation: partSum / n * 100,
    };
  };

  const bucketShares = (aum: number) => {
    return migrationShares(Math.max(aum, 0.01), { ...p, aum0: Math.max(p.aum0, 0.01) }, MIGRATION_BUCKETS);
  };
  return { metric, bucketShares };
}

function fmt(v: number, digits = 2) {
  return Number.isFinite(v) ? v.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}

function Field({ label, value, onChange, suffix, step = 0.1, min = 0, hint }: {
  label: string; value: number; onChange: (v: number) => void; suffix?: string; step?: number; min?: number; hint?: string;
}) {
  return <label className="field">
    <span>{label}{hint && <span className="hint" title={hint}><Info size={13} /></span>}</span>
    <span className="input-wrap"><input type="number" value={value} step={step} min={min} onChange={(e) => onChange(Number(e.target.value))} />{suffix && <em>{suffix}</em>}</span>
  </label>;
}

type AumMarker = { label: string; value: number; color: string; dash: string };

function LineChart({ data, series, threshold, yLabel, autoScale = false, height = 250, markers = [] }: {
  data: Metric[];
  series: { key: keyof Metric; label: string; color: string }[];
  threshold?: number;
  yLabel: string;
  autoScale?: boolean;
  height?: number;
  markers?: AumMarker[];
}) {
  const w = 760, h = height, l = 54, r = 18, t = 18, b = 38;
  const values = data.flatMap((d) => series.map((s) => Number(d[s.key]))).concat(threshold === undefined ? [] : [threshold]).filter(Number.isFinite);
  const dataMin = values.length ? Math.min(...values) : 0;
  const dataMax = values.length ? Math.max(...values) : 1;
  // Leave breathing room at both ends, including for a flat series.
  const padding = Math.max((dataMax - dataMin) * 0.08, Math.max(Math.abs(dataMin), Math.abs(dataMax), 0.01) * 0.005);
  const minY = autoScale ? dataMin - padding : Math.min(0, dataMin);
  const maxY = autoScale ? dataMax + padding : Math.max(dataMax, 0.01);
  const tickStep = (maxY - minY) / 4;
  const tickDigits = Math.min(8, Math.max(0, 1 - Math.floor(Math.log10(tickStep))));
  const minX = data[0]?.aum ?? 0;
  const maxX = data.at(-1)?.aum ?? 1;
  const xAum = (aum: number) => l + (aum - minX) / Math.max(maxX - minX, 1e-8) * (w - l - r);
  const x = (i: number) => xAum(data[i].aum);
  const visibleMarkers = markers.filter(m => m.value >= minX && m.value <= maxX);
  const y = (v: number) => t + (maxY - v) / Math.max(maxY - minY, 1e-8) * (h - t - b);
  const path = (key: keyof Metric) => data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(d[key])).toFixed(1)}`).join(" ");
  return <div className="chart-shell">
    <div className="legend">{series.map((s) => <span key={s.label}><i style={{ background: s.color }} />{s.label}</span>)}{markers.map(m => <span key={m.label}><svg width="20" height="4" aria-hidden="true"><line x1="0" x2="20" y1="2" y2="2" stroke={m.color} strokeWidth="2" strokeDasharray={m.dash}/></svg>{m.label}: ${fmt(m.value,2)}bn{m.value < minX || m.value > maxX ? " (outside chart range)" : ""}</span>)}</div>
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${yLabel} by AUM`}>
      {[0, .25, .5, .75, 1].map((f) => { const yy = t + f * (h - t - b); const val = maxY - f * (maxY - minY); return <g key={f}><line x1={l} y1={yy} x2={w-r} y2={yy} className="grid"/><text x={l-8} y={yy+4} textAnchor="end" className="axis-label">{fmt(val, autoScale ? tickDigits : val > 10 ? 0 : 1)}</text></g>; })}
      {threshold !== undefined && <line x1={l} y1={Number(y(threshold).toFixed(4))} x2={w-r} y2={Number(y(threshold).toFixed(4))} className="threshold" />}
      {series.map((s) => <path key={String(s.key)} d={path(s.key)} fill="none" stroke={s.color} strokeWidth="3" strokeLinecap="round" />)}
      {visibleMarkers.map(m => <line key={m.label} x1={xAum(m.value)} x2={xAum(m.value)} y1={t} y2={h-b} stroke={m.color} strokeWidth="2" strokeDasharray={m.dash} aria-label={`${m.label}: $${fmt(m.value,2)}bn`}><title>{m.label}: ${fmt(m.value,2)}bn</title></line>)}
      {[0,.25,.5,.75,1].map(f => <text key={f} x={xAum(minX+f*(maxX-minX))} y={h-18} textAnchor={f===0 ? "start" : f===1 ? "end" : "middle"} className="axis-label">${fmt(minX+f*(maxX-minX),1)}bn</text>)}
      <text x={(l+w-r)/2} y={h-3} textAnchor="middle" className="axis-label">AUM (USD)</text>
    </svg>
  </div>;
}

function MigrationChart({ labels, sets }: { labels: string[]; sets: { label: string; values: number[]; color: string }[] }) {
  const max = Math.max(1, ...sets.flatMap((s) => s.values));
  return <div className="migration-chart">
    <div className="legend">{sets.map((s) => <span key={s.label}><i style={{ background: s.color }} />{s.label}</span>)}</div>
    <div className="bars">{labels.map((label, i) => <div className="bar-group" key={label}>
      <div className="bar-stack">{sets.map((s) => <div key={s.label} className="bar" title={`${s.label}: ${fmt(s.values[i],1)}%`} style={{ height: `${s.values[i]/max*150}px`, paddingTop: s.values[i] > 6 ? 3 : 0, background: s.color }}><span>{s.values[i] > 6 ? fmt(s.values[i],0) : ""}</span></div>)}</div>
      <small>{label}</small>
    </div>)}</div>
  </div>;
}

function MigrationDemo({ params }: { params: Params }) {
  const initial = () => ({ aum0: String(params.aum0), aum1: String(params.aum0 * 2), aum2: String(params.aum0 * 4), eta: String(params.scaleElasticity), kappa: String(params.tailElasticity) });
  const [inputs, setInputs] = useState(initial);
  const fields = [
    { key: "aum0", label: "Reference AUM A₀ ($bn)", min: 0.01, max: 1000, step: 0.5 },
    { key: "aum1", label: "Scenario 1 AUM ($bn)", min: 0.01, max: 1000, step: 0.5 },
    { key: "aum2", label: "Scenario 2 AUM ($bn)", min: 0.01, max: 1000, step: 0.5 },
    { key: "eta", label: "η · Scale elasticity", min: 0, max: 2, step: 0.05 },
    { key: "kappa", label: "κ · Tail thickening", min: 0, max: 1, step: 0.05 },
  ] as const;
  const valid = fields.every(f => inputs[f.key].trim() !== "" && Number.isFinite(Number(inputs[f.key])) && Number(inputs[f.key]) >= f.min && Number(inputs[f.key]) <= f.max);
  const demo = { ...params, aum0: Number(inputs.aum0), scaleElasticity: Number(inputs.eta), tailElasticity: Number(inputs.kappa) };
  const aums = [demo.aum0, Number(inputs.aum1), Number(inputs.aum2)];
  const sets = valid ? aums.map((aum, i) => ({ label: `${["Reference", "Scenario 1", "Scenario 2"][i]} · $${fmt(aum,2)}bn`, values: migrationShares(aum, demo, MIGRATION_BUCKETS), color: COLORS[i] })) : [];
  const tailIndices = aums.map(aum => demo.burrC * demo.burrD * Math.pow(aum / demo.aum0, -demo.tailElasticity));
  return <article className="card table-card demo-block">
    <div className="card-head"><div><h2>1. Distributional liquidity migration</h2><p>Explore how AUM and migration assumptions change the distribution of traded notional.</p></div><button className="ghost" onClick={() => setInputs(initial())}>Reset demo</button></div>
    <p>These controls are for this demo. They start from the dashboard assumptions and use its fitted Burr parameters. They do not change the main capacity case.</p>
    <div className="demo-controls">{fields.map(f => <label className="field" key={f.key}><span>{f.label}</span><span className="input-wrap"><input type="number" min={f.min} max={f.max} step={f.step} value={inputs[f.key]} onChange={e => setInputs(s => ({ ...s, [f.key]: e.target.value }))}/></span></label>)}</div>
    <div className="demo-explanation"><p><strong>η (eta)</strong> changes participation scale as AUM grows. At η = 0, scale stays fixed; at η = 1, it grows proportionally to AUM.</p><p><strong>κ (kappa)</strong> reduces the Burr shape d as AUM grows, making the upper tail heavier. At κ = 0, d stays fixed.</p></div>
    <p className="demo-formula">λ(A) = λ₀ × (A / A₀)<sup>η</sup> &nbsp; · &nbsp; d(A) = d₀ × (A / A₀)<sup>−κ</sup></p>
    {!valid ? <p role="alert">Enter AUMs between $0.01bn and $1,000bn, η between 0 and 2, and κ between 0 and 1.</p> : <>
      <MigrationChart labels={MIGRATION_BUCKETS.map(b => b.label)} sets={sets}/>
      <p>Bucket share (%) = 100 × [F<sub>A</sub>(upper) − F<sub>A</sub>(lower)]. Shares measure traded value, not trade counts. The reference distribution stays fixed when η or κ changes because A / A₀ = 1.</p>
      <div className="table-scroll"><table><caption>Notional share by participation bucket; changes are percentage points versus the fitted reference.</caption><thead><tr><th>Participation bucket</th><th>Observed sample</th><th>Reference</th><th>Scenario 1</th><th>Change</th><th>Scenario 2</th><th>Change</th></tr></thead><tbody>{MIGRATION_BUCKETS.map((b,i) => <tr key={b.label}><td><strong>{b.label} ADV</strong></td><td>{i < DEFAULT_BUCKETS.length ? `${fmt(DEFAULT_BUCKETS[i].share,2)}%` : "Not supplied"}</td><td>{fmt(sets[0].values[i],2)}%</td>{[1,2].map(j => <Fragment key={j}><td>{fmt(sets[j].values[i],2)}%</td><td>{sets[j].values[i] - sets[0].values[i] > 0 ? "+" : ""}{fmt(sets[j].values[i] - sets[0].values[i],2)} pp</td></Fragment>)}</tr>)}</tbody><tfoot><tr><th>Total</th><td>100.00%</td><td>{fmt(sets[0].values.reduce((s,v)=>s+v,0),2)}%</td><td>{fmt(sets[1].values.reduce((s,v)=>s+v,0),2)}%</td><td>0.00 pp</td><td>{fmt(sets[2].values.reduce((s,v)=>s+v,0),2)}%</td><td>0.00 pp</td></tr></tfoot></table></div>
      <p>The observed column is the supplied live sample. The reference is a smooth fit, so bucket shares may differ. Changing A₀ reinterprets the AUM represented by that sample; it does not refit the distribution. The &gt;100% bucket retains the model’s projected tail.</p>
      <div className="demo-explanation">{aums.map((aum,i) => <p key={i}><strong>{["Reference", "Scenario 1", "Scenario 2"][i]}</strong><br/>A / A₀ = {fmt(aum / demo.aum0,2)} · λ = {fmt(demo.burrScale * Math.pow(aum / demo.aum0,demo.scaleElasticity),4)} · d = {fmt(demo.burrD * Math.pow(aum / demo.aum0,-demo.tailElasticity),3)} · cd = {fmt(tailIndices[i],2)}</p>)}</div>
      {tailIndices.some(v => v <= 1) && <p role="status">At least one scenario has cd ≤ 1: bucket probabilities remain defined, but the fitted distribution has no finite mean participation.</p>}
    </>}
  </article>;
}

export default function Home() {
  const [params, setParams] = useState(DEFAULTS);
  const [buckets, setBuckets] = useState(DEFAULT_BUCKETS);
  const [tab, setTab] = useState<"overview" | "migration" | "inputs" | "demo">("overview");
  const [advanced, setAdvanced] = useState(false);
  const [displayAums, setDisplayAums] = useState({ regulatory: "", competition: "" });
  const displayFields = [
    { key: "regulatory", label: "Regulatory capacity", color: "#476b87", dash: "8 4" },
    { key: "competition", label: "Median competition", color: "#855594", dash: "2 4" },
  ] as const;
  const markers: AumMarker[] = displayFields.flatMap(f => {
    const raw = displayAums[f.key];
    const value = Number(raw);
    return raw.trim() && Number.isFinite(value) && value > 0 ? [{ label: f.label, value, color: f.color, dash: f.dash }] : [];
  });
  const [demoTab, setDemoTab] = useState<"migration" | "impact" | "alpha">("migration");
  const set = (key: keyof Params, value: number) => setParams((s) => ({ ...s, [key]: value }));
  const engine = useMemo(() => makeEngine(params, buckets), [params, buckets]);
  const curve = useMemo(() => Array.from({ length: 61 }, (_, i) => engine.metric(Math.max(.1, params.maxAum * (i + 1) / 61))), [engine, params.maxAum]);
  const scenarios = useMemo(() => [params.aum0, params.aum0 * 2, params.aum0 * 4].map(engine.metric), [engine, params.aum0]);
  const current = scenarios[0];
  const crossing = (key: keyof Metric, threshold: number, below = true) => {
    const found = curve.find((d) => below ? Number(d[key]) <= threshold : Number(d[key]) >= threshold);
    return found?.aum;
  };
  const irCapacity = crossing("netIr", params.irThreshold);
  const retainedCapacity = crossing("retained", params.retainedThreshold);
  const migrationSets = scenarios.map((s, i) => ({ label: `$${fmt(s.aum,0)}bn`, values: engine.bucketShares(s.aum), color: COLORS[i] }));

  const exportCsv = () => {
    const columns: (keyof Metric)[] = ["aum","impact","annualDrag","alphaCapture","implementedAlpha","netAlpha","netIr","retained","avgDays","multiDay","threePlus","meanParticipation"];
    const csv = [columns.map(c => c === "aum" ? "aum_usd_bn" : c).join(","), ...curve.map((row) => columns.map((c) => row[c].toFixed(6)).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a"); a.href = url; a.download = "capacity-dashboard-scenarios.csv"; a.click(); URL.revokeObjectURL(url);
  };

  return <main>
    <header className="topbar">
      <div className="brand"><span className="brand-mark"><CircleGauge size={21}/></span><div><strong>Capacity Lab</strong><small>Long-only equity model · USD</small></div></div>
      <div className="top-actions"><span className="live"><i/>Model live</span><button className="ghost" onClick={() => { setParams(DEFAULTS); setBuckets(DEFAULT_BUCKETS); setDisplayAums({ regulatory: "", competition: "" }); }} title="Restore all default assumptions"><RefreshCcw size={16}/>Reset</button><button className="primary" onClick={exportCsv}><ArrowDownToLine size={16}/>Export CSV</button></div>
    </header>

    <div className="workspace">
      <aside className="sidebar">
        <div className="side-head"><div><span className="eyebrow">MODEL INPUTS</span><h2>Assumptions</h2></div><Settings2 size={18}/></div>
        <section className="input-section"><h3>Strategy</h3>
          <div className="field-grid"><Field label="Current AUM" value={params.aum0} onChange={(v)=>set("aum0",v)} suffix="$bn"/><Field label="Gross alpha" value={params.grossAlpha} onChange={(v)=>set("grossAlpha",v)} suffix="%"/><Field label="Tracking error" value={params.trackingError} onChange={(v)=>set("trackingError",v)} suffix="%"/><Field label="One-way turnover" value={params.turnover} onChange={(v)=>set("turnover",v)} suffix="%"/><Field label="Holdings" value={params.holdings} onChange={(v)=>set("holdings",v)} step={1}/><Field label="Chart horizon" value={params.maxAum} onChange={(v)=>set("maxAum",v)} suffix="$bn" step={5}/></div>
        </section>
        <section className="input-section"><h3>Migration & execution</h3>
          <div className="field-grid"><Field label="Scale elasticity" value={params.scaleElasticity} onChange={(v)=>set("scaleElasticity",v)} step={.05} hint="How quickly participation shifts as AUM rises; 1.0 is proportional."/><Field label="Tail thickening" value={params.tailElasticity} onChange={(v)=>set("tailElasticity",v)} step={.05} hint="Positive values increase the high-participation tail at larger AUM."/><Field label="Daily participation" value={params.dailyParticipation} onChange={(v)=>set("dailyParticipation",v)} suffix="% ADV"/><Field label="Maximum horizon" value={params.maxDays} onChange={(v)=>set("maxDays",v)} suffix="days" step={1}/><Field label="Alpha half-life" value={params.halfLife} onChange={(v)=>set("halfLife",v)} suffix="days"/></div>
        </section>
        <section className="input-section"><h3>Decision thresholds</h3>
          <div className="field-grid"><Field label="Minimum net IR" value={params.irThreshold} onChange={(v)=>set("irThreshold",v)} step={.05}/><Field label="Minimum retained alpha" value={params.retainedThreshold} onChange={(v)=>set("retainedThreshold",v)} suffix="%"/></div>
        </section>
        <section className="input-section display-markers"><h3>Display markers</h3>
          <div className="field-grid">{displayFields.map(f => <label className="field" key={f.key}><span>{f.label}</span><span className="input-wrap"><input type="number" min="0.01" step="0.5" placeholder="Not set" value={displayAums[f.key]} onChange={e => setDisplayAums(s => ({ ...s, [f.key]: e.target.value }))}/><em>$bn</em></span></label>)}</div>
          <p>Enter USD billions to show vertical lines on the Overview charts. Display only; clear a value to hide its line.</p>
          {displayFields.some(f => displayAums[f.key].trim() && (!Number.isFinite(Number(displayAums[f.key])) || Number(displayAums[f.key]) <= 0)) && <p role="alert">Marker AUMs must be positive numbers.</p>}
        </section>
        <button className="advanced-toggle" onClick={()=>setAdvanced(!advanced)}><span>Advanced calibration</span><ChevronDown size={16} className={advanced ? "rotated" : ""}/></button>
        {advanced && <section className="advanced-panel"><p>Burr XII distribution</p><div className="field-grid"><Field label="Shape c" value={params.burrC} onChange={(v)=>set("burrC",v)} step={.01}/><Field label="Shape d" value={params.burrD} onChange={(v)=>set("burrD",v)} step={.01}/><Field label="Scale" value={params.burrScale} onChange={(v)=>set("burrScale",v)} step={.005}/></div><p>Impact curve: a + b·p<sup>γ</sup></p><div className="field-grid"><Field label="a" value={params.impactA} onChange={(v)=>set("impactA",v)}/><Field label="b" value={params.impactB} onChange={(v)=>set("impactB",v)}/><Field label="Gamma" value={params.impactGamma} onChange={(v)=>set("impactGamma",v)} step={.05}/></div></section>}
        <div className="model-note"><Info size={15}/><p>Shares represent executed notional. Current observed bucket costs anchor the impact level.</p></div>
      </aside>

      <section className="content">
        <div className="hero"><div><span className="eyebrow">PORTFOLIO CAPACITY</span><h1>Analysis strategy's AUM scenarios</h1><p>Explore how liquidity migration, execution horizons and alpha decay reshape the portfolio as it scales.</p></div><div className="asof"><span>BASE CASE · USD</span><strong>${fmt(params.aum0,1)}bn</strong></div></div>
        <nav className="tabs">{([['overview','Overview'],['migration','Liquidity migration'],['inputs','Input data'],['demo','Demo key building blocks']] as const).map(([id,label])=><button key={id} className={tab===id?'active':''} onClick={()=>setTab(id)}>{label}</button>)}</nav>

        {tab === "overview" && <>
          <div className="kpis">
            <article><span className="kpi-icon green"><Activity size={18}/></span><div><small>Current net IR</small><strong>{fmt(current.netIr,2)}</strong><em className={current.netIr >= params.irThreshold ? "good" : "warn"}>{current.netIr >= params.irThreshold ? "Above" : "Below"} threshold</em></div></article>
            <article><span className="kpi-icon amber"><WalletCards size={18}/></span><div><small>IR capacity</small><strong>{irCapacity ? `$${fmt(irCapacity,1)}bn` : `> $${fmt(params.maxAum,0)}bn`}</strong><em>Net IR = {fmt(params.irThreshold,2)}</em></div></article>
            <article><span className="kpi-icon rust"><TrendingDown size={18}/></span><div><small>Alpha capture at 2×</small><strong>{fmt(scenarios[1].alphaCapture,1)}%</strong><em>{fmt(100-scenarios[1].alphaCapture,1)}% delay loss</em></div></article>
            <article><span className="kpi-icon blue"><Clock3 size={18}/></span><div><small>Avg execution at 2×</small><strong>{fmt(scenarios[1].avgDays,1)} days</strong><em>{fmt(scenarios[1].threePlus,1)}% requires 3+ days</em></div></article>
          </div>
          <div className="overview-charts">
            <article className="card chart-card"><div className="card-head"><div><h2>Net information ratio</h2><p>After execution delay and market impact</p></div><span className="badge">Threshold {fmt(params.irThreshold,2)}</span></div><LineChart data={curve} yLabel="Net IR" height={320} markers={markers} autoScale threshold={params.irThreshold} series={[{key:"netIr",label:"Net IR",color:COLORS[1]}]}/></article>
            <article className="card chart-card"><div className="card-head"><div><h2>Alpha decomposition</h2><p>Annualised relative return through capacity</p></div></div><LineChart data={curve} yLabel="Alpha (%)" height={320} markers={markers} autoScale series={[{key:"implementedAlpha",label:"After delay",color:COLORS[2]},{key:"netAlpha",label:"After impact",color:COLORS[3]}]}/></article>
          </div>
          <article className="card table-card"><div className="card-head"><div><h2>Scenario results</h2><p>Base AUM and two scaling checkpoints</p></div><span className="badge subtle">Notional-weighted</span></div><div className="table-scroll"><table><thead><tr><th>AUM (USD)</th><th>Impact</th><th>Annual drag</th><th>Alpha capture</th><th>Net alpha</th><th>Net IR</th><th>Retained</th><th>Avg days</th><th>3+ days</th></tr></thead><tbody>{scenarios.map((s)=><tr key={s.aum}><td><strong>${fmt(s.aum,1)}bn</strong></td><td>{fmt(s.impact,1)} bp</td><td>{fmt(s.annualDrag,1)} bp</td><td>{fmt(s.alphaCapture,1)}%</td><td>{fmt(s.netAlpha,2)}%</td><td><span className={s.netIr >= params.irThreshold ? "pill good-bg" : "pill warn-bg"}>{fmt(s.netIr,2)}</span></td><td>{fmt(s.retained,1)}%</td><td>{fmt(s.avgDays,1)}</td><td>{fmt(s.threePlus,1)}%</td></tr>)}</tbody></table></div></article>
          <div className="decision-strip"><BarChart3 size={20}/><div><span>Capacity readout</span><strong>{retainedCapacity ? `Retained alpha falls through ${fmt(params.retainedThreshold,0)}% near $${fmt(retainedCapacity,1)}bn.` : `Retained alpha stays above ${fmt(params.retainedThreshold,0)}% through $${fmt(params.maxAum,0)}bn.`}</strong></div></div>
        </>}

        {tab === "migration" && <>
          <div className="grid-two migration-grid"><article className="card"><div className="card-head"><div><h2>Migration across ADV buckets</h2><p>Burr XII distribution shifts with AUM</p></div></div><MigrationChart labels={MIGRATION_BUCKETS.map(b=>b.label)} sets={migrationSets}/></article><article className="card chart-card"><div className="card-head"><div><h2>Execution horizon</h2><p>More notional moves into multi-day schedules</p></div></div><LineChart data={curve} yLabel="Days / share (%)" series={[{key:"avgDays",label:"Average days",color:COLORS[1]},{key:"threePlus",label:"3+ day share (%)",color:COLORS[2]}]}/></article></div>
          <article className="card table-card"><div className="card-head"><div><h2>Bucket migration table</h2><p>Share of annual traded notional; &gt;100% is a modeled tail, absent from the source.</p></div></div><div className="table-scroll"><table><thead><tr><th>Participation bucket</th>{scenarios.map(s=><th key={s.aum}>${fmt(s.aum,0)}bn</th>)}</tr></thead><tbody>{MIGRATION_BUCKETS.map((b,i)=><tr key={b.label}><td><strong>{b.label} ADV</strong></td>{migrationSets.map(s=><td key={s.label}>{fmt(s.values[i],1)}%</td>)}</tr>)}</tbody></table></div></article>
        </>}

        {tab === "demo" && <>
          <nav className="demo-subtabs" aria-label="Demo building blocks">
            <button aria-pressed={demoTab === "migration"} onClick={() => setDemoTab("migration")}>1. Liquidity migration</button>
            <button aria-pressed={demoTab === "impact"} onClick={() => setDemoTab("impact")}>2. Impact model</button>
            <button aria-pressed={demoTab === "alpha"} onClick={() => setDemoTab("alpha")}>3. Alpha decay</button>
          </nav>
          <div hidden={demoTab !== "migration"}><MigrationDemo params={params}/></div>
          <div hidden={demoTab !== "impact"}><ImpactDemo params={params}/></div>
          <div hidden={demoTab !== "alpha"}><AlphaDecayDemo aum0={params.aum0} halfLife={params.halfLife} grossAlpha={params.grossAlpha} scenario={(aum, halfLife) => makeEngine({ ...params, halfLife }, buckets).metric(aum)}/></div>
        </>}

        {tab === "inputs" && <article className="card table-card"><div className="card-head"><div><h2>Liquidity calibration inputs</h2><p>Edit notional shares and expected impact; changes flow through the dashboard immediately.</p></div><span className="badge">Share total {fmt(buckets.reduce((s,b)=>s+b.share,0),1)}%</span></div><div className="table-scroll"><table className="edit-table"><thead><tr><th>ADV bucket</th><th>Trades</th><th>Value (USD m)</th><th>Representative participation</th><th>Notional share</th><th>Expected impact</th><th>Realised impact</th></tr></thead><tbody>{buckets.map((b,i)=><tr key={b.label}><td><strong>{b.label}</strong></td><td>{fmt(b.trades,0)}</td><td>{fmt(b.valueUsdMillion,3)}</td><td>{fmt(b.p*100,2)}%</td><td><span className="inline-input"><input type="number" value={b.share} step="0.01" onChange={e=>setBuckets(bs=>bs.map((x,j)=>j===i?{...x,share:Number(e.target.value)}:x))}/><em>%</em></span></td><td><span className="inline-input"><input type="number" value={b.cost} step="0.01" onChange={e=>setBuckets(bs=>bs.map((x,j)=>j===i?{...x,cost:Number(e.target.value)}:x))}/><em>bp</em></span></td><td>{fmt(b.realised,2)} bp</td></tr>)}</tbody></table></div><div className="input-foot"><Info size={16}/><p>Source: buckets_data_live.csv. 971 trades totaling $944.475m. Reported value weights are retained; negative source impacts are shown as positive costs. Bucket midpoints proxy participation, using median daily volume as the ADV proxy. Curves are refitted to these six buckets; the Burr scale reaches its fitting bound. Editing shares or costs adjusts the base impact level; migration shape remains controlled by the Burr parameters.</p></div></article>}
      </section>
    </div>
    <footer><span>Capacity Lab</span><p>Illustrative decision-support model—not investment advice.</p></footer>
  </main>;
}
