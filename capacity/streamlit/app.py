"""Streamlit version of the Capacity Lab dashboard."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from capacity_model import (
    ADV_POINTS, BUCKETS, LIVE, MIGRATION_LABELS, AdvEngine, BurrEngine, Scenario,
    burr_shares, calibrate_orders, curve,
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
def orders(preference: float) -> pd.DataFrame:
    return calibrate_orders(preference)


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
            for name, shares in values.items() for bucket, share in zip(MIGRATION_LABELS, shares)]
    fig = px.bar(pd.DataFrame(rows), x="Participation bucket", y="Share (%)", color="Scenario", barmode="group", title=title, color_discrete_sequence=PALETTE)
    fig.update_layout(legend_orientation="h", legend_y=1.12)
    st.plotly_chart(style_figure(fig), width="stretch")


with st.sidebar:
    st.title("Capacity Lab")
    st.caption("Long-only equity model · USD")
    engine_name = st.selectbox("Migration model", ["ADV-calibrated migration", "Burr migration"])
    st.subheader("Strategy")
    aum0 = st.number_input("Current AUM ($bn)", 0.1, 1000.0, 3.4, .1)
    gross_alpha = st.number_input("Gross alpha (%)", 0.0, 100.0, .5, .05)
    tracking_error = st.number_input("Tracking error (%)", .01, 100.0, 1.3, .1)
    turnover = st.number_input("One-way turnover (%)", 0.0, 1000.0, 13.9, .1)
    holdings = st.number_input("Average holdings", 1, 10000, 40, 1)
    max_aum = st.number_input("Chart horizon ($bn)", 1.0, 1000.0, 15.0, 1.0)
    st.subheader("Migration and execution")
    daily = st.number_input("Daily participation (% ADV)", .1, 100.0, 10.0, .5)
    max_days = st.number_input("Maximum execution days", 1, 252, 10, 1)
    half_life = st.number_input("Alpha half-life (days)", .1, 1260.0, 10.0, 1.0)
    adv_volume = st.number_input("Market ADV level (%)", 1.0, 300.0, 100.0, 5.0, disabled=engine_name.startswith("Burr"))
    preference_label = st.selectbox("Liquidity preference", ["Neutral prior", "Favour liquid stocks", "Favour illiquid stocks"], disabled=engine_name.startswith("Burr"))
    preference = {"Neutral prior": 0.0, "Favour liquid stocks": 2.0, "Favour illiquid stocks": -2.0}[preference_label]
    eta = st.number_input("η · Scale elasticity", 0.0, 2.0, .85, .05, disabled=engine_name.startswith("ADV"))
    kappa = st.number_input("κ · Tail thickening", 0.0, 2.0, 0.0, .05, disabled=engine_name.startswith("ADV"))
    st.subheader("Decision thresholds")
    minimum_ir = st.number_input("Minimum net IR", 0.0, 10.0, .4, .05)
    retained_threshold = st.number_input("Minimum retained alpha (%)", 0.0, 100.0, 80.0, 1.0)
    st.subheader("Display markers")
    regulatory_raw = st.text_input("Implied regulatory AUM ($bn)", placeholder="Not set")
    competition_raw = st.text_input("Median competition AUM ($bn)", placeholder="Not set")
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
                    turnover=turnover, holdings=int(holdings), scale_elasticity=eta,
                    tail_elasticity=kappa, daily_participation=daily, max_days=int(max_days),
                    half_life=half_life, adv_volume=adv_volume)
engine = AdvEngine(scenario, orders(preference)) if engine_name.startswith("ADV") else BurrEngine(scenario)
data = curve(engine, max_aum)
base, twice, four = [engine.metric(aum0 * x) for x in (1, 2, 4)]

st.title("Analysis strategy's AUM scenarios")
st.caption("Distributional liquidity migration, execution horizons, market impact and alpha decay")
overview, liquidity, demo, inputs = st.tabs(["Overview", "Liquidity migration", "Demo building blocks", "Input data"])

with overview:
    cols = st.columns(4)
    cols[0].metric("Current net IR", f"{base['Net IR']:.2f}", "Above threshold" if base["Net IR"] >= minimum_ir else "Below threshold")
    crossing = data.loc[data["Net IR"] <= minimum_ir, "AUM"]
    cols[1].metric("IR capacity", f"${crossing.iloc[0]:.1f}bn" if len(crossing) else f"> ${max_aum:.0f}bn")
    cols[2].metric("Alpha capture at 2×", f"{twice['Alpha capture (%)']:.1f}%")
    cols[3].metric("Average execution at 2×", f"{twice['Average days']:.1f} days")
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
    st.dataframe(pd.DataFrame([base, twice, four]).round(3), width="stretch", hide_index=True)
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
            migration_chart({label: burr_shares(aum, scenario, count_fit=True) for label, aum in zip(labels, aums)}, "Count-calibrated Burr migration")
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
            demo_holdings = c1.number_input("Average holdings", 1, 203, int(holdings), 1, key="demo_aum_holdings")
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
                adv_volume=float(demo_adv_volume),
            )
            demo_engine = AdvEngine(demo_scenario, orders(demo_preference))
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
                "Participation bucket": MIGRATION_LABELS,
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
            migration_chart({label: burr_shares(aum, scenario, count_fit=True, eta=demo_eta, kappa=demo_kappa) for label, aum in zip(labels, aums)}, "Parent-order count migration")
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
        fig.add_scatter(x=BUCKETS.p * 100, y=BUCKETS.cost, mode="markers", name="Expected buckets", marker_color=AMBER, marker_size=10)
        fig.add_scatter(x=BUCKETS.p * 100, y=BUCKETS.realised, mode="markers", name="Realised buckets", marker_color=RUST, marker_size=10)
        fig.update_layout(xaxis_title="Participation (% ADV)", yaxis_title="Impact (bp)")
        st.plotly_chart(style_figure(fig), width="stretch")
        st.latex(r"c(p)=a+b p^{\gamma}")
    with alpha_demo:
        st.subheader("Alpha decay over six months")
        h = st.slider("Half-life (days)", 1, 126, int(round(half_life)))
        days = np.arange(127)
        alpha = pd.DataFrame({"Day": days, "Remaining gross alpha (%)": gross_alpha * 2 ** (-days / h)})
        fig = px.line(alpha, x="Day", y="Remaining gross alpha (%)", color_discrete_sequence=[GREEN])
        st.plotly_chart(style_figure(fig), width="stretch")
        st.latex(r"R_g(t)=R_g(0)\,2^{-t/H_{\alpha}}")

with inputs:
    st.subheader("Liquidity calibration inputs")
    display = BUCKETS.rename(columns={"label": "Participation bucket", "trades": "Parent orders", "valueUsdMillion": "Value (USD m)", "share": "Notional share (%)", "cost": "Expected impact (bp)", "realised": "Realised impact (bp)"})
    st.dataframe(display[["Participation bucket", "Parent orders", "Value (USD m)", "Notional share (%)", "Expected impact (bp)", "Realised impact (bp)"]], width="stretch", hide_index=True)
    st.subheader("Trading-universe ADV distribution")
    adv_display = ADV_POINTS.rename(columns={"percentile": "Percentile", "advUsd": "ADV (USD)"})
    st.dataframe(adv_display, width="stretch", hide_index=True)
