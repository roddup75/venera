"""Streamlit Capacity Lab: Monte Carlo execution-delay methodology."""
from __future__ import annotations
import io
import json
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from capacity_model import Scenario, MIN_AUM, validate_trades
from empirical_model import EmpiricalIRModel
from universe_sampler import create_liquidity_engine, ADV_POINTS
from bucket_sampler import bucket_migration
from impact_cost import fit_impact_cost, impact_bps, impact_curve
from transfer_coefficient import TransferCoefficientModel
from alpha_decay import AlphaDecayModel
from strategy_store import (BUCKET_COLUMNS, DEFAULT_PARAMETERS, IR_COLUMNS,
                            default_strategy, load_strategies, save_strategy)

GREEN, AMBER, RUST, BLUE = "#42c7a5", "#f4bd50", "#ef7658", "#76a9d0"
PALETTE = [GREEN, AMBER, RUST, BLUE, "#c698db"]
PAGE_BG, PANEL_BG, TEXT, GRID = "#050505", "#111111", "#f2f4f3", "#303432"
st.set_page_config(page_title="Capacity Lab", page_icon="◉", layout="wide")
st.markdown("""
<style>
  .stApp, [data-testid="stAppViewContainer"] { background: #050505; color: #f2f4f3; }
  [data-testid="stHeader"] { background: rgba(5, 5, 5, 0.88); }
  [data-testid="stMetric"] {
    background: #111111;
    border: 1px solid #303432;
    border-radius: 12px;
    padding: 14px;
  }
  [data-testid="stMetricLabel"], [data-testid="stMetricValue"],
  [data-testid="stMetricDelta"], h1, h2, h3, p, label { color: #f2f4f3; }
  div[data-testid="stSidebar"] { background: #0c0d0d; border-right: 1px solid #262927; }
  div[data-testid="stTabs"] button { color: #c8cfcc; }
  div[data-testid="stTabs"] button[aria-selected="true"] { color: #42c7a5; }
  [data-testid="stDataFrame"] { border: 1px solid #303432; border-radius: 8px; }
  div[data-testid="stAlert"] { background: #111b18; color: #f2f4f3; }
</style>
""", unsafe_allow_html=True)


def display_table(frame, **kwargs):
    """Format display values only; preserve model and export precision."""
    view=frame.copy()
    ratio_columns={"p":"Representative order/ADV (%)","lower":"Lower order/ADV (%)",
                   "upper":"Upper order/ADV (%)","Baseline order/ADV":"Baseline order/ADV (%)",
                   "Order/ADV at selected AUM":"Order/ADV at selected AUM (%)",
                   "Sampled notional weight":"Sampled notional weight (%)"}
    for column,label in ratio_columns.items():
        if column in view:
            view[column]=100*view[column]
            view=view.rename(columns={column:label})
    formats={column:st.column_config.NumberColumn(format="%d" if pd.api.types.is_integer_dtype(view[column]) else "%.2f")
             for column in view if pd.api.types.is_numeric_dtype(view[column]) and not pd.api.types.is_bool_dtype(view[column])}
    return st.dataframe(view,column_config=formats,**kwargs)


