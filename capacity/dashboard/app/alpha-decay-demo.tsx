"use client";

import { useState } from "react";

type Scenario = { implementedAlpha: number; avgDays: number };
type Props = {
  aum0: number;
  halfLife: number;
  grossAlpha: number;
  scenario: (aum: number, halfLife: number) => Scenario;
};
const HORIZON = 126;
const format = (value: number, digits = 3) => value.toLocaleString("en-US", { maximumFractionDigits: digits });

export default function AlphaDecayDemo({ aum0, halfLife, grossAlpha, scenario }: Props) {
  const initial = () => ({ first: String(aum0), second: String(aum0 * 2), halfLife: String(halfLife) });
  const [inputs, setInputs] = useState(initial);
  const fields = [
    { key: "first", label: "AUM 1 (USD bn)", min: 0.01, max: 1000, step: 0.5 },
    { key: "second", label: "AUM 2 (USD bn)", min: 0.01, max: 1000, step: 0.5 },
    { key: "halfLife", label: "Half-life Hα (trading days)", min: 0.1, max: 1260, step: 1 },
  ] as const;
  const valid = fields.every(f => inputs[f.key].trim() !== "" && Number.isFinite(Number(inputs[f.key])) && Number(inputs[f.key]) >= f.min && Number(inputs[f.key]) <= f.max);
  const h = Number(inputs.halfLife);
  const sets = valid ? [Number(inputs.first), Number(inputs.second)].map((aum, i) => ({
    label: `AUM ${i+1} · $${format(aum,2)}bn`,
    color: ["#1d6f61", "#bc5a3c"][i],
    ...scenario(aum, h),
  })) : [];
  const usable = valid && sets.every(s => Number.isFinite(s.implementedAlpha) && Number.isFinite(s.avgDays));
  const rg = (start: number, day: number) => start * Math.pow(2, -day / h);
  const values = sets.map(s => s.implementedAlpha);
  const lo = Math.min(0, ...values), hi = Math.max(0, ...values);
  const padding = Math.max((hi-lo)*0.06, 0.0001);
  const minY = lo < 0 ? lo-padding : 0, maxY = hi+padding;
  const x = (day: number) => 80 + day / HORIZON * 656;
  const y = (value: number) => 28 + (maxY-value)/(maxY-minY)*236;
  const path = (start: number) => Array.from({length:HORIZON+1}, (_,day) => `${day ? "L" : "M"}${x(day)},${y(rg(start,day))}`).join(" ");
  const checkpoints = [...new Set([0, 5, 10, 21, 42, 63, 84, 105, 126, ...(h <= HORIZON ? [h] : [])])].sort((a,b)=>a-b);
  return <article className="card table-card demo-block">
    <div className="card-head"><div><h2>3. Alpha decay</h2><p>Compare remaining gross alpha at two AUMs over six months.</p></div><button className="ghost" onClick={() => setInputs(initial())}>Reset alpha demo</button></div>
    <div className="demo-controls">{fields.map(f => <label className="field" key={f.key}><span>{f.label}</span><span className="input-wrap"><input type="number" min={f.min} max={f.max} step={f.step} value={inputs[f.key]} onChange={e=>setInputs(s=>({...s,[f.key]:e.target.value}))}/></span></label>)}</div>
    <p>Each curve starts with gross alpha after the model’s AUM-dependent execution delay. The horizontal axis adds a common waiting period before execution: 0–126 trading days, approximately six months at 21 trading days per month. These demo controls do not change the main capacity case.</p>
    <p className="demo-formula">R<sub>g</sub>(A, t) = R<sub>g</sub>(A, 0) × 2<sup>−t / Hα</sup></p>
    <p>Hα is the signal half-life: every Hα trading days of additional waiting halves the remaining alpha. It is separate from γ, the impact-curve exponent. R<sub>g</sub> is annualised gross alpha remaining, not cumulative return or net alpha after costs.</p>
    {!valid ? <p role="alert">Enter both AUMs between $0.01bn and $1,000bn, and a positive half-life between 0.1 and 1,260 trading days.</p> : !usable ? <p role="alert">The current model assumptions do not produce finite alpha estimates. Check the main dashboard’s distribution and execution parameters.</p> : <>
      <div className="legend">{sets.map((s,i)=><span key={i}><i style={{background:s.color}}/>{s.label}{i===1 ? " (dashed)" : ""}</span>)}</div>
      <div className="impact-plot"><svg viewBox="0 0 770 326" role="img" aria-label="Remaining annualised gross alpha Rg in percent by additional waiting days, from zero to 126 trading days, at two AUMs">
        <text x="80" y="17" className="impact-axis">Rg (% p.a.)</text>
        {[0,.25,.5,.75,1].map(f=><g key={f}><line x1="80" x2="736" y1={y(minY+f*(maxY-minY))} y2={y(minY+f*(maxY-minY))} className="grid"/><text x="69" y={y(minY+f*(maxY-minY))+4} textAnchor="end" className="impact-axis">{format(minY+f*(maxY-minY),4)}%</text></g>)}
        {[0,21,42,63,84,105,126].map(day=><text key={day} x={x(day)} y="286" textAnchor="middle" className="impact-axis">{day}</text>)}
        {h<=HORIZON && <line x1={x(h)} x2={x(h)} y1="28" y2="264" className="threshold"><title>One half-life: {format(h)} trading days</title></line>}
        {sets.map((s,i)=><path key={i} d={path(s.implementedAlpha)} fill="none" stroke={s.color} strokeWidth="3" strokeDasharray={i===1 ? "7 5" : undefined}/>)}
        <text x="408" y="315" textAnchor="middle" className="impact-axis">Additional waiting time (trading days)</text>
      </svg></div>
      <div className="demo-explanation">{sets.map((s,i)=><p key={i}><strong>{s.label}</strong><br/>Day 0 Rg: {format(s.implementedAlpha,4)}% p.a.<br/>Average modeled execution: {format(s.avgDays,2)} days.<br/>At one half-life: {format(s.implementedAlpha/2,4)}% p.a.</p>)}</div>
      <div className="table-scroll"><table><caption>Gross alpha remaining (% p.a.) after additional waiting</caption><thead><tr><th>Trading days</th>{sets.map((s,i)=><th key={i}>{s.label}</th>)}<th>Share of day-0 alpha</th></tr></thead><tbody>{checkpoints.map(day=><tr key={day}><td>{format(day)}{day===h ? " · half-life" : ""}</td>{sets.map((s,i)=><td key={i}>{format(rg(s.implementedAlpha,day),4)}%</td>)}<td>{format(Math.pow(2,-day/h)*100,2)}%</td></tr>)}</tbody></table></div>
      <p>The reference gross alpha is {format(grossAlpha)}% p.a. at ${format(aum0,2)}bn. Day-0 Rg uses the same notional-weighted execution-capture calculation as the main model, normalised to that reference AUM. The extra waiting factor is a demo extension; equal AUMs produce overlapping curves, and AUMs with similar execution schedules may differ only slightly.</p>
    </>}
  </article>;
}
