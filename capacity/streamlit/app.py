"""Streamlit version of the Capacity Lab dashboard."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from capacity_model import (
    LIVE, AdvEngine, BurrEngine, Scenario,
    burr_shares, calibrate_orders, curve,
)
from strategy_store import (
    ADV_COLUMNS, BUCKET_COLUMNS, DEFAULT_PARAMETERS, default_strategy, load_strategies, save_strategy,
)


GREEN, AMBER, RUST, BLUE = "#42c7a5", "#f4bd50", "#ef7658", "#76a9d0"
PALETTE = ["#b8f2e3", GREEN, AMBER, RUST, BLUE, "#c698db"]
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


@st.cache_data(show_spinner=False)
def orders(
    preference: float,
    buckets: pd.DataFrame,
    adv_points: pd.DataFrame,
    universe_size: int,
) -> pd.DataFrame:
    return calibrate_orders(preference, buckets, adv_points, universe_size)


def style_figure(fig: go.Figure) -> go.Figure:
    """Apply a high-contrast dark theme consistently to every Plotly chart."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=PAGE_BG,
        plot_bgcolor=PANEL_BG,
        font_color=TEXT,
        title_font_color=TEXT,
        legend_bgcolor="rgba(17,17,17,0.85)",
        hoverlabel=dict(bgcolor="#1a1d1b", font_color=TEXT),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor="#555b58")
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor="#555b58")
    return fig


def add_aum_markers(fig: go.Figure, markers: list[dict[str, float | str]], max_aum: float) -> go.Figure:
    """Add optional external AUM reference lines without changing the chart range."""
    positions = ["top left", "top right"]
    for index, marker in enumerate(markers):
        value = float(marker["value"])
        if 0.1 <= value <= max_aum:
            fig.add_vline(
                x=value,
                line_width=2,
                line_dash=str(marker["dash"]),
                line_color=str(marker["color"]),
                annotation_text=f"{marker['label']} · ${value:g}bn",
                annotation_position=positions[index % len(positions)],
                annotation_font_color=str(marker["color"]),
                annotation_bgcolor="rgba(5,5,5,0.82)",
                annotation_borderpad=4,
            )
    return fig


def migration_chart(values: dict[str, np.ndarray], title: str):
    rows = [{"Participation bucket": bucket, "Scenario": name, "Share (%)": share}
            for name, shares in values.items() for bucket, share in zip(migration_labels, shares)]
    fig = px.bar(pd.DataFrame(rows), x="Participation bucket", y="Share (%)", color="Scenario", barmode="group", title=title, color_discrete_sequence=PALETTE)
    fig.update_layout(legend_orientation="h", legend_y=1.12)
    st.plotly_chart(style_figure(fig), width="stretch")


try:
    strategies = load_strategies()
    strategy_load_error = None
except (OSError, ValueError) as error:
    strategies = {"Swiss Strategy": default_strategy()}
    strategy_load_error = str(error)

pending_strategy = st.session_state.pop("pending_strategy", None)
strategy_saved_message = st.session_state.pop("strategy_saved_message", None)
if pending_strategy in strategies:
    st.session_state["selected_strategy"] = pending_strategy
    st.session_state["creator_base_strategy"] = pending_strategy

with st.sidebar:
    st.title("Capacity Lab")
    st.caption("Long-only equity model · USD")
    selected_strategy_name = st.selectbox(
        "Saved strategy",
        list(strategies),
        key="selected_strategy",
        help="Create and save additional cases in the Strategy creator tab.",
    )
    if strategy_load_error:
        st.warning(f"Saved strategies could not be loaded: {strategy_load_error}")
    if strategy_saved_message:
        st.success(strategy_saved_message)

selected_strategy = strategies[selected_strategy_name]
saved = {**DEFAULT_PARAMETERS, **selected_strategy["parameters"]}
strategy_buckets = pd.DataFrame(selected_strategy["buckets"])[BUCKET_COLUMNS].copy()
strategy_adv_points = pd.DataFrame(selected_strategy["adv_points"])[ADV_COLUMNS].copy()
migration_labels = [*strategy_buckets["label"].astype(str).tolist(), ">100%"]
main_key = f"main::{selected_strategy_name}::"

