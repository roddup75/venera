"use client";

import { useState } from "react";

type ImpactParameters = { impactA: number; impactB: number; impactGamma: number };
export const impactAtPercent = (participation: number, a: number, b: number, gamma: number) => a + b * Math.pow(participation / 100, gamma);
const format = (value: number) => value.toLocaleString("en-GB", { maximumFractionDigits: 2 });

export default function ImpactDemo({ params }: { params: ImpactParameters }) {
  const initial = () => ({ a: String(params.impactA), b: String(params.impactB), gamma: String(params.impactGamma), participation: "10", max: "100" });
  const [inputs, setInputs] = useState(initial);
  const fields = [
    { key: "a", label: "a · Base cost (bp)", min: 0, max: 1000, step: 0.1 },
    { key: "b", label: "b · Impact coefficient (bp)", min: 0, max: 1000, step: 1 },
    { key: "gamma", label: "γ · Impact exponent", min: 0.01, max: 3, step: 0.05 },
    { key: "participation", label: "Participation (% ADV)", min: 0, max: 500, step: 1 },
    { key: "max", label: "Chart maximum (% ADV)", min: 1, max: 500, step: 10 },
  ] as const;
  const valid = fields.every(f => inputs[f.key].trim() !== "" && Number.isFinite(Number(inputs[f.key])) && Number(inputs[f.key]) >= f.min && Number(inputs[f.key]) <= f.max);
  const a = Number(inputs.a), b = Number(inputs.b), gamma = Number(inputs.gamma);
  const selected = Number(inputs.participation), max = Number(inputs.max);
  const cost = (p: number) => impactAtPercent(p, a, b, gamma);
  const reference = (p: number) => impactAtPercent(p, params.impactA, params.impactB, params.impactGamma);
  const ceiling = Math.max(max, selected);
  const high = Math.max(cost(ceiling), reference(ceiling), 0.01) * 1.1;
  const x = (p: number) => 72 + p / ceiling * 670;
  const y = (value: number) => 24 + (1 - value / high) * 240;
  const path = (fn: (p: number) => number) => Array.from({ length: 301 }, (_, i) => {
    const p = ceiling * i / 300;
    return `${i ? "L" : "M"}${x(p)},${y(fn(p))}`;
  }).join(" ");
  const rates = [...new Set([0, 1, 5, 10, 25, 50, 100, selected, ceiling].filter(p => p <= ceiling))].sort((l,r) => l-r);
  return <article className="card table-card demo-block">
    <div className="card-head"><div><h2>2. Impact model</h2><p>Explore the cost of trading at different participation rates.</p></div><button className="ghost" onClick={() => setInputs(initial())}>Reset impact demo</button></div>
    <p>Adjust the demo curve and compare it with the dashboard’s current fitted curve. These controls do not change the main capacity case.</p>
    <div className="demo-controls">{fields.map(f => <label className="field" key={f.key}><span>{f.label}</span><span className="input-wrap"><input type="number" min={f.min} max={f.max} step={f.step} value={inputs[f.key]} onChange={e => setInputs(s => ({ ...s, [f.key]: e.target.value }))}/></span></label>)}</div>
    <p className="demo-formula">c(p) = a + b × p<sup>γ</sup> &nbsp; where p = participation (% ADV) / 100</p>
    <div className="demo-explanation"><p><strong>a · Base cost</strong><br/>Shifts the whole curve up or down. At zero participation, modeled cost equals a.</p><p><strong>b · Impact coefficient</strong><br/>Scales the variable cost. At 100% ADV, modeled cost equals a + b.</p><p><strong>γ · Shape</strong><br/>γ = 0.5 gives a square-root curve; γ = 1 is linear. Raising γ reduces variable cost below 100% ADV and increases it above 100% ADV.</p></div>
    {!valid ? <p role="alert">Use a and b between 0 and 1,000 bp, γ between 0.01 and 3, participation between 0 and 500%, and a chart maximum between 1 and 500%.</p> : <>
      <p className="demo-formula" aria-live="polite">At <strong>{format(selected)}% ADV</strong>: {format(a)} + {format(b)} × ({format(selected)} / 100)<sup>{gamma.toFixed(4)}</sup> ≈ <strong>{format(cost(selected))} bp</strong>. Reference: {format(reference(selected))} bp.</p>
      <div className="legend"><span><i style={{background:"#1d6f61"}}/>Demo curve</span><span><i style={{background:"#bc5a3c"}}/>Reference curve (dashed)</span></div>
      <div className="impact-plot"><svg viewBox="0 0 770 320" role="img" aria-label="Impact cost in basis points by participation percentage of ADV, showing demo and reference curves">
        <text x="72" y="16" className="impact-axis">Impact (bp per executed notional)</text>
        {[0,.25,.5,.75,1].map(f => <g key={f}><line x1="72" x2="742" y1={y(f*high)} y2={y(f*high)} className="grid"/><text x="62" y={y(f*high)+4} textAnchor="end" className="impact-axis">{format(f*high)}</text><text x={x(f*ceiling)} y="285" textAnchor="middle" className="impact-axis">{format(f*ceiling)}%</text></g>)}
        <path d={path(reference)} fill="none" stroke="#bc5a3c" strokeWidth="3" strokeDasharray="6 5"/>
        <path d={path(cost)} fill="none" stroke="#1d6f61" strokeWidth="3"/>
        <line x1={x(selected)} x2={x(selected)} y1="24" y2="264" className="threshold"/>
        <circle cx={x(selected)} cy={y(cost(selected))} r="5" fill="#1d6f61"><title>{format(selected)}% ADV: {format(cost(selected))} bp</title></circle>
        <text x="407" y="312" textAnchor="middle" className="impact-axis">Participation (% ADV)</text>
      </svg></div>
      {selected > max && <p>The chart extends to the selected participation rate so the inspected point stays visible.</p>}
      <div className="table-scroll"><table><caption>Raw impact curve comparison across participation rates</caption><thead><tr><th>Participation (% ADV)</th><th>Reference cost (bp)</th><th>Demo cost (bp)</th><th>Difference (bp)</th></tr></thead><tbody>{rates.map(p => <tr key={p} className={p===selected ? "impact-selected" : undefined}><td>{format(p)}%{p===selected ? " · selected" : ""}</td><td>{format(reference(p))}</td><td>{format(cost(p))}</td><td>{cost(p)-reference(p)>0 ? "+" : ""}{format(cost(p)-reference(p))}</td></tr>)}</tbody></table></div>
      <p>Costs are basis points per executed notional, before the portfolio’s baseline calibration multiplier, execution-horizon adjustment, and annual turnover conversion. Reference parameters: a = {format(params.impactA)}, b = {format(params.impactB)}, γ = {params.impactGamma.toFixed(4)}.</p>
    </>}
  </article>;
}