def style_figure(fig: go.Figure) -> go.Figure:
    """Apply a high-contrast dark theme consistently to every Plotly chart."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=PAGE_BG,
        plot_bgcolor=PANEL_BG,
        font_color=TEXT,
        title_font_color=TEXT,
        legend_bgcolor="rgba(17,17,17,0.85)",
        legend=dict(orientation="h", y=1.12, x=0),
        hoverlabel=dict(bgcolor="#1a1d1b", font_color=TEXT),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor="#555b58")
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor="#555b58")
    return fig


def add_aum_markers(fig: go.Figure, markers: list[dict[str, float | str]], max_aum: float) -> go.Figure:
    """Add optional external AUM reference lines without changing the chart range."""
    positions = ["top right", "top right"]
    for index, marker in enumerate(markers):
        value = float(marker["value"])
        if MIN_AUM <= value <= max_aum:
            fig.add_vline(
                x=value,
                line_width=2,
                line_dash=str(marker["dash"]),
                line_color=str(marker["color"]),
                annotation_text=f"{'Reg.' if marker['label'] == 'Implied regulatory AUM' else 'Peers'} ${value:g}bn",
                annotation_yshift=-20 * index,
                annotation_position=positions[index % len(positions)],
                annotation_font_color=str(marker["color"]),
                annotation_bgcolor="rgba(5,5,5,0.82)",
                annotation_borderpad=4,
            )
    return fig


def fit_ir_curve(points: pd.DataFrame) -> dict[str, float | np.ndarray]:
    """Fit IR(A) = a - b A^gamma without requiring an optimisation dependency."""
    frame = points[IR_COLUMNS].copy()
    frame[IR_COLUMNS] = frame[IR_COLUMNS].apply(pd.to_numeric, errors="raise")
    values = frame.to_numpy(float)
    if len(frame) < 3 or not np.isfinite(values).all():
        raise ValueError("Enter at least three finite AUM and IR observations.")
    if (frame["aumBn"] < 0).any() or frame["aumBn"].duplicated().any():
        raise ValueError("AUM values must be non-negative and unique.")
    x = frame["aumBn"].to_numpy(float)
    y = frame["ir"].to_numpy(float)
    best: tuple[float, float, float, np.ndarray, float] | None = None
    for gamma in np.linspace(0.20, 3.00, 1401):
        transformed = x ** gamma
        variance = float(np.dot(transformed - transformed.mean(), transformed - transformed.mean()))
        if variance <= 1e-16:
            continue
        slope = float(np.dot(transformed - transformed.mean(), y - y.mean()) / variance)
        b = -slope
        if b < 0:
            continue
        a = float(y.mean() + b * transformed.mean())
        fitted = a - b * transformed
        sse = float(np.dot(y - fitted, y - fitted))
        if best is None or sse < best[4]:
            best = (a, b, float(gamma), fitted, sse)
    if best is None:
        raise ValueError("The IR observations do not support a decreasing fitted curve.")
    a, b, gamma, fitted, sse = best
    total = float(np.dot(y - y.mean(), y - y.mean()))
    r_squared = 1.0 - sse / total if total > 1e-16 else 1.0
    return {
        "a": a, "b": b, "gamma": gamma, "fitted": fitted,
        "r_squared": r_squared, "x": x, "y": y,
    }


try:
    strategies = load_strategies()
except (OSError, KeyError, TypeError, ValueError) as error:
    strategies = {"Swiss Strategy": default_strategy()}
    st.warning(f"Saved strategies could not be loaded: {error}")

pending = st.session_state.pop("pending_strategy", None)
if pending in strategies:
    st.session_state["selected_strategy"] = pending
message = st.session_state.pop("strategy_saved_message", None)
if message:
    st.success(message)

with st.sidebar:
    st.title("Capacity Lab")
    st.caption("Three-pillar capacity model · USD")
    selected_strategy_name = st.selectbox("Saved strategy", list(strategies), key="selected_strategy")
selected_strategy = strategies[selected_strategy_name]
saved = {**DEFAULT_PARAMETERS, **selected_strategy["parameters"]}
main_key = f"execution::{selected_strategy_name}::"
demo_key = main_key+"pillars::"
model_kind="Three-pillar empirical"
strategy_ir_points = pd.DataFrame(selected_strategy["ir_points"])[IR_COLUMNS]
try:
    strategy_ir_fit = fit_ir_curve(strategy_ir_points)
    strategy_ir_fit_error = None
except (KeyError, TypeError, ValueError) as error:
    strategy_ir_fit, strategy_ir_fit_error = None, str(error)

with st.sidebar:
    st.caption("Three pillars: impact costs, alpha decay and transfer coefficient. Calibrate their shapes in Model Calibration.")
    alpha_points=[[float(st.session_state.get(demo_key+f"triple_{i}_{j}",value)) for j,value in enumerate(point)] for i,point in enumerate(saved["alpha_points"])]
    tc_points=[[float(st.session_state.get(demo_key+f"tc_triple_{i}_{j}",value)) for j,value in enumerate(point)] for i,point in enumerate(saved["tc_points"])]
    st.subheader("Strategy anchor")
    aum0=st.number_input("Current AUM ($bn)",MIN_AUM,1000.,max(MIN_AUM,float(saved["aum0"])),.1,key=main_key+"aum0")
    gross_alpha=st.number_input("Baseline gross alpha (%)",0.,100.,float(saved["gross_alpha"]),.05,key=main_key+"gross_alpha",
        help="Annual gross alpha at current AUM, before impact costs. The calibrated pillars define relative retention around this anchor.")
    tracking_error=st.number_input("Tracking error (%)",.01,100.,float(saved["tracking_error"]),.1,key=main_key+"tracking_error")
    horizon_key=main_key+"max_aum"
    if horizon_key in st.session_state and st.session_state[horizon_key]<aum0:
        st.session_state[horizon_key]=aum0
    horizon_default={} if horizon_key in st.session_state else {"value":max(aum0,float(saved["max_aum"]))}
    max_aum=st.number_input("Chart horizon ($bn)",min_value=aum0,max_value=1000.,step=1.,key=horizon_key,**horizon_default)
    st.subheader("Simulation")
    if not st.session_state.get("capacity_interval_ui_migrated"):
        st.session_state[main_key+"calculation_mode"]="Monte Carlo"
        st.session_state["capacity_interval_ui_migrated"]=True
    calculation_mode=st.selectbox("Calculation mode",["Deterministic","Monte Carlo"],
        index=0 if saved["calculation_mode"]=="Deterministic" else 1,key=main_key+"calculation_mode",
        help="Monte Carlo adds 20–80% IR bands and the capacity interval at minimum IR.")
    uncertainty_source="Stock selections only"
    mc_samples=int(st.session_state.get(demo_key+"samples",saved["mc_samples"]))
    mc_seed=int(st.session_state.get(demo_key+"seed",saved["mc_seed"]))
    st.caption("Only stock selections vary. Sample count and seed are in Model Calibration → ADV bucket sampler.")
    with st.expander("Execution reference"):
        daily=st.number_input("Daily participation (% ADV)",.1,100.,float(saved["daily"]),.5,key=main_key+"daily",
            help="Used by the execution-time reference in alpha calibration. It does not change order/ADV buckets or the combined IR curve.")
    # Preserve retired settings as metadata; none is an active sidebar cost/alpha input.
    half_life=float(saved["half_life"])
    annual_cost_bps=float(saved["annual_cost_bps"])
    cost_elasticity=float(saved["cost_elasticity"])
    retained_threshold=float(saved["retained_threshold"])
    st.subheader("Decision threshold")
    minimum_ir=st.number_input("Minimum net IR",0.,10.,float(saved["minimum_ir"]),.05,key=main_key+"minimum_ir")
    with st.expander("Backtest IR comparison"):
        if strategy_ir_fit is None:
            backtest_a = backtest_b = backtest_gamma = None
            st.warning(f"Backtest observations could not be fitted: {strategy_ir_fit_error}")
        else:
            st.caption("Separate empirical curve: IR(A) = a − b A^γ.")
            backtest_a = st.number_input("Backtest a", value=float(strategy_ir_fit["a"]), step=.01, format="%.4f", key=main_key+"backtest_a")
            backtest_b = st.number_input("Backtest b", min_value=0.0, value=float(strategy_ir_fit["b"]), step=.005, format="%.5f", key=main_key+"backtest_b")
            backtest_gamma = st.number_input("Backtest γ", .20, 3.0, float(strategy_ir_fit["gamma"]), .05, key=main_key+"backtest_gamma")
    with st.expander("Display markers"):
        regulatory_raw = st.text_input("Implied regulatory AUM ($bn)", value="" if saved["regulatory_aum"] is None else str(saved["regulatory_aum"]), key=main_key+"regulatory_aum")
        competition_raw = st.text_input("Median competition AUM ($bn)", value="" if saved["competition_aum"] is None else str(saved["competition_aum"]), key=main_key+"competition_aum")

st.title("Capacity Analysis")
st.caption("Three calibrated pillars → empirical net alpha and IR")
summary, overview, backtest_ir, execution, inputs, methodology = st.tabs([
    "Summary", "Empirical IR curve", "Backtest IR curve", "Model Calibration", "Inputs & strategy", "Methodology",
])
creator = inputs

with inputs:
    st.subheader("Baseline order inputs")
    st.info("The existing buckets describe total parent-order notional / ADV, as confirmed. All order sizes are anchored to current AUM.")
    source_options = ["Universe ADV sampler", "Trade CSV"]
    source = st.radio("Order input source", source_options,
                      index=1 if selected_strategy.get("trades") else 0,
                      key=main_key+"source", horizontal=True)
    st.caption("The universe sampler selects stocks uniformly with replacement and gives every order equal absolute notional. Historical buckets provide impact-cost calibration and comparison data; they do not determine simulated bucket frequencies. Trade CSV remains available for actual orders.")
    universe_controls=st.columns(2)
    universe_size=int(universe_controls[0].number_input("Stocks in universe",1,10000,int(saved.get("universe_size",300)),1,key=main_key+"universe_size",disabled=source=="Trade CSV"))
    annual_trades=int(universe_controls[1].number_input("Annual parent orders (12 monthly rebalances)",1,1000000,int(saved.get("annual_trades",971)),1,key=main_key+"annual_trades",disabled=source=="Trade CSV"))
    st.caption(f"{annual_trades:,} annual orders ≈ {annual_trades/12:.2f} per month. The strategy rebalances monthly; the annual simulation pools 12 monthly rebalances. Fixed ADV and independent selections mean calendar grouping does not change annual results.")
    with st.expander("Universe ADV percentile inputs"):
        active_adv_points=st.data_editor(pd.DataFrame(selected_strategy.get("adv_points") or ADV_POINTS.to_dict("records")),
            hide_index=True,num_rows="dynamic",width="stretch",key=main_key+"adv_points",
            column_config={"percentile":st.column_config.NumberColumn("Stock percentile",format="%.2f"),
                           "advUsd":st.column_config.NumberColumn("ADV (USD/day)",format="%.2f")})
        st.caption("Locally saved ADV boundaries; log-dollar interpolation at midpoint stock ranks approximates individual stocks. These are percentile boundaries, not decile means or an observed stock-level tape.")
    st.subheader("Historical ADV buckets and estimated impact costs")
    bucket_editor_input=pd.DataFrame(selected_strategy["buckets"])[BUCKET_COLUMNS].copy()
    ratio_columns=["lower","upper","p"]
    bucket_editor_input[ratio_columns]*=100
    bucket_formats={column:st.column_config.NumberColumn(format="%.2f") for column in BUCKET_COLUMNS if column!="label"}
    bucket_formats.update({"p":st.column_config.NumberColumn("Representative order/ADV (%)",format="%.2f"),
                           "lower":st.column_config.NumberColumn("Lower order/ADV (%)",format="%.2f"),
                           "upper":st.column_config.NumberColumn("Upper order/ADV (%)",format="%.2f"),
                           "valueUsdMillion":st.column_config.NumberColumn("Traded value (USD m)",format="%.2f")})
    active_buckets=st.data_editor(bucket_editor_input,hide_index=True,num_rows="dynamic",width="stretch",
                                  key=main_key+"buckets_percent",column_config=bucket_formats).copy()
    active_buckets[ratio_columns]/=100
    active_trades = None
    if source == "Trade CSV":
        uploaded = st.file_uploader("Upload baseline parent orders", type=["csv"], key=main_key+"trades")
        st.caption("Required columns: q (positive total parent-order notional), adv (positive average daily traded value), in the same currency. Each row is one order; buys and sells both use positive magnitudes. Uploads are saved only when you save the strategy.")
        st.download_button("Download CSV template", "q,adv\n100000,10000000\n500000,20000000\n", "baseline_orders_template.csv", "text/csv")
        try:
            if uploaded is not None:
                active_trades = validate_trades(pd.read_csv(io.BytesIO(uploaded.getvalue())))
            elif selected_strategy.get("trades"):
                active_trades = validate_trades(pd.DataFrame(selected_strategy["trades"]))
            else:
                st.warning("Upload a trade CSV or choose Universe ADV sampler.")
                st.stop()
            display_table(active_trades, hide_index=True, width="stretch")
        except (ValueError, TypeError, pd.errors.ParserError) as error:
            st.error(f"Invalid trade CSV: {error}")
            st.stop()
    st.caption("In the empirical model, changing the order data or estimated bucket costs updates impact estimation. The isolated alpha-decay and TC curves remain controlled by their calibration triples.")

turnover=float(st.session_state.get(demo_key+"impact_turnover",saved.get("turnover",13.9)))
scenario = Scenario(aum0=aum0, gross_alpha=gross_alpha, tracking_error=tracking_error,
                    daily_participation=daily, half_life=half_life,
                    annual_cost_bps=annual_cost_bps, cost_elasticity=cost_elasticity)
with execution:
    st.subheader("Model Calibration")
    st.caption("Calibrate the relative shape of the three pillars here. Gross alpha in Capacity Lab fixes the level at current AUM. Changes update Empirical IR curve and Summary; calculations start at USD 500m.")
    sampler_tab, alpha_tab, tc_tab = st.tabs([
        "a) ADV bucket sampler", "b) Alpha decay", "c) Transfer coefficient decay",
    ])
    demo_key = main_key+"pillars::"
    with sampler_tab:
        st.write("Universe ADV → equal-notional parent orders → ADV bucket migration → estimated impact costs.")
        controls=st.columns(3)
        demo_samples=controls[0].number_input("Sampler Monte Carlo samples",2,20000,int(mc_samples),100,key=demo_key+"samples",help="Number of simulated annual books. Universe mode uses the annual order-count input; CSV mode uses the observed row count.")
        demo_seed=controls[1].number_input("Sampler random seed",0,2**32-1,int(mc_seed),1,key=demo_key+"seed")
        turnover=controls[2].number_input("Impact one-way annual turnover (%)",min_value=0.,value=float(saved.get("turnover",13.9)),step=.5,key=demo_key+"impact_turnover",help="Annual portfolio drag = 2 × one-way turnover fraction × impact per traded dollar.")
        sample_aum_key=demo_key+"sample_aum"
        previous_anchor=st.session_state.get(demo_key+"preview_anchor")
        preview=st.session_state.get(sample_aum_key)
        if previous_anchor is None or preview is None or np.isclose(preview,previous_anchor,rtol=0,atol=1e-9):
            st.session_state[sample_aum_key]=float(aum0)
        elif preview>max_aum:
            st.session_state[sample_aum_key]=float(max_aum)
        st.session_state[demo_key+"preview_anchor"]=float(aum0)
        sample_aum=st.number_input("Sampler AUM (USD bn)",min_value=MIN_AUM,max_value=float(max_aum),step=.1,key=sample_aum_key,
                                   help="Preview defaults to current AUM. Universe order size = 2 × turnover fraction × AUM / annual order count; stock ADV stays fixed.")
        st.caption(f"Order-size baseline: current AUM (${aum0:g}bn). Preview order sizes are scaled by {sample_aum/aum0:.2f}×. Calculations start at $0.5bn; gross alpha is anchored at current AUM.")
        st.caption("Universe mode samples stocks uniformly with replacement. Every order has the same absolute notional: 2 × one-way turnover fraction × AUM / annual parent-order count. Trade CSV mode resamples complete observed orders. ADV stays fixed as AUM grows.")
        mc_samples=int(demo_samples)
        mc_seed=int(demo_seed)
        try:
            sampler=create_liquidity_engine(scenario,active_buckets,active_trades,"Monte Carlo",int(demo_samples),int(demo_seed),
                active_adv_points,universe_size,annual_trades,turnover)
        except (ValueError,TypeError) as error:
            st.error(f"Check sampler inputs: {error}")
            st.stop()
        if active_trades is None:
            ticket=2*turnover/100*sample_aum*1e9/annual_trades
            st.caption(f"Approximate universe: {universe_size:,} stocks · {annual_trades:,} orders per annual book · equal ticket at preview AUM: ${ticket:,.2f}. Total traded notional reconciles exactly to turnover in every simulated book.")
        sample_key=demo_key+"book"
        if sample_key in st.session_state and st.session_state[sample_key]>int(demo_samples):
            st.session_state[sample_key]=int(demo_samples)
        sample_default={} if sample_key in st.session_state else {"value":1}
        book_details=st.expander("Inspect a simulated trading book")
        with book_details:
            sample_id=st.number_input("Simulated book to inspect",min_value=1,max_value=int(demo_samples),step=1,key=sample_key,**sample_default)
        book=sampler.sampled_book(int(sample_id)-1,float(sample_aum))
        # This view focuses on order composition and impact; signal parameters are separate.
        book=book.drop(columns=["Execution days","Absolute capture"])

        c1,c2,c3=st.columns(3)
        c1.metric("Orders in sampled book",f"{int(book['Sampled orders'].sum()):,}")
        c2.metric("Selected AUM",f"USD {sample_aum:g}bn")
        c3.metric("Sampled traded notional",f"USD {book['Sampled notional (USD)'].sum()/1e6:,.2f}m")
        st.subheader("Trade migration across ADV buckets")
        try:
            migration,_=bucket_migration(book,active_buckets,aum0)
        except (ValueError,KeyError,TypeError) as error:
            st.warning(f"Bucket migration cannot be shown: {error}")
        else:
            migration_plot=migration.copy()
            scenario_names={0:f"Current · ${aum0:g}bn",1:f"×2 · ${2*aum0:g}bn",2:f"×3 · ${3*aum0:g}bn"}
            migration_plot['AUM scenario']=migration_plot.Stage.map(scenario_names)
            fig=px.bar(migration_plot,x='Bucket',y='Trade share (%)',color='AUM scenario',barmode='group',
                       title='Trade frequency by ADV bucket',color_discrete_sequence=[GREEN,AMBER,BLUE],
                       category_orders={'Bucket':migration[migration.Stage==0].Bucket.tolist(),
                                        'AUM scenario':list(scenario_names.values())},
                       custom_data=['Trades','AUM (USD bn)'])
            fig.update_traces(hovertemplate="ADV bucket: %{x}<br>Frequency: %{y:.2f}%<br>Trades: %{customdata[0]:,}<br>AUM: $%{customdata[1]:g}bn<extra>%{fullData.name}</extra>")
            fig.update_layout(xaxis_title='ADV bucket (parent order/ADV)',yaxis_title='Trade frequency (%)')
            fig.update_yaxes(range=[0,100],ticksuffix='%')
            st.plotly_chart(style_figure(fig),width="stretch")
            st.caption(f"Same simulated book #{int(sample_id)} at all three levels: {int(book['Sampled orders'].sum()):,} parent orders, seed {int(demo_seed)}. Bars show the percentage of trades in each bucket. Order sizes grow with AUM; ADV stays fixed. Current means the Capacity Lab current AUM, independently of Sampler AUM and chart horizon.")
            st.caption("Buckets include their lower bound and exclude their upper bound. An overflow bucket retains orders at or above the highest boundary. Universe mode derives participation from equal tickets and stock ADV; CSV mode uses actual order/ADV pairs.")
            with st.expander("Bucket migration data"):
                display_table(migration[['Scenario','AUM (USD bn)','Bucket','Trades','Trade share (%)']],hide_index=True,width="stretch")
                st.download_button("Export bucket migration CSV",migration.assign(book_number=int(sample_id),seed=int(demo_seed)).to_csv(index=False),"bucket_migration.csv","text/csv")
        try:
            impact_fit=fit_impact_cost(active_buckets,"cost")
        except (ValueError,KeyError,TypeError) as error:
            st.warning(f"Impact curve cannot be fitted: {error}")
        else:
            impact_a,impact_b,impact_gamma=impact_fit.a,impact_fit.b,impact_fit.gamma
            actual_cost=active_buckets.cost.to_numpy(float)
            observed_x=active_buckets.p.to_numpy(float)
            observed_average=float(np.average(actual_cost,weights=active_buckets.valueUsdMillion.to_numpy(float)))
            book["Estimated impact (bp/traded dollar)"]=impact_bps(book["Order/ADV at selected AUM"],impact_a,impact_b,impact_gamma)
            book["Estimated impact cost (USD)"]=book["Sampled notional (USD)"]*book["Estimated impact (bp/traded dollar)"]/10000
            sampled_average=float(np.dot(book["Sampled notional weight"],book["Estimated impact (bp/traded dollar)"]))
            metrics=st.columns(4)
            metrics[0].metric("Observed weighted bucket impact",f"{observed_average:.2f} bp")
            metrics[1].metric("Sampled weighted impact",f"{sampled_average:.2f} bp")
            metrics[2].metric("Sampled order impact cost",f"${book['Estimated impact cost (USD)'].sum():,.0f}")
            metrics[3].metric("Implied annual portfolio drag",f"{2*turnover/100*sampled_average:.2f} bp")
            st.caption("Observed impact uses baseline traded-value weights. Sampled impact and dollar cost describe the selected book; annual drag uses the turnover assumption. Historical bucket frequencies are a comparison, not a calibration target for the universe sampler.")
            plot_max=max(float(observed_x.max()),float(book['Order/ADV at selected AUM'].max()),.001)
            log_impact_axis=plot_max>10*float(observed_x.max())
            positive_x=np.r_[observed_x[observed_x>0],book.loc[book['Order/ADV at selected AUM']>0,'Order/ADV at selected AUM']]
            xs=np.geomspace(float(positive_x.min())/2,plot_max,301) if log_impact_axis else np.linspace(0,plot_max,201)
            fig=go.Figure()
            fig.add_scatter(x=100*xs,y=impact_bps(xs,impact_a,impact_b,impact_gamma),mode="lines",name="Automatically fitted impact",line=dict(color=GREEN))
            fig.add_scatter(x=100*observed_x,y=actual_cost,mode="markers",name="Estimated bucket costs",marker=dict(color=AMBER,size=10))
            fig.add_scatter(x=100*book['Order/ADV at selected AUM'],y=book['Estimated impact (bp/traded dollar)'],mode="markers",name="Sampled order support",marker=dict(color=BLUE,symbol="x"))
            fig.update_layout(title="Impact cost fitted to ADV buckets",xaxis_title="Parent order/ADV (%)"+ (" · log scale" if log_impact_axis else ""),yaxis_title="Impact (bp per traded dollar)")
            if log_impact_axis:
                fig.update_xaxes(type="log")
            st.plotly_chart(style_figure(fig),width="stretch")
            cost_curve=impact_curve(sampler,max_aum,impact_a,impact_b,impact_gamma,turnover)
            fig=go.Figure()
            fig.add_scatter(x=cost_curve.AUM,y=cost_curve['Annual drag P80 (portfolio bp)'],mode="lines",line=dict(width=0),showlegend=False)
            fig.add_scatter(x=cost_curve.AUM,y=cost_curve['Annual drag P20 (portfolio bp)'],mode="lines",line=dict(width=0),fill="tonexty",fillcolor="rgba(66,199,165,0.18)",name="20–80% stock-selection range" if active_trades is None else "20–80% order-resampling range")
            fig.add_scatter(x=cost_curve.AUM,y=cost_curve['Annual drag (portfolio bp)'],mode="lines",name="Mean annual impact drag",line=dict(color=GREEN))
            fig.update_layout(title="Estimated annual impact cost across AUM",xaxis_title="AUM (USD bn)",yaxis_title="Annual impact drag (portfolio bp)")
            fig.update_xaxes(range=[MIN_AUM,max_aum] if max_aum>MIN_AUM else [MIN_AUM,MIN_AUM+.01])
            st.plotly_chart(style_figure(fig),width="stretch")
            st.caption("The cost curve is fitted automatically from estimated bucket costs; Monte Carlo varies selected stocks (or resamples actual CSV orders). Bands exclude uncertainty in the fit. Predictions outside the observed order/ADV range are extrapolations. Sampler count, seed and turnover also drive the combined empirical model. The isolated calibration triples are unchanged.")
            with st.expander("Fit details and exports"):
                st.write(f"Automatic fit: a = {impact_a:.5f} bp, b = {impact_b:.5f} bp, curvature = {impact_gamma:.5f}. Equal-weight bucket RMSE = {impact_fit.rmse:.3f} bp.")
                st.caption("The fitted curve uses fractional order/ADV. Portfolio costs use notional weights. Annual drag = 2 × one-way turnover fraction × weighted impact; dollar costs price the sampled orders directly.")
                display_table(active_buckets[["label","p","trades","valueUsdMillion","cost"]],hide_index=True,width="stretch")
                impact_metadata={"impact_a":impact_a,"impact_b":impact_b,"impact_gamma":impact_gamma,
                                 "one_way_turnover_pct":turnover,"calibration_column":"cost",
                                 "baseline_aum_usd_bn":aum0,"samples":int(demo_samples),"seed":int(demo_seed),
                                 "order_source":sampler.source,"universe_size":universe_size,"annual_orders":sampler.book_size}
                st.download_button("Export sampled impact costs CSV",book.assign(aum_usd_bn=sample_aum,book_number=int(sample_id),**impact_metadata).to_csv(index=False),"sampled_impact_costs.csv","text/csv")
                st.download_button("Export impact cost curve CSV",cost_curve.assign(**impact_metadata).to_csv(index=False),"impact_cost_curve.csv","text/csv")
        with book_details:
            edges=active_buckets.upper.to_numpy(float)
            labels=active_buckets.label.astype(str).tolist()+[f">={edges[-1]*100:g}%"]
            # Historical bucket observations are a diagnostic, not a sampling prior.
            raw_counts=np.r_[active_buckets.trades.to_numpy(float),0.]
            raw_values=np.r_[active_buckets.valueUsdMillion.to_numpy(float)*1e6,0.]
            categories=np.searchsorted(edges,book['Order/ADV at selected AUM'].to_numpy(),side="right")
            sampled_counts=np.bincount(categories,weights=book['Sampled orders'],minlength=len(labels))
            sampled_values=np.bincount(categories,weights=book['Sampled notional (USD)'],minlength=len(labels))
            total=sampled_values.sum()
            shares=pd.DataFrame({"ADV bucket":labels,
                "Historical count share (%)":100*raw_counts/raw_counts.sum(),"Simulated count share (%)":100*sampled_counts/sampled_counts.sum(),
                "Historical notional share (%)":100*raw_values/raw_values.sum(),"Simulated notional share (%)":100*sampled_values/total if total>0 else np.zeros(len(labels))})
            st.caption("Historical buckets describe current AUM; simulated shares describe the selected preview AUM. Universe-mode total notional is fixed by turnover, and equal tickets make count shares equal notional shares. A mismatch with history exposes the uniform-selection/equal-ticket assumptions.")
            for columns,title in [(["Historical count share (%)","Simulated count share (%)"],"Historical vs simulated order counts"),(["Historical notional share (%)","Simulated notional share (%)"],"Historical vs simulated traded notional")]:
                melted=shares.melt(id_vars="ADV bucket",value_vars=columns,var_name="Series",value_name="Share (%)")
                fig=px.bar(melted,x="ADV bucket",y="Share (%)",color="Series",barmode="group",title=title,color_discrete_sequence=[GREEN,AMBER])
                st.plotly_chart(style_figure(fig),width="stretch")
            positive=book[book['Sampled notional (USD)']>0].sort_values('Order/ADV at selected AUM').copy()
            positive['Order/ADV (% at selected AUM)']=100*positive['Order/ADV at selected AUM']
            positive['Cumulative sampled notional (%)']=100*positive['Sampled notional (USD)'].cumsum()/positive['Sampled notional (USD)'].sum()
            fig=px.line(positive,x='Order/ADV (% at selected AUM)',y='Cumulative sampled notional (%)',markers=True,title='Sampled order-size distribution',color_discrete_sequence=[BLUE])
            fig.update_traces(line_shape="hv")
            st.plotly_chart(style_figure(fig),width="stretch")
            display_table(shares,hide_index=True,width="stretch")
            display_table(book,hide_index=True,width="stretch")
            if active_trades is None:
                monthly=sampler.monthly_book(int(sample_id)-1,float(sample_aum))
                monthly_summary=monthly.groupby('Month',as_index=False).agg(
                    **{'Parent orders':('Parent orders','sum'),'Traded notional (USD)':('Traded notional (USD)','sum')})
                st.caption("Monthly rebalance allocation of this same annual book. Order counts sum to the annual input; fixed ADV and equal tickets leave annual costs unchanged.")
                display_table(monthly_summary,hide_index=True,width="stretch")
                st.download_button("Export monthly sampled book CSV",monthly.assign(seed=int(demo_seed),
                    book_number=int(sample_id)).to_csv(index=False),"monthly_sampled_book.csv","text/csv")
            st.download_button("Export sampled book CSV",book.assign(aum_usd_bn=sample_aum,book_number=int(sample_id),seed=int(demo_seed)).to_csv(index=False),"demo_sampled_book.csv","text/csv")

    with alpha_tab:
        st.subheader("Alpha decay")
        st.write("Calibrate AUM → percentage of parent orders taking more than one day → net IR. Other effects remain fixed.")
        candidate_points = []
        for i, point in enumerate(saved["alpha_points"]):
            cols = st.columns(3)
            a = cols[0].number_input(f"Demo point {i+1} AUM ($bn)", .5, 1000., float(point[0]), .5, key=demo_key+f"triple_{i}_0", disabled=i==0)
            b = cols[1].number_input(f"Demo point {i+1} trades >1 day (%)", 0., 100., float(point[1]), .5, key=demo_key+f"triple_{i}_1", disabled=i==0)
            ir = cols[2].number_input(f"Demo point {i+1} net IR", value=float(point[2]), step=.01, key=demo_key+f"triple_{i}_2")
            candidate_points.append([a,b,ir])
        alpha_points=candidate_points
        try:
            candidate = AlphaDecayModel(candidate_points, tracking_error)
            ir_demo = candidate.curve(candidate_points[-1][0])
        except ValueError as error:
            st.warning(str(error))
        else:
            c1,c2 = st.columns(2)
            c1.metric("Implied AUM curvature", f"{candidate.k:.5f}")
            c2.metric("Implied congestion-to-IR curvature", f"{candidate.gamma:.5f}")
            st.caption("Curvatures are fitted automatically. Edit the triples to calibrate the shape. Trade percentages are count-weighted, not notional-weighted.")
            reference = create_liquidity_engine(scenario, active_buckets, active_trades, "Deterministic",
                                                adv_points=active_adv_points,universe_size=universe_size,
                                                annual_trades=annual_trades,turnover=turnover)
            reference_share = [reference.metric(float(a))["Multi-day count (%)"] for a in ir_demo["AUM"]]
            st.caption("The dotted liquidity reference uses the active order data and Capacity Lab participation at current AUM. It is a comparison, not an automatic fit to your triples.")
            for x,y,title in [("AUM","Multi-day count (%)","AUM → trades >1 day"),
                              ("Multi-day count (%)","Net IR","Trades >1 day → IR"),
                              ("AUM","Net IR","Resulting AUM → IR")]:
                fig=px.line(ir_demo,x=x,y=y,title=title,color_discrete_sequence=[GREEN])
                if y == "Multi-day count (%)":
                    fig.add_scatter(x=ir_demo["AUM"], y=reference_share, mode="lines", name="Active liquidity reference", line=dict(color=BLUE,dash="dot"))
                if x == "AUM":
                    fig.update_xaxes(title="AUM (USD bn)",range=[.5,candidate_points[-1][0]])
                mapping={"AUM":0,"Multi-day count (%)":1,"Net IR":2}
                points=np.asarray(candidate_points)
                fig.add_scatter(x=points[:,mapping[x]],y=points[:,mapping[y]],mode="markers",name="Calibration points",marker=dict(color=AMBER,size=10))
                st.plotly_chart(style_figure(fig),width="stretch")
            display_table(ir_demo,hide_index=True,width="stretch")
            st.caption("This simplified model ignores how far beyond one day an order takes. Monte Carlo in Capacity Lab conditions on this fitted relationship and assumes independent multi-day order indicators; it does not estimate uncertainty in these three assumptions.")
            st.caption("These points already update the Empirical IR curve and Summary automatically. Save through Inputs & strategy to persist them.")
            st.download_button("Export alpha-decay demo CSV",ir_demo.to_csv(index=False),"demo_alpha_decay.csv","text/csv")
            st.download_button("Download alpha-decay settings",json.dumps({"pillar":"Alpha decay","alpha_points":candidate_points,"aum_curvature":candidate.k,"congestion_ir_curvature":candidate.gamma},indent=2),"alpha_decay_settings.json","application/json")

    with tc_tab:
        st.subheader("Transfer coefficient calibration")
        st.write("Calibrate AUM → transfer coefficient → annual alpha, holding other effects fixed. Alpha is treated as annual net alpha for the Capacity Lab comparison.")
        candidate_tc_points = []
        for i, point in enumerate(saved["tc_points"]):
            cols = st.columns(3)
            tc = cols[0].number_input(f"Demo TC point {i+1} coefficient (%)", 0., 100., float(point[0]), 1., key=demo_key+f"tc_triple_{i}_0")
            a = cols[1].number_input(f"Demo TC point {i+1} AUM ($bn)", .5, 1000., float(point[1]), .5, key=demo_key+f"tc_triple_{i}_1", disabled=i==0)
            alpha = cols[2].number_input(f"Demo TC point {i+1} annual alpha (%)", value=float(point[2]), step=.05, key=demo_key+f"tc_triple_{i}_2")
            candidate_tc_points.append([tc,a,alpha])
        tc_points=candidate_tc_points
        try:
            candidate_tc = TransferCoefficientModel(candidate_tc_points, tracking_error)
            tc_curve = candidate_tc.curve(candidate_tc_points[-1][1])
        except ValueError as error:
            st.warning(str(error))
        else:
            cols=st.columns(2)
            cols[0].metric("Implied AUM-to-TC curvature",f"{candidate_tc.k:.5f}")
            cols[1].metric("Implied TC-to-alpha curvature",f"{candidate_tc.gamma:.5f}")
            if np.isclose(candidate_tc.gamma,1.):
                st.caption("These triples imply a linear TC-to-alpha relationship. The AUM-to-TC relationship remains nonlinear.")
            mapping={"Transfer coefficient (%)":0,"AUM":1,"Net alpha (%)":2}
            points=np.asarray(candidate_tc_points)
            for x,y,title in [("AUM","Transfer coefficient (%)","AUM → transfer coefficient"),
                              ("Transfer coefficient (%)","Net alpha (%)","Transfer coefficient → alpha"),
                              ("AUM","Net alpha (%)","Resulting AUM → alpha")]:
                fig=px.line(tc_curve,x=x,y=y,title=title,color_discrete_sequence=[AMBER])
                fig.add_scatter(x=points[:,mapping[x]],y=points[:,mapping[y]],mode="markers",name="Calibration points",marker=dict(color=GREEN,size=10))
                if x=="AUM":
                    fig.update_xaxes(title="AUM (USD bn)",range=[.5,candidate_tc_points[-1][1]])
                st.plotly_chart(style_figure(fig),width="stretch")
            display_table(tc_curve,hide_index=True,width="stretch")
            st.caption("Curvatures fit the estimated triples exactly. This isolated calibration is separate from the alpha-decay curve. It does not estimate IC, independent breadth or statistical TC uncertainty.")
            st.caption("These points already update the Empirical IR curve and Summary automatically. Save through Inputs & strategy to persist them.")
            st.download_button("Export transfer-coefficient demo CSV",tc_curve.to_csv(index=False),"demo_transfer_coefficient.csv","text/csv")
            st.download_button("Download TC settings",json.dumps({"pillar":"Transfer coefficient","tc_points":candidate_tc_points,"aum_curvature":candidate_tc.k,"tc_alpha_curvature":candidate_tc.gamma},indent=2),"tc_calibration.json","application/json")

try:
    engine=EmpiricalIRModel(scenario,alpha_points,tc_points,active_buckets,active_trades,turnover,calculation_mode,int(mc_samples),int(mc_seed),active_adv_points,universe_size,annual_trades)
    if max_aum>engine.maximum:
        st.warning(f"Empirical chart horizon limited to ${engine.maximum:.2f}bn, where calibrated retention reaches zero.")
        max_aum=engine.maximum
    data=engine.curve(max_aum,calculation_mode=="Monte Carlo")
except (ValueError, TypeError) as error:
    st.error(f"Check model inputs: {error}")
    st.stop()

aum_markers = []
for raw, label, color, dash in [(regulatory_raw, "Implied regulatory AUM", BLUE, "dash"), (competition_raw, "Median competition", "#c698db", "dot")]:
    if raw.strip():
        try:
            value = float(raw)
            if not np.isfinite(value) or value <= 0:
                raise ValueError()
            aum_markers.append({"label": label, "value": value, "color": color, "dash": dash})
            if value < MIN_AUM or value > max_aum:
                st.sidebar.caption(f"{label} lies outside the chart range.")
        except ValueError:
            st.sidebar.warning(f"{label} must be a positive number or blank.")
scenario_multipliers = [1, 1.5, 2, 2.5, 3]
scenario_aums = np.unique(np.r_[MIN_AUM, [aum0*s for s in scenario_multipliers]])
calibration_aums=np.unique(np.r_[np.asarray(alpha_points)[:,0],np.asarray(tc_points)[:,1]])
scenario_aums=np.unique(np.r_[scenario_aums[scenario_aums<=max_aum],calibration_aums[calibration_aums<=max_aum]])
last_calibration_aum=min(float(alpha_points[-1][0]),float(tc_points[-1][1]))
scenario_labels = ["$500m" if a == MIN_AUM else f"×{a/aum0:g}" for a in scenario_aums]
scenario_metrics = [engine.metric(float(a)) for a in scenario_aums]
base = engine.metric(aum0)
capacity_minimum_crossing = engine.capacity(minimum_ir, max_aum)
capacity_zero_crossing = engine.capacity(0, max_aum)
capacity_draws=None
capacity_uncertainty=None
if calculation_mode=="Monte Carlo":
    capacity_draws=engine.capacity_samples(minimum_ir,max_aum)
    capacity_uncertainty=engine.capacity_interval(capacity_draws)

def percentile_display(value):
    return f"${value:.2f}bn" if value is not None else f"> ${max_aum:.2f}bn"

if strategy_ir_fit is not None and backtest_a is not None:
    active_backtest_a, active_backtest_b, active_backtest_gamma = backtest_a, backtest_b, backtest_gamma
    current_backtest_ir = backtest_a - backtest_b * aum0 ** backtest_gamma
    zero_aum = MIN_AUM if backtest_a-backtest_b*MIN_AUM**backtest_gamma <= 0 else (backtest_a/backtest_b)**(1/backtest_gamma) if backtest_b > 0 else np.nan
    minimum_ir_aum = MIN_AUM if backtest_a-backtest_b*MIN_AUM**backtest_gamma <= minimum_ir else ((backtest_a-minimum_ir)/backtest_b)**(1/backtest_gamma) if backtest_b > 0 else np.nan
else:
    active_backtest_a = active_backtest_b = active_backtest_gamma = np.nan
    current_backtest_ir = zero_aum = minimum_ir_aum = np.nan

with overview:
    st.caption(f"Gross alpha is anchored to {gross_alpha:.2f}% per year at current AUM (${aum0:.2f}bn). Alpha-decay and TC calibrations define relative retention; full estimated impact costs are deducted once.")
    st.caption(f"Impact fit uses estimated bucket costs; one-way annual turnover {turnover:.2f}%. Beyond ${last_calibration_aum:.2f}bn is extrapolation.")
    if calculation_mode=="Monte Carlo":
        st.caption(f"{mc_samples:,} draws · {engine.book_size:,} annual orders · seed {mc_seed}. The 20–80% bands vary stock selections only. Gross alpha at current AUM and all pillar calibrations are fixed across draws; central IR equals mean simulated IR.")
    else:
        st.caption("Deterministic curve without intervals. Select Monte Carlo for capacity uncertainty.")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Current net IR",f"{base['Net IR']:.3f}")
    c2.metric("AUM at minimum net IR",percentile_display(capacity_minimum_crossing))
    c3.metric("Current gross alpha",f"{base['Gross alpha (%)']:.2f}%")
    c4.metric("Annual impact drag",f"{base['Annual impact drag (bp)']:.2f} bp")
    for columns, title, ylabel in [(["Net IR"], "Net information ratio", "Net IR"),
                                  (["Net alpha (%)"], "Net alpha", "Net alpha (% per year)")]:
        plot = data.melt(id_vars="AUM", value_vars=columns, var_name="Series", value_name="Value")
        fig = px.line(plot, x="AUM", y="Value", labels={"Value": ylabel}, color="Series", title=title, color_discrete_sequence=PALETTE)
        suffixes=("P20","P80")
        bounds = {"Net IR": tuple(f"Net IR {p}" for p in suffixes),
                  "Net alpha (%)": tuple(f"Net alpha {p} (%)" for p in suffixes)}
        band_key = columns[0]
        if calculation_mode == "Monte Carlo" and band_key in bounds:
            low, high = bounds[band_key]
            fig.add_scatter(x=data["AUM"], y=data[high], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
            fig.add_scatter(x=data["AUM"], y=data[low], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(66,199,165,0.18)", name="20–80% conditional range", hoverinfo="skip")
        if columns == ["Net IR"] and capacity_uncertainty is not None:
            lo=capacity_uncertainty['P20'];hi=capacity_uncertainty['P80']
            if lo is not None:
                fig.add_vrect(x0=lo,x1=hi if hi is not None else max_aum,
                    fillcolor=BLUE,opacity=.12,line_width=0,annotation_text="Capacity P20–P80" if hi is not None else "Capacity P80 beyond horizon")
        if columns == ["Net IR"]:
            fig.add_hline(y=minimum_ir, line_dash="dash", line_color=RUST)
        if max_aum > last_calibration_aum:
            fig.add_vrect(x0=last_calibration_aum, x1=max_aum, fillcolor=AMBER, opacity=.08, line_width=0, annotation_text="Extrapolation")
        add_aum_markers(fig, aum_markers, max_aum)
        fig.update_xaxes(title="AUM (USD bn)", range=[MIN_AUM, max_aum] if max_aum > MIN_AUM else [MIN_AUM, MIN_AUM+.01])
        st.plotly_chart(style_figure(fig), width="stretch")
    table=pd.DataFrame(scenario_metrics)
    table.insert(0,"Scenario",scenario_labels)
    display_table(table,hide_index=True,width="stretch")
    with st.expander("Three-pillar IR breakdown"):
        breakdown=pd.DataFrame(scenario_metrics)
        breakdown['Starting net IR']=engine.initial_ir
        st.caption("Starting net IR at $0.5bn is implied by the current-AUM gross-alpha anchor and baseline impact. Losses reconcile to net IR at each AUM.")
        display_table(breakdown[['AUM','Starting net IR','Alpha retention (%)','TC alpha retention (%)','Alpha-decay loss (IR)','TC loss (IR)','Incremental impact drag (bp)','Impact loss (IR)','Net IR','Net alpha (%)']],hide_index=True,width="stretch")
    export=data.assign(methodology="three-pillar-current-gross-v4",model=model_kind,
        alpha_points=json.dumps(alpha_points),tc_points=json.dumps(tc_points),tracking_error_pct=tracking_error,
        gross_alpha_anchor_pct=gross_alpha,gross_alpha_anchor_aum=aum0,one_way_turnover_pct=turnover,
        impact_a=engine.fit.a,impact_b=engine.fit.b,impact_gamma=engine.fit.gamma,
        order_source=engine.orders.source,universe_size=universe_size,parent_order_count=engine.book_size,
        adv_percentiles=json.dumps(active_adv_points.to_dict("records")),uncertainty_source=uncertainty_source,
        interval_lower_percentile=20,interval_upper_percentile=80,calculation_mode=calculation_mode,
        mc_samples=int(mc_samples),mc_seed=int(mc_seed))
    st.download_button("Export capacity curve CSV", export.to_csv(index=False), "execution_capacity_curve.csv", "text/csv")
    st.download_button("Export active baseline inputs", (active_trades if active_trades is not None else active_buckets).to_csv(index=False),
                       "baseline_orders.csv" if active_trades is not None else "baseline_buckets.csv", "text/csv")

with summary:
    st.subheader("Capacity results")
    if capacity_uncertainty is not None:
        cells=st.columns(4)
        cells[0].metric("Capacity P20",percentile_display(capacity_uncertainty['P20']))
        cells[1].metric("Capacity median (P50)",percentile_display(capacity_uncertainty['P50']))
        cells[2].metric("Capacity P80",percentile_display(capacity_uncertainty['P80']))
        cells[3].metric("Threshold reached within horizon",f"{capacity_uncertainty['Threshold reached (%)']:.2f}%")
        st.caption(f"Minimum net IR {minimum_ir:.2f}. The empirical P20–P80 range is the central 60% of stock-selection outcomes; alpha-decay and TC are fixed.")
    else:
        c1,c2=st.columns(2)
        c1.metric("Empirical AUM at minimum IR",percentile_display(capacity_minimum_crossing))
        c2.metric("Backtest AUM at minimum IR",f"${minimum_ir_aum:.2f}bn" if np.isfinite(minimum_ir_aum) else "Not reached")
    comparison=pd.DataFrame([
        {'Approach':'Empirical IR curve','Current net IR':base['Net IR'],'Current net alpha (%)':base['Net alpha (%)'],
         'AUM at minimum IR (central)':percentile_display(capacity_minimum_crossing),'AUM at zero IR (central)':percentile_display(capacity_zero_crossing)},
        {'Approach':'Backtest IR curve','Current net IR':current_backtest_ir,'Current net alpha (%)':current_backtest_ir*tracking_error,
         'AUM at minimum IR (central)':f"${minimum_ir_aum:.2f}bn" if np.isfinite(minimum_ir_aum) else 'Not reached',
         'AUM at zero IR (central)':f"${zero_aum:.2f}bn" if np.isfinite(zero_aum) else 'Not reached'}])
    if capacity_uncertainty is not None:
        comparison['Capacity P20']=[percentile_display(capacity_uncertainty['P20']),'Not simulated']
        comparison['Capacity median']=[percentile_display(capacity_uncertainty['P50']),'Not simulated']
        comparison['Capacity P80']=[percentile_display(capacity_uncertainty['P80']),'Not simulated']
    display_table(comparison,hide_index=True,width="stretch")
    st.subheader("Both approaches across AUM")
    comparison_scenarios=pd.DataFrame({'AUM (USD bn)':scenario_aums,
        'Empirical net IR':[m['Net IR'] for m in scenario_metrics],
        'Backtest net IR':[active_backtest_a-active_backtest_b*a**active_backtest_gamma if np.isfinite(active_backtest_a) else np.nan for a in scenario_aums]})
    display_table(comparison_scenarios,hide_index=True,width="stretch")
    # The distribution is deliberately last, after results and both tables.
    if capacity_uncertainty is not None:
        st.subheader("Simulation distribution")
        reached=capacity_draws.loc[capacity_draws['Threshold reached']]
        if len(reached):
            fig=px.histogram(reached,x='AUM at minimum IR (USD bn)',nbins=40,
                title='Distribution of AUM at minimum IR',color_discrete_sequence=[GREEN])
            fig.update_layout(yaxis_title='Simulations',xaxis_title='AUM at minimum IR (USD bn)')
            for key,color in [('P20',BLUE),('P50',AMBER),('P80',BLUE)]:
                value=capacity_uncertainty[key]
                if value is not None:fig.add_vline(x=value,line_color=color,line_dash='dash',annotation_text=key)
            st.plotly_chart(style_figure(fig),width="stretch")
        if capacity_uncertainty['Censored simulations']:
            st.caption(f"{capacity_uncertainty['Censored simulations']:,} simulations remain beyond ${max_aum:.2f}bn and are included in the percentile calculation. The histogram shows reached crossings only.")
        st.download_button('Export simulated capacity crossings CSV',capacity_draws.assign(seed=int(mc_seed),uncertainty_source=uncertainty_source).to_csv(index=False),'simulated_capacity_crossings.csv','text/csv')

with backtest_ir:
    if selected_strategy.get("ir_points_source") == "illustrative-default":
        st.info("These backtest observations are illustrative defaults. Replace them with actual optimised-backtest observations in Inputs & strategy before interpreting the comparison as historical evidence.")
    st.subheader("IR curve from optimised backtests")
    st.write(
        "The curve uses the historical optimised-backtest observations saved in Inputs & strategy. "
        "Its a, b, and γ parameters can be adjusted in the Capacity Lab sidebar."
    )
    if strategy_ir_fit is None or backtest_a is None or backtest_b is None or backtest_gamma is None:
        st.warning(f"The IR curve could not be fitted: {strategy_ir_fit_error}")
    else:
        ir_fit = strategy_ir_fit
        fit_a = active_backtest_a
        fit_b = active_backtest_b
        fit_gamma = active_backtest_gamma
        observed_x = np.asarray(ir_fit["x"], dtype=float)
        observed_y = np.asarray(ir_fit["y"], dtype=float)
        fitted_observations = fit_a - fit_b * observed_x ** fit_gamma
        residual_sse = float(np.sum((observed_y - fitted_observations) ** 2))
        total_sse = float(np.sum((observed_y - observed_y.mean()) ** 2))
        parameter_r_squared = 1.0 - residual_sse / total_sse if total_sse > 1e-16 else 1.0
        metrics = st.columns(5)
        metrics[0].metric("Fitted IR at current AUM", f"{current_backtest_ir:.3f}")
        metrics[1].metric(
            "AUM at minimum IR",
            f"${minimum_ir_aum:.2f}bn" if np.isfinite(minimum_ir_aum) else "Not reached",
            f"Minimum IR = {minimum_ir:.2f}",
            delta_color="off",
        )
        metrics[2].metric("Zero-IR AUM", f"${zero_aum:.2f}bn" if np.isfinite(zero_aum) else "Not reached")
        metrics[3].metric("Model R²", f"{parameter_r_squared:.4f}")
        metrics[4].metric("Model γ", f"{fit_gamma:.3f}")

        fit_horizon = max(float(max_aum), float(observed_x.max()), float(aum0))
        fit_x = np.linspace(MIN_AUM, fit_horizon, 301)
        fit_y = fit_a - fit_b * fit_x ** fit_gamma
        fig = go.Figure()
        fig.add_scatter(
            x=fit_x, y=fit_y, mode="lines", name="Fitted backtest IR",
            line=dict(color=GREEN, width=3),
            hovertemplate="AUM: $%{x:.2f}bn<br>Fitted IR: %{y:.3f}<extra></extra>",
        )
        fig.add_scatter(
            x=observed_x[observed_x >= MIN_AUM], y=observed_y[observed_x >= MIN_AUM], mode="markers", name="Backtest observations",
            marker=dict(color=AMBER, size=10),
            hovertemplate="AUM: $%{x:.2f}bn<br>Observed IR: %{y:.3f}<extra></extra>",
        )
        fig.add_hline(y=0, line_color="#8b9390", line_width=1)
        fig.add_hline(
            y=minimum_ir, line_dash="dash", line_color=RUST,
            annotation_text=f"Minimum IR {minimum_ir:.2f}", annotation_font_color=RUST,
        )
        fig.add_vline(
            x=float(aum0), line_dash="dot", line_color=BLUE,
            annotation_text=f"Current AUM ${aum0:g}bn", annotation_font_color=BLUE,
        )
        add_aum_markers(fig, aum_markers, fit_horizon)
        fig.update_layout(
            title="Backtest information ratio by AUM",
            xaxis=dict(title="AUM (USD bn)", range=[MIN_AUM, fit_horizon]), yaxis_title="Information ratio",
            legend=dict(orientation="h", y=1.12),
        )
        st.plotly_chart(style_figure(fig), width="stretch")
        st.latex(
            rf"IR(A)={fit_a:.4f}-{fit_b:.4f}A^{{{fit_gamma:.3f}}}"
        )
        st.caption(
            "The saved observations determine the default fit; sidebar edits create an active scenario without "
            "changing the strategy. Treat the curve as empirical strategy evidence alongside the empirical capacity curve."
        )


with methodology:
    st.download_button("Download methodology PDF", (Path(__file__).parent / "methodology.pdf").read_bytes(),
                       "capacity_methodology.pdf", "application/pdf")

with creator:
    st.subheader("Save the current analysis as a strategy")
    st.write("Save the current sidebar assumptions, edited bucket inputs, selected trade tape and backtest observations. Use a new name to create a copy. Existing legacy data is preserved as metadata.")
    with st.form("save_execution_strategy"):
        strategy_name = st.text_input("Strategy name", value=selected_strategy_name)
        creator_ir_points = st.data_editor(strategy_ir_points, num_rows="dynamic", hide_index=True, width="stretch",
            column_config={"aumBn": st.column_config.NumberColumn("AUM (USD bn)", min_value=0.0,format="%.2f"),
                           "ir": st.column_config.NumberColumn("Backtest IR",format="%.2f")}, key=main_key+"saved_ir")
        st.caption("Backtest parameters will be refitted from these saved observations when the strategy is loaded.")
        save_clicked = st.form_submit_button("Save strategy", type="primary")
    if save_clicked:
        try:
            def marker_value(raw):
                if not raw.strip():
                    return None
                value = float(raw)
                if not np.isfinite(value) or value <= 0:
                    raise ValueError("Display-marker AUM must be positive or blank.")
                return value
            parameters = {**saved, "engine_name": "Three-pillar empirical", "model_kind": model_kind, "alpha_points": alpha_points, "tc_points": tc_points, "aum0": aum0,
                          "gross_alpha": gross_alpha, "tracking_error": tracking_error,
                          "universe_size":universe_size,"annual_trades":annual_trades,
                          "max_aum": max_aum, "turnover": turnover, "daily": daily, "half_life": half_life,
                          "annual_cost_bps": annual_cost_bps, "cost_elasticity": cost_elasticity,
                          "calculation_mode": calculation_mode, "mc_samples": int(mc_samples), "mc_seed": int(mc_seed),
                          "minimum_ir": minimum_ir, "retained_threshold": retained_threshold,
                          "regulatory_aum": marker_value(regulatory_raw), "competition_aum": marker_value(competition_raw)}
            save_strategy(strategy_name, parameters, active_buckets,
                          active_adv_points,
                          ir_points=creator_ir_points, trades=active_trades)
        except (OSError, KeyError, TypeError, ValueError) as error:
            st.error(f"Strategy was not saved: {error}")
        else:
            name = strategy_name.strip()
            for key in list(st.session_state):
                if str(key).startswith(f"execution::{name}::"):
                    del st.session_state[key]
            st.session_state["pending_strategy"] = name
            st.session_state["strategy_saved_message"] = f"Saved and loaded {name}."
            st.rerun()