with st.sidebar:
    engine_options = ["ADV-calibrated migration", "Burr migration"]
    engine_name = st.selectbox(
        "Migration model",
        engine_options,
        index=engine_options.index(saved["engine_name"]),
        key=main_key + "engine",
    )
    st.subheader("Strategy")
    aum0 = st.number_input("Current AUM ($bn)", 0.1, 1000.0, float(saved["aum0"]), .1, key=main_key + "aum0")
    gross_alpha = st.number_input("Gross alpha (%)", 0.0, 100.0, float(saved["gross_alpha"]), .05, key=main_key + "gross_alpha")
    tracking_error = st.number_input("Tracking error (%)", .01, 100.0, float(saved["tracking_error"]), .1, key=main_key + "tracking_error")
    turnover = st.number_input("One-way turnover (%)", 0.0, 1000.0, float(saved["turnover"]), .1, key=main_key + "turnover")
    universe_size = st.number_input(
        "Trading-universe size",
        2, 100000, int(saved["universe_size"]), 1,
        key=main_key + "universe_size",
        help="Number of eligible stocks represented by the ADV percentile distribution.",
    )
    holdings_key = main_key + "holdings"
    if holdings_key in st.session_state and int(st.session_state[holdings_key]) > int(universe_size):
        st.session_state[holdings_key] = int(universe_size)
    holdings_initial = {} if holdings_key in st.session_state else {
        "value": min(int(saved["holdings"]), int(universe_size)),
    }
    holdings = st.number_input(
        "Average holdings", min_value=1, max_value=int(universe_size), step=1,
        key=holdings_key, **holdings_initial,
    )
    max_aum = st.number_input("Chart horizon ($bn)", 1.0, 1000.0, float(saved["max_aum"]), 1.0, key=main_key + "max_aum")
    st.subheader("Migration and execution")
    daily = st.number_input("Daily participation (% ADV)", .1, 100.0, float(saved["daily"]), .5, key=main_key + "daily")
    max_days = st.number_input("Maximum execution days", 1, 252, int(saved["max_days"]), 1, key=main_key + "max_days")
    half_life = st.number_input("Alpha half-life (days)", .1, 1260.0, float(saved["half_life"]), 1.0, key=main_key + "half_life")
    adv_volume = st.number_input("Market ADV level (%)", 1.0, 300.0, float(saved["adv_volume"]), 5.0, disabled=engine_name.startswith("Burr"), key=main_key + "adv_volume")
    preference_options = ["Neutral prior", "Favour liquid stocks", "Favour illiquid stocks"]
    preference_label = st.selectbox(
        "Liquidity preference",
        preference_options,
        index=preference_options.index(saved["preference_label"]),
        disabled=engine_name.startswith("Burr"),
        key=main_key + "preference",
    )
    preference = {"Neutral prior": 0.0, "Favour liquid stocks": 2.0, "Favour illiquid stocks": -2.0}[preference_label]
    eta = st.number_input("η · Scale elasticity", 0.0, 2.0, float(saved["eta"]), .05, disabled=engine_name.startswith("ADV"), key=main_key + "eta")
    kappa = st.number_input("κ · Tail thickening", 0.0, 2.0, float(saved["kappa"]), .05, disabled=engine_name.startswith("ADV"), key=main_key + "kappa")
    st.subheader("Decision thresholds")
    minimum_ir = st.number_input("Minimum net IR", 0.0, 10.0, float(saved["minimum_ir"]), .05, key=main_key + "minimum_ir")
    retained_threshold = st.number_input("Minimum retained alpha (%)", 0.0, 100.0, float(saved["retained_threshold"]), 1.0, key=main_key + "retained_threshold")
    st.subheader("Display markers")
    regulatory_raw = st.text_input(
        "Implied regulatory AUM ($bn)",
        value="" if saved["regulatory_aum"] is None else str(saved["regulatory_aum"]),
        placeholder="Not set",
        key=main_key + "regulatory_aum",
    )
    competition_raw = st.text_input(
        "Median competition AUM ($bn)",
        value="" if saved["competition_aum"] is None else str(saved["competition_aum"]),
        placeholder="Not set",
        key=main_key + "competition_aum",
    )
    st.caption("Optional reference lines on both Overview charts. Enter values in USD billions.")


