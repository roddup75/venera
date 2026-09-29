"use client";
import { useMemo, useState, type ComponentType } from "react";
import { calibrateOrders, createAdvEngine, type AdvScenario } from "./adv-migration";
import AdvCalibrationPanel from "./adv-calibration-panel";
import live from "./bucket-data.json";
import universe from "./universe-adv-data.json";

type ChartProps = { labels: string[]; sets: { label: string; values: number[]; color: string }[] };
const fmt=(v:number,d=2)=>v.toLocaleString("en-GB",{minimumFractionDigits:d,maximumFractionDigits:d});
export default function AdvMigrationDemo({params,Chart}:{params:Omit<AdvScenario,"advVolume"> & {aum0:number};Chart:ComponentType<ChartProps>}) {
 const initial=()=>({first:String(params.aum0),second:String(params.aum0*2),holdings:String(params.holdings),turnover:String(params.turnover),volume:"100",daily:String(params.dailyParticipation),horizon:String(params.maxDays),halfLife:String(params.halfLife)});
 const [inputs,setInputs]=useState(initial),[preference,setPreference]=useState(0);
 const fields=[
  {key:"first",label:"AUM 1 ($bn)",min:.01,max:1000,step:.1},
  {key:"second",label:"AUM 2 ($bn)",min:.01,max:1000,step:.1},
  {key:"holdings",label:"Average holdings",min:1,max:203,step:1},
  {key:"turnover",label:"Annual one-way turnover (%)",min:0,max:1000,step:.1},
  {key:"volume",label:"Market ADV level (%)",min:1,max:300,step:5},
  {key:"daily",label:"Daily participation (% ADV)",min:.1,max:100,step:.5},
  {key:"horizon",label:"Maximum execution days",min:1,max:252,step:1},
  {key:"halfLife",label:"Alpha half-life (days)",min:.1,max:1260,step:1},
 ] as const;
 const valid=fields.every(f=>inputs[f.key].trim()!=="" && Number.isFinite(Number(inputs[f.key])) && Number(inputs[f.key])>=f.min && Number(inputs[f.key])<=f.max);
 const calibration=useMemo(()=>{try{return {orders:calibrateOrders(live.buckets,universe.quantiles,preference),error:""};}catch(e){return {orders:[],error:String(e)};}},[preference]);
 const engine=useMemo(()=>valid && !calibration.error ? createAdvEngine({...params,holdings:Number(inputs.holdings),turnover:Number(inputs.turnover),advVolume:Number(inputs.volume),dailyParticipation:Number(inputs.daily),maxDays:Number(inputs.horizon),halfLife:Number(inputs.halfLife)},live.buckets,calibration.orders):null,[params,inputs,valid,calibration]);
 const aums=[Number(inputs.first),Number(inputs.second)], labels=[...live.buckets.map(b=>b.label),">100%"];
 const sets=(count:boolean)=>aums.map((a,i)=>({label:`AUM ${i+1} · $${fmt(a)}bn`,color:["#1d6f61","#bc5a3c"][i],values:engine?(count?engine.countShares(a):engine.bucketShares(a)):[]}));
 return <>
 <article className="card table-card demo-block">
  <div className="card-head"><div><h2>1. ADV-calibrated liquidity migration</h2><p>Explore order size, trading frequency and available liquidity together.</p></div><button className="ghost" onClick={()=>{setInputs(initial());setPreference(0);}}>Reset ADV demo</button></div>
  <p>Demo controls are independent of the main case. Reset copies the current strategy and execution assumptions. Historical calibration remains fixed at $3.4bn, 40 holdings, 971 parent orders and $944.475m annual trading.</p>
  <div className="demo-controls">{fields.map(f=><label className="field" key={f.key}><span>{f.label}</span><span className="input-wrap"><input type="number" min={f.min} max={f.max} step={f.step} value={inputs[f.key]} onChange={e=>setInputs(s=>({...s,[f.key]:e.target.value}))}/></span></label>)}<label className="field"><span>Liquidity preference</span><select value={preference} onChange={e=>setPreference(Number(e.target.value))}><option value={0}>Neutral prior</option><option value={2}>Favour liquid stocks</option><option value={-2}>Favour illiquid stocks</option></select></label></div>
  <div className="demo-explanation"><p><strong>AUM, holdings, ADV and preference</strong><br/>These controls change the participation-bucket graphs.</p><p><strong>Daily participation and maximum days</strong><br/>These controls change the execution-outcome graph below.</p><p><strong>Turnover and half-life</strong><br/>Turnover changes annual order totals; half-life changes captured alpha and net IR.</p></div>
  <p className="demo-formula">Q = Q₀ × (A / $3.4bn) × (40 / H) &nbsp; · &nbsp; N = 971 × (H / 40) × (T / T₀)<br/>p = Q / (ADV × volume factor) &nbsp; · &nbsp; T₀ = $944.475m / (2 × $3.4bn)</p>
  {!valid && <p role="alert">Enter values within the displayed input limits; clear or invalid inputs pause the demo.</p>}
  {calibration.error && <p role="alert">Calibration cannot reconcile the supplied inputs: {calibration.error}</p>}
  {engine && <><h3>Traded-dollar migration (%)</h3><Chart labels={labels} sets={sets(false)}/><h3>Parent-order count migration (%)</h3><Chart labels={labels} sets={sets(true)}/>
   <h3>Execution outcomes by parent-order count (%)</h3><Chart labels={["Completed in 1 day","Completed in 2–5 days","Completed in 6+ days","Beyond maximum horizon"]} sets={aums.map((a,i)=>({label:`AUM ${i+1} · $${fmt(a)}bn`,color:["#1d6f61","#bc5a3c"][i],values:engine.executionShares(a)}))}/>
   <p className="model-explanation">Daily participation changes the number of days required to complete an order. Maximum execution days determines which orders fall beyond the permitted horizon. Parent-order participation buckets remain based on total order value divided by ADV.</p>
   <div className="table-scroll"><table><caption>Two views of the same parent orders. Zero turnover implies no annual orders or traded dollars.</caption><thead><tr><th>Participation bucket</th><th>AUM 1 · dollars %</th><th>AUM 2 · dollars %</th><th>AUM 1 · orders %</th><th>AUM 2 · orders %</th></tr></thead><tbody>{labels.map((label,i)=><tr key={label}><td>{label}</td>{[...sets(false),...sets(true)].map((s,j)=><td key={j}>{fmt(s.values[i])}%</td>)}</tr>)}</tbody></table></div>
   <div className="table-scroll"><table><caption>Alpha capture is relative to the historical portfolio under the selected execution policy.</caption><thead><tr><th>AUM</th><th>Alpha capture</th><th>After delay (%)</th><th>Net IR</th></tr></thead><tbody>{aums.map((a,i)=>{const m=engine.metric(a);return <tr key={i}><td>${fmt(a)}bn</td><td>{fmt(m.alphaCapture)}%</td><td>{fmt(m.implementedAlpha,3)}</td><td>{fmt(m.netIr,3)}</td></tr>})}</tbody></table></div>
  </>}
 </article>
 {engine && <AdvCalibrationPanel orders={calibration.orders} buckets={live.buckets} engine={engine} aums={aums}/>}
 </>;
}