def parse_marker(raw: str, label: str, color: str, dash: str) -> tuple[dict[str, float | str] | None, str | None]:
    if not raw.strip():
        return None, None
    try:
        value = float(raw)
    except ValueError:
        return None, f"{label} must be a positive number."
    if not np.isfinite(value) or value <= 0:
        return None, f"{label} must be a positive number."
    return {"label": label, "value": value, "color": color, "dash": dash}, None


regulatory_marker, regulatory_error = parse_marker(regulatory_raw, "Implied regulatory AUM", BLUE, "dash")
competition_marker, competition_error = parse_marker(competition_raw, "Median competition", "#c698db", "dot")
aum_markers = [marker for marker in (regulatory_marker, competition_marker) if marker is not None]
for marker_error in (regulatory_error, competition_error):
    if marker_error:
        st.sidebar.warning(marker_error)
outside_markers = [marker for marker in aum_markers if float(marker["value"]) > max_aum]
if outside_markers:
    st.sidebar.info(
        "Outside chart horizon: "
        + ", ".join(f"{marker['label']} (${float(marker['value']):g}bn)" for marker in outside_markers)
    )

scenario = Scenario(aum0=aum0, gross_alpha=gross_alpha, tracking_error=tracking_error,
                    turnover=turnover, holdings=int(holdings), universe_size=int(universe_size), scale_elasticity=eta,
                    tail_elasticity=kappa, daily_participation=daily, max_days=int(max_days),
                    half_life=half_life, adv_volume=adv_volume,
                    burr_c=float(saved["burr_c"]), burr_d=float(saved["burr_d"]),
                    burr_scale=float(saved["burr_scale"]), impact_a=float(saved["impact_a"]),
                    impact_b=float(saved["impact_b"]), impact_gamma=float(saved["impact_gamma"]))
selected_orders = orders(preference, strategy_buckets, strategy_adv_points, int(universe_size))
engine = (AdvEngine(
              scenario, selected_orders, strategy_buckets,
              anchor_aum=float(saved["aum0"]), anchor_holdings=int(saved["holdings"]),
          )
          if engine_name.startswith("ADV") else BurrEngine(scenario, strategy_buckets))
data = curve(engine, max_aum)
base, twice, four = [engine.metric(aum0 * x) for x in (1, 2, 4)]

st.title("Capacity Analysis")
st.caption("Distributional liquidity migration, execution horizons, market impact and alpha decay")
overview, liquidity, demo, inputs, creator = st.tabs([
    "Overview", "Liquidity migration", "Demo building blocks", "Input data", "Strategy creator",
])

with overview:
    cols = st.columns(3)
    cols[0].metric("Current net IR", f"{base['Net IR']:.2f}", "Above threshold" if base["Net IR"] >= minimum_ir else "Below threshold")
    crossing = data.loc[data["Net IR"] <= minimum_ir, "AUM"]
    cols[1].metric(
        "AUM at minimum net IR",
        f"${crossing.iloc[0]:.1f}bn" if len(crossing) else f"> ${max_aum:.0f}bn",
        f"Minimum net IR = {minimum_ir:.2f}",
        delta_color="off",
        help="First AUM on the scenario curve where net information ratio reaches or falls below the selected minimum.",
    )
    cols[2].metric("Alpha capture at current AUM", f"{base['Alpha capture (%)']:.1f}%")
    cols = st.columns(3)
    cols[0].metric(
        "Average execution at current AUM",
        f"{base['Average days']:.2f} days",
        help="Count-weighted fractional completion time: parent-order participation divided by the daily ADV participation rate.",
    )
    cols[1].metric(
        "Average weighted trade size",
        f"{base['Mean participation (%)']:.2f}% ADV",
        help="Intended-notional-weighted parent-order participation at the current AUM.",
    )
    cols[2].metric(
        "Average theoretical impact cost",
        f"{base['Impact (bp)']:.2f} bp",
        help="Modeled theoretical impact averaged across intended traded notional at the current AUM.",
    )
    fig = px.line(data, x="AUM", y="Net IR", title="Net information ratio", color_discrete_sequence=[GREEN])
    fig.add_hline(y=minimum_ir, line_dash="dash", line_color=RUST)
    add_aum_markers(fig, aum_markers, max_aum)
    fig.update_layout(yaxis_title="Net IR", xaxis_title="AUM (USD bn)")
    st.plotly_chart(style_figure(fig), width="stretch")
    alpha = data.melt(id_vars="AUM", value_vars=["After delay (%)", "Net alpha (%)"], var_name="Series", value_name="Alpha (%)")
    fig = px.line(alpha, x="AUM", y="Alpha (%)", color="Series", title="Alpha decomposition", color_discrete_sequence=[AMBER, RUST])
    add_aum_markers(fig, aum_markers, max_aum)
    fig.update_layout(xaxis_title="AUM (USD bn)")
    st.plotly_chart(style_figure(fig), width="stretch")
    fig = go.Figure()
    fig.add_scatter(
        x=data["AUM"], y=data["Impact (bp)"], mode="lines",
        name="Average theoretical impact cost", line=dict(color=AMBER, width=3),
        hovertemplate="AUM: $%{x:.2f}bn<br>Impact: %{y:.2f} bp<extra></extra>",
    )
    fig.add_scatter(
        x=data["AUM"], y=data["Mean participation (%)"], mode="lines", yaxis="y2",
        name="Average weighted trade size", line=dict(color=BLUE, width=3),
        hovertemplate="AUM: $%{x:.2f}bn<br>Trade size: %{y:.2f}% ADV<extra></extra>",
    )
    fig.update_layout(
        title="Theoretical impact cost and weighted trade size",
        xaxis_title="AUM (USD bn)",
        yaxis=dict(title="Average weighted theoretical impact cost (bp)"),
        yaxis2=dict(
            title="Average weighted trade size (% ADV)",
            overlaying="y", side="right", showgrid=False,
        ),
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(style_figure(fig), width="stretch")
    scenario_table = pd.DataFrame([base, twice, four]).rename(
        columns={"Average days": "Avg execution (days)"},
    )
    st.dataframe(scenario_table.round(3), width="stretch", hide_index=True)
    retained_cross = data.loc[data["Retained alpha (%)"] <= retained_threshold, "AUM"]
    if len(retained_cross):
        st.info(f"Retained alpha falls through {retained_threshold:.0f}% near ${retained_cross.iloc[0]:.1f}bn.")
    else:
        st.info(f"Retained alpha stays above {retained_threshold:.0f}% through ${max_aum:.0f}bn.")

with liquidity:
    aums = [aum0, aum0 * 2, aum0 * 4]
    labels = [f"${x:.1f}bn" for x in aums]
    view = st.radio("View", ["Traded-dollar migration", "Parent-order count migration", "Execution outcomes"], horizontal=True)
    if view == "Traded-dollar migration":
        migration_chart({label: engine.dollar_shares(aum) for label, aum in zip(labels, aums)}, view)
    elif view == "Parent-order count migration":
        if isinstance(engine, AdvEngine):
            migration_chart({label: engine.count_shares(aum) for label, aum in zip(labels, aums)}, view)
        else:
            migration_chart({label: burr_shares(aum, scenario, count_fit=True, buckets=strategy_buckets) for label, aum in zip(labels, aums)}, "Count-calibrated Burr migration")
    else:
        if isinstance(engine, AdvEngine):
            outcome_labels = ["Completed in 1 day", "Completed in 2–5 days", "Completed in 6+ days", "Beyond maximum horizon"]
            rows = [{"Execution outcome": outcome, "Scenario": label, "Parent orders (%)": share}
                    for label, aum in zip(labels, aums) for outcome, share in zip(outcome_labels, engine.execution_shares(aum))]
            fig = px.bar(pd.DataFrame(rows), x="Execution outcome", y="Parent orders (%)", color="Scenario", barmode="group", color_discrete_sequence=PALETTE)
            st.plotly_chart(style_figure(fig), width="stretch")
        else:
            st.info("Execution-outcome counts require the ADV-calibrated parent-order engine.")
    st.caption("Participation buckets are defined by total parent-order value divided by ADV. Daily participation changes execution outcomes, not the parent-order bucket.")

with demo:
    migration_demo, impact_demo, alpha_demo = st.tabs(["1. Liquidity migration", "2. Impact model", "3. Alpha decay"])
    with migration_demo:
        aum_calibrated_demo, burr_count_demo = st.tabs(["AUM-calibrated migration", "Count-calibrated Burr"])
        with aum_calibrated_demo:
            st.subheader("AUM-calibrated liquidity migration")
            st.write(
                "Compare two portfolio sizes using the observed parent-order buckets and the one-year "
                "ADV distribution. These controls are independent of the main capacity case."
            )
            c1, c2 = st.columns(2)
            demo_aum_1 = c1.number_input("AUM 1 ($bn)", .01, 1000.0, float(aum0), .1, key="demo_aum_1")
            demo_aum_2 = c2.number_input("AUM 2 ($bn)", .01, 1000.0, float(aum0 * 2), .1, key="demo_aum_2")
            c1, c2, c3 = st.columns(3)
            if "demo_aum_holdings" in st.session_state and int(st.session_state["demo_aum_holdings"]) > int(universe_size):
                st.session_state["demo_aum_holdings"] = int(universe_size)
            demo_holdings_initial = {} if "demo_aum_holdings" in st.session_state else {"value": int(holdings)}
            demo_holdings = c1.number_input(
                "Average holdings", min_value=1, max_value=int(universe_size), step=1,
                key="demo_aum_holdings", **demo_holdings_initial,
            )
            demo_adv_volume = c2.number_input("Market ADV level (%)", 1.0, 300.0, 100.0, 5.0, key="demo_aum_adv")
            demo_preference_label = c3.selectbox(
                "Liquidity preference",
                ["Neutral prior", "Favour liquid stocks", "Favour illiquid stocks"],
                key="demo_aum_preference",
            )
            demo_preference = {
                "Neutral prior": 0.0,
                "Favour liquid stocks": 2.0,
                "Favour illiquid stocks": -2.0,
            }[demo_preference_label]
            demo_scenario = replace(
                scenario,
                holdings=int(demo_holdings),
                universe_size=int(universe_size),
                adv_volume=float(demo_adv_volume),
            )
            demo_engine = AdvEngine(
                demo_scenario,
                orders(demo_preference, strategy_buckets, strategy_adv_points, int(universe_size)),
                strategy_buckets,
                anchor_aum=float(saved["aum0"]),
                anchor_holdings=int(saved["holdings"]),
            )
            demo_aums = [float(demo_aum_1), float(demo_aum_2)]
            demo_labels = [f"AUM {index + 1} · ${value:.2f}bn" for index, value in enumerate(demo_aums)]
            migration_chart(
                {label: demo_engine.dollar_shares(value) for label, value in zip(demo_labels, demo_aums)},
                "Traded-dollar migration",
            )
            migration_chart(
                {label: demo_engine.count_shares(value) for label, value in zip(demo_labels, demo_aums)},
                "Parent-order count migration",
            )
            dollar_sets = [demo_engine.dollar_shares(value) for value in demo_aums]
            count_sets = [demo_engine.count_shares(value) for value in demo_aums]
            comparison = pd.DataFrame({
                "Participation bucket": migration_labels,
                f"AUM 1 · dollars (%)": dollar_sets[0],
                f"AUM 2 · dollars (%)": dollar_sets[1],
                f"AUM 1 · orders (%)": count_sets[0],
                f"AUM 2 · orders (%)": count_sets[1],
            })
            st.dataframe(comparison.round(2), width="stretch", hide_index=True)
            st.caption(
                "Parent-order size scales with AUM and inversely with holdings. Market ADV and the "
                "liquidity preference determine where those orders fall in the participation buckets."
            )
        with burr_count_demo:
            st.subheader("Count-calibrated Burr migration")
            c1, c2 = st.columns(2)
            demo_eta = c1.slider("η · Scale elasticity", 0.0, 2.0, float(LIVE["countCalibration"]["scaleElasticity"]), .05)
            demo_kappa = c2.slider("κ · Tail thickening", 0.0, 2.0, float(LIVE["countCalibration"]["tailElasticity"]), .05)
            migration_chart({label: burr_shares(aum, scenario, count_fit=True, eta=demo_eta, kappa=demo_kappa, buckets=strategy_buckets) for label, aum in zip(labels, aums)}, "Parent-order count migration")
            fit = LIVE["countCalibration"]
            st.caption(f"Count fit: c={fit['burrC']:.3f}, d={fit['burrD']:.3f}, λ₀={fit['burrScale']:.4f}; joint RMSE={fit['rmsePercentagePoints']:.2f} percentage points.")
    with impact_demo:
        st.subheader("Impact model")
        c1, c2, c3 = st.columns(3)
        a = c1.number_input("a", value=float(scenario.impact_a), format="%.4f")
        b = c2.number_input("b", value=float(scenario.impact_b), format="%.4f")
        gamma = c3.number_input("γ", value=float(scenario.impact_gamma), min_value=.01, max_value=3.0, step=.05)
        p = np.linspace(0, 1, 201)
        fig = go.Figure()
        fig.add_scatter(x=p * 100, y=a + b * p ** gamma, mode="lines", name="Fitted impact", line_color=GREEN)
        fig.add_scatter(x=strategy_buckets.p * 100, y=strategy_buckets.cost, mode="markers", name="Expected buckets", marker_color=AMBER, marker_size=10)
        fig.add_scatter(x=strategy_buckets.p * 100, y=strategy_buckets.realised, mode="markers", name="Realised buckets", marker_color=RUST, marker_size=10)
        fig.update_layout(xaxis_title="Participation (% ADV)", yaxis_title="Impact (bp)")
        st.plotly_chart(style_figure(fig), width="stretch")
        st.latex(r"c(p)=a+b p^{\gamma}")
    with alpha_demo:
        st.subheader("Alpha decay over six months")
        st.info(
            "Alpha decay is applied to each parent order before portfolio aggregation. One-day "
            "orders have full delay capture; multi-day orders and unfinished notional reduce "
            "captured gross alpha. The model then subtracts impact costs and divides net alpha "
            "by tracking error to obtain net IR. Capture is normalized to the current-AUM case."
        )
        h = st.slider("Half-life (days)", 1, 126, int(round(half_life)))
        days = np.arange(127)
        alpha = pd.DataFrame({"Day": days, "Remaining gross alpha (%)": gross_alpha * 2 ** (-days / h)})
        fig = px.line(alpha, x="Day", y="Remaining gross alpha (%)", color_discrete_sequence=[GREEN])
        st.plotly_chart(style_figure(fig), width="stretch")
        st.latex(r"R_g(t)=R_g(0)\,2^{-t/H_{\alpha}}")

with inputs:
    st.subheader("Liquidity calibration inputs")
    st.caption(f"Active strategy: {selected_strategy_name}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Trading-universe size", f"{int(universe_size):,} stocks")
    c2.metric("Average holdings", f"{int(holdings):,}")
    c3.metric("Universe coverage", f"{100 * int(holdings) / int(universe_size):.1f}%")
    display = strategy_buckets.rename(columns={"label": "Participation bucket", "trades": "Parent orders", "valueUsdMillion": "Value (USD m)", "share": "Notional share (%)", "cost": "Expected impact (bp)", "realised": "Realised impact (bp)"})
    st.dataframe(display[["Participation bucket", "Parent orders", "Value (USD m)", "Notional share (%)", "Expected impact (bp)", "Realised impact (bp)"]], width="stretch", hide_index=True)
    st.subheader("Trading-universe ADV distribution")
    st.caption(
        f"The percentile curve represents {int(universe_size):,} eligible stocks; the calibration "
        "uses a finite stock-count grid (up to 1,000 points)."
    )
    adv_display = strategy_adv_points.rename(columns={"percentile": "Percentile", "advUsd": "ADV (USD)"})
    st.dataframe(adv_display, width="stretch", hide_index=True)

with creator:
    st.subheader("Strategy creator")
    st.write(
        "Create or update a complete strategy case in one place. A saved strategy contains the "
        "Capacity Lab defaults, liquidity buckets, and the trading-universe ADV distribution."
    )
    creator_base_name = st.selectbox(
        "Start from strategy",
        list(strategies),
        index=list(strategies).index(selected_strategy_name),
        key="creator_base_strategy",
    )
    creator_base = strategies[creator_base_name]
    creator_defaults = {**DEFAULT_PARAMETERS, **creator_base["parameters"]}
    creator_key = f"creator::{creator_base_name}::"

    with st.form("strategy_creator_form::" + creator_base_name):
        strategy_name = st.text_input(
            "Strategy name",
            value=creator_base_name,
            key=creator_key + "name",
            help="Use a new name to create a copy, or keep the current name to update it.",
        )
        creator_engine = st.selectbox(
            "Default migration model",
            engine_options,
            index=engine_options.index(creator_defaults["engine_name"]),
            key=creator_key + "engine",
        )

        st.markdown("#### Capacity Lab defaults")
        c1, c2, c3 = st.columns(3)
        creator_aum0 = c1.number_input("Current AUM ($bn)", .1, 1000.0, float(creator_defaults["aum0"]), .1, key=creator_key + "aum0")
        creator_alpha = c2.number_input("Gross alpha (%)", 0.0, 100.0, float(creator_defaults["gross_alpha"]), .05, key=creator_key + "gross_alpha")
        creator_te = c3.number_input("Tracking error (%)", .01, 100.0, float(creator_defaults["tracking_error"]), .1, key=creator_key + "tracking_error")
        c1, c2, c3, c4 = st.columns(4)
        creator_turnover = c1.number_input("One-way turnover (%)", 0.0, 1000.0, float(creator_defaults["turnover"]), .1, key=creator_key + "turnover")
        creator_universe = c2.number_input("Trading-universe size", 2, 100000, int(creator_defaults["universe_size"]), 1, key=creator_key + "universe_size")
        creator_holdings_key = creator_key + "holdings"
        if creator_holdings_key in st.session_state and int(st.session_state[creator_holdings_key]) > int(creator_universe):
            st.session_state[creator_holdings_key] = int(creator_universe)
        creator_holdings_initial = {} if creator_holdings_key in st.session_state else {
            "value": min(int(creator_defaults["holdings"]), int(creator_universe)),
        }
        creator_holdings = c3.number_input(
            "Average holdings", min_value=1, max_value=int(creator_universe), step=1,
            key=creator_holdings_key, **creator_holdings_initial,
        )
        creator_horizon = c4.number_input("Chart horizon ($bn)", 1.0, 1000.0, float(creator_defaults["max_aum"]), 1.0, key=creator_key + "max_aum")

        st.markdown("#### Migration, execution, and decisions")
        c1, c2, c3 = st.columns(3)
        creator_daily = c1.number_input("Daily participation (% ADV)", .1, 100.0, float(creator_defaults["daily"]), .5, key=creator_key + "daily")
        creator_max_days = c2.number_input("Maximum execution days", 1, 252, int(creator_defaults["max_days"]), 1, key=creator_key + "max_days")
        creator_half_life = c3.number_input("Alpha half-life (days)", .1, 1260.0, float(creator_defaults["half_life"]), 1.0, key=creator_key + "half_life")
        c1, c2, c3 = st.columns(3)
        creator_adv_volume = c1.number_input("Market ADV level (%)", 1.0, 300.0, float(creator_defaults["adv_volume"]), 5.0, key=creator_key + "adv_volume")
        creator_preference = c2.selectbox(
            "Liquidity preference",
            preference_options,
            index=preference_options.index(creator_defaults["preference_label"]),
            key=creator_key + "preference",
        )
        creator_eta = c3.number_input("η · Scale elasticity", 0.0, 2.0, float(creator_defaults["eta"]), .05, key=creator_key + "eta")
        c1, c2, c3 = st.columns(3)
        creator_kappa = c1.number_input("κ · Tail thickening", 0.0, 2.0, float(creator_defaults["kappa"]), .05, key=creator_key + "kappa")
        creator_min_ir = c2.number_input("Minimum net IR", 0.0, 10.0, float(creator_defaults["minimum_ir"]), .05, key=creator_key + "minimum_ir")
        creator_retained = c3.number_input("Minimum retained alpha (%)", 0.0, 100.0, float(creator_defaults["retained_threshold"]), 1.0, key=creator_key + "retained_threshold")
        c1, c2 = st.columns(2)
        creator_regulatory = c1.text_input(
            "Implied regulatory AUM ($bn)",
            value="" if creator_defaults["regulatory_aum"] is None else str(creator_defaults["regulatory_aum"]),
            placeholder="Not set",
            key=creator_key + "regulatory_aum",
        )
        creator_competition = c2.text_input(
            "Median competition AUM ($bn)",
            value="" if creator_defaults["competition_aum"] is None else str(creator_defaults["competition_aum"]),
            placeholder="Not set",
            key=creator_key + "competition_aum",
        )

        with st.expander("Advanced Burr and impact defaults"):
            c1, c2, c3 = st.columns(3)
            creator_burr_c = c1.number_input("Burr shape c", .0001, 100.0, float(creator_defaults["burr_c"]), .01, format="%.4f", key=creator_key + "burr_c")
            creator_burr_d = c2.number_input("Burr shape d", .0001, 100.0, float(creator_defaults["burr_d"]), .01, format="%.4f", key=creator_key + "burr_d")
            creator_burr_scale = c3.number_input("Burr scale", .000001, 100.0, float(creator_defaults["burr_scale"]), .001, format="%.6f", key=creator_key + "burr_scale")
            c1, c2, c3 = st.columns(3)
            creator_impact_a = c1.number_input("Impact a", 0.0, 10000.0, float(creator_defaults["impact_a"]), .01, format="%.4f", key=creator_key + "impact_a")
            creator_impact_b = c2.number_input("Impact b", 0.0, 10000.0, float(creator_defaults["impact_b"]), .01, format="%.4f", key=creator_key + "impact_b")
            creator_impact_gamma = c3.number_input("Impact γ", .01, 10.0, float(creator_defaults["impact_gamma"]), .05, key=creator_key + "impact_gamma")

        st.markdown("#### Liquidity bucket data")
        st.caption("Parent-order counts and traded values should describe the same annual observation window.")
        creator_buckets = st.data_editor(
            pd.DataFrame(creator_base["buckets"])[BUCKET_COLUMNS],
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            key=creator_key + "buckets",
        )
        st.markdown("#### Trading-universe ADV distribution")
        st.caption("Enter increasing percentile boundaries and annual-lookback ADV values in USD.")
        creator_adv_points = st.data_editor(
            pd.DataFrame(creator_base["adv_points"])[ADV_COLUMNS],
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            key=creator_key + "adv_points",
        )
        save_clicked = st.form_submit_button("Save strategy", type="primary")

    if save_clicked:
        try:
            def optional_positive(raw: str, field: str) -> float | None:
                if not raw.strip():
                    return None
                value = float(raw)
                if not np.isfinite(value) or value <= 0:
                    raise ValueError(f"{field} must be a positive number or left blank.")
                return value

            creator_parameters = {
                "engine_name": creator_engine,
                "aum0": float(creator_aum0),
                "gross_alpha": float(creator_alpha),
                "tracking_error": float(creator_te),
                "turnover": float(creator_turnover),
                "holdings": int(creator_holdings),
                "universe_size": int(creator_universe),
                "max_aum": float(creator_horizon),
                "daily": float(creator_daily),
                "max_days": int(creator_max_days),
                "half_life": float(creator_half_life),
                "adv_volume": float(creator_adv_volume),
                "preference_label": creator_preference,
                "eta": float(creator_eta),
                "kappa": float(creator_kappa),
                "minimum_ir": float(creator_min_ir),
                "retained_threshold": float(creator_retained),
                "regulatory_aum": optional_positive(creator_regulatory, "Implied regulatory AUM"),
                "competition_aum": optional_positive(creator_competition, "Median competition AUM"),
                "burr_c": float(creator_burr_c),
                "burr_d": float(creator_burr_d),
                "burr_scale": float(creator_burr_scale),
                "impact_a": float(creator_impact_a),
                "impact_b": float(creator_impact_b),
                "impact_gamma": float(creator_impact_gamma),
            }
            save_strategy(strategy_name, creator_parameters, creator_buckets, creator_adv_points)
        except (KeyError, OSError, TypeError, ValueError) as error:
            st.error(f"Strategy was not saved: {error}")
        else:
            clean_name = strategy_name.strip()
            for session_key in list(st.session_state):
                if str(session_key).startswith(f"main::{clean_name}::"):
                    del st.session_state[session_key]
            st.session_state["pending_strategy"] = clean_name
            st.session_state["strategy_saved_message"] = f"Saved and loaded {clean_name}."
            st.rerun()
