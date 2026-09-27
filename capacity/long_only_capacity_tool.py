"""Distributional long-only equity capacity model.

The model combines four mechanisms:

1. a smooth market-impact curve fitted to observed ADV buckets;
2. a continuous Burr XII distribution for parent-order participation;
3. an AUM-dependent scale and optional tail-shape change in that distribution;
4. execution-horizon choice and exponential alpha decay.

Conventions
-----------
- turnover is ONE-WAY annual turnover, T;
- executed notional (buys + sells) is approximately 2*T*AUM;
- impact is in basis points per executed notional;
- current gross alpha is normalized after the current execution schedule;
- bucket shares are treated as shares of executed notional, not trade counts.

This remains a transparent toy model. Production calibration should use
trade-level parent orders, realised execution horizons and signal-decay data.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import brentq, curve_fit, least_squares
from scipy.stats import burr12


OUT = Path(__file__).resolve().parent

# -----------------------------------------------------------------------------
# 1) Strategy and implementation assumptions
# -----------------------------------------------------------------------------
AUM0_BN = 5.0
GROSS_ALPHA = 0.040
TRACKING_ERROR = 0.040
TURNOVER_1W = 0.80
N_HOLDINGS = 100

# Distributional migration assumptions.
# scale(A) = scale(A0) * (A/A0)^PARTICIPATION_SCALE_ELASTICITY
# An elasticity below one allows execution/portfolio adaptation to damp the
# mechanical increase in participation. Set it to one for proportional scaling.
PARTICIPATION_SCALE_ELASTICITY = 0.85

# Positive values make the upper tail heavier as AUM increases by reducing the
# second Burr shape parameter. Keep at zero unless data support composition drift.
TAIL_THICKENING_ELASTICITY = 0.00

# Execution and alpha-decay assumptions.
TARGET_DAILY_PARTICIPATION = 0.10  # 10% ADV per execution day
MAX_EXECUTION_DAYS = 10
ALPHA_HALF_LIFE_DAYS = 10.0
N_DISTRIBUTION_QUANTILES = 4000


def load_live_buckets(path: Path) -> pd.DataFrame:
    """Read the Numbers CSV export; preserve reported notional weights.

    Source impacts are signed return contributions. Negating them gives the
    positive cost convention used by this model (not an absolute-value transform).
    Bucket midpoints proxy participation because order-level values are absent.
    """
    source = pd.read_csv(path, skiprows=2)
    source = source[source["Median daily volume bucket"].notna()].copy()
    edges = source["Median daily volume bucket"].str.extract(
        r"^\s*(\d+(?:\.\d+)?)%\s*-\s*(\d+(?:\.\d+)?)%\s*$"
    ).astype(float) / 100
    result = pd.DataFrame({
        "bucket": source["Median daily volume bucket"].str.replace("% - ", "-", regex=False),
        "lower": edges[0],
        "upper": edges[1],
        "p_adv": edges.mean(axis=1),
        "trades": pd.to_numeric(source["Trades"]),
        "value_usd_million": pd.to_numeric(source["Value (millon USD)"]),
        "notional_share": source["% weight value"].str.rstrip("%").astype(float) / 100,
        "expected_bp": -pd.to_numeric(source["Estimated Impact cost (bps)"]),
        "realised_bp": -pd.to_numeric(source["Realised Total Impact cost (bps)"]),
    }).reset_index(drop=True)
    if result.empty or not np.isfinite(result.select_dtypes("number")).all().all():
        raise ValueError("Live bucket data contains missing or invalid values")
    if (result["lower"] >= result["upper"]).any() or result["lower"].iloc[0] != 0:
        raise ValueError("Invalid participation bucket bounds")
    if not np.allclose(result["lower"].iloc[1:], result["upper"].iloc[:-1]):
        raise ValueError("Participation buckets must be contiguous and ordered")
    if (result["notional_share"] < 0).any() or not np.isclose(result["notional_share"].sum(), 1):
        raise ValueError("Notional shares must be nonnegative and sum to one")
    return result


buckets = load_live_buckets(OUT / "buckets_data_live.csv")
assert np.isclose(buckets["notional_share"].sum(), 1.0)

# Keep the unobserved upper tail in model projections, without inventing an
# observed impact or fitting a fabricated source row.
migration_buckets = pd.concat([
    buckets[["bucket", "lower", "upper"]],
    pd.DataFrame([{"bucket": ">100%", "lower": 1.0, "upper": np.inf}]),
], ignore_index=True)


# -----------------------------------------------------------------------------
# 2) Smooth impact curves
# -----------------------------------------------------------------------------
def impact_curve(p, a, b, gamma):
    """Impact in bp as a function of effective participation p."""
    return a + b * np.power(p, gamma)


def fit_impact_curve(df: pd.DataFrame, col: str = "expected_bp"):
    x = df["p_adv"].to_numpy(float)
    y = df[col].to_numpy(float)
    popt, _ = curve_fit(
        impact_curve,
        x,
        y,
        p0=(0.5, 45.0, 0.6),
        bounds=([0.0, 0.0, 0.10], [20.0, 500.0, 1.50]),
        maxfev=100000,
    )
    return popt


PARAM_EXPECTED = fit_impact_curve(buckets, "expected_bp")
PARAM_REALISED = fit_impact_curve(buckets, "realised_bp")


# -----------------------------------------------------------------------------
# 3) Continuous participation distribution and bucket migration
# -----------------------------------------------------------------------------
def fit_participation_distribution(df: pd.DataFrame):
    """Fit Burr XII parameters to cumulative notional shares at bucket edges.

    Burr XII has a flexible body and a Pareto-like upper tail:
        F(p) = 1 - [1 + (p / scale)^c]^-d.
    """
    finite = np.isfinite(df["upper"].to_numpy(float))
    edges = df.loc[finite, "upper"].to_numpy(float)
    targets = df.loc[finite, "notional_share"].cumsum().to_numpy(float)

    def residuals(log_params):
        # Parameterise the tail index directly. For Burr XII the survival tail
        # is proportional to p^(-c*d). Requiring c*d >= 1.25 gives a finite
        # mean while retaining the empirically common 1-to-2 heavy-tail range.
        c, tail_index, scale = np.exp(log_params)
        d = tail_index / c
        return burr12.cdf(edges, c, d, scale=scale) - targets

    result = least_squares(
        residuals,
        np.log([1.0, 1.50, 0.03]),
        bounds=(np.log([0.10, 1.25, 1e-4]), np.log([10.0, 20.0, 10.0])),
        max_nfev=100000,
    )
    if not result.success:
        raise RuntimeError(f"Burr XII calibration failed: {result.message}")
    c, tail_index, scale = np.exp(result.x)
    return c, tail_index / c, scale


BURR_C0, BURR_D0, BURR_SCALE0 = fit_participation_distribution(buckets)
QUANTILE_GRID = (np.arange(N_DISTRIBUTION_QUANTILES) + 0.5) / N_DISTRIBUTION_QUANTILES


def participation_parameters(aum_bn: float):
    """Return Burr XII parameters at a target AUM."""
    if aum_bn <= 0:
        raise ValueError("AUM must be positive")
    aum_ratio = aum_bn / AUM0_BN
    scale = BURR_SCALE0 * aum_ratio ** PARTICIPATION_SCALE_ELASTICITY
    d = BURR_D0 * aum_ratio ** (-TAIL_THICKENING_ELASTICITY)
    return BURR_C0, d, scale


def participation_cdf(p, aum_bn: float):
    c, d, scale = participation_parameters(aum_bn)
    return burr12.cdf(p, c, d, scale=scale)


def participation_samples(aum_bn: float):
    """Deterministic notional-weighted participation quantiles."""
    c, d, scale = participation_parameters(aum_bn)
    return burr12.ppf(QUANTILE_GRID, c, d, scale=scale)


def migrated_bucket_shares(aum_bn: float) -> pd.Series:
    """Smooth bucket shares implied by the fitted distribution at target AUM."""
    shares = []
    for row in migration_buckets.itertuples(index=False):
        lower_cdf = 0.0 if row.lower == 0 else participation_cdf(row.lower, aum_bn)
        upper_cdf = 1.0 if not np.isfinite(row.upper) else participation_cdf(row.upper, aum_bn)
        shares.append(float(upper_cdf - lower_cdf))
    return pd.Series(shares, index=migration_buckets["bucket"], dtype=float)


# -----------------------------------------------------------------------------
# 4) Execution horizon, alpha decay and impact
# -----------------------------------------------------------------------------
def execution_days(participation):
    """Execution days implied by a target daily participation rate."""
    days = np.ceil(np.asarray(participation) / TARGET_DAILY_PARTICIPATION)
    return np.clip(days, 1, MAX_EXECUTION_DAYS).astype(int)


def alpha_capture_factor(days, half_life_days: float = ALPHA_HALF_LIFE_DAYS):
    """Average exponential alpha remaining across equally sized daily slices."""
    if half_life_days <= 0:
        raise ValueError("Alpha half-life must be positive")
    days = np.asarray(days, dtype=float)
    decay = np.log(2.0) / half_life_days
    numerator = 1.0 - np.exp(-decay * days)
    denominator = days * (1.0 - np.exp(-decay))
    return numerator / denominator


BASE_PARTICIPATION = participation_samples(AUM0_BN)
BASE_EXECUTION_DAYS = execution_days(BASE_PARTICIPATION)
BASE_ALPHA_CAPTURE = alpha_capture_factor(BASE_EXECUTION_DAYS)


def distribution_state(aum_bn: float):
    participation = participation_samples(aum_bn)
    days = execution_days(participation)

    # Current observed impact already embeds the current implementation schedule.
    # This ratio changes effective daily intensity relative to that baseline.
    effective_participation = participation * BASE_EXECUTION_DAYS / days

    capture = alpha_capture_factor(days)
    relative_alpha_capture = capture / BASE_ALPHA_CAPTURE
    return participation, days, effective_participation, relative_alpha_capture


RAW_EXPECTED_IMPACT_BP = float(np.dot(buckets["notional_share"], buckets["expected_bp"]))
RAW_REALISED_IMPACT_BP = float(np.dot(buckets["notional_share"], buckets["realised_bp"]))
BASE_EXPECTED_MODEL_BP = float(np.mean(impact_curve(BASE_PARTICIPATION, *PARAM_EXPECTED)))
BASE_REALISED_MODEL_BP = float(np.mean(impact_curve(BASE_PARTICIPATION, *PARAM_REALISED)))
EXPECTED_IMPACT_CALIBRATION = RAW_EXPECTED_IMPACT_BP / BASE_EXPECTED_MODEL_BP
REALISED_IMPACT_CALIBRATION = RAW_REALISED_IMPACT_BP / BASE_REALISED_MODEL_BP


def weighted_impact_bp(aum_bn: float, realised: bool = False) -> float:
    _, _, effective_participation, _ = distribution_state(aum_bn)
    if realised:
        raw = np.mean(impact_curve(effective_participation, *PARAM_REALISED))
        return float(raw * REALISED_IMPACT_CALIBRATION)
    raw = np.mean(impact_curve(effective_participation, *PARAM_EXPECTED))
    return float(raw * EXPECTED_IMPACT_CALIBRATION)


def strategy_metrics(aum_bn: float) -> dict:
    participation, days, effective_participation, relative_capture = distribution_state(aum_bn)
    c_bp = float(
        np.mean(impact_curve(effective_participation, *PARAM_EXPECTED))
        * EXPECTED_IMPACT_CALIBRATION
    )
    drag = 2.0 * TURNOVER_1W * c_bp / 10000.0

    # In the toy model, alpha share is proportional to executed-notional share.
    alpha_capture = float(np.mean(relative_capture))
    implemented_gross_alpha = GROSS_ALPHA * alpha_capture
    net_alpha = implemented_gross_alpha - drag

    return {
        "aum_bn": aum_bn,
        "baseline_gross_alpha_pct": GROSS_ALPHA * 100.0,
        "alpha_capture_pct": alpha_capture * 100.0,
        "implemented_gross_alpha_pct": implemented_gross_alpha * 100.0,
        "weighted_impact_bp": c_bp,
        "annual_drag_bp": drag * 10000.0,
        "net_alpha_pct": net_alpha * 100.0,
        "gross_ir_after_delay": implemented_gross_alpha / TRACKING_ERROR,
        "net_ir": net_alpha / TRACKING_ERROR,
        "alpha_retained_pct": net_alpha / GROSS_ALPHA * 100.0,
        "average_execution_days": float(np.mean(days)),
        "share_multiday_pct": float(np.mean(days >= 2) * 100.0),
        "share_3plus_days_pct": float(np.mean(days >= 3) * 100.0),
        "mean_parent_participation_pct": float(np.mean(participation) * 100.0),
    }


# -----------------------------------------------------------------------------
# 5) Outputs and diagnostics
# -----------------------------------------------------------------------------
alpha_per_holding_slot = GROSS_ALPHA / N_HOLDINGS
position_replacements = TURNOVER_1W * N_HOLDINGS
portfolio_contribution_per_replacement = GROSS_ALPHA / position_replacements
alpha_per_capital_cycle = GROSS_ALPHA / TURNOVER_1W
average_holding_years = 1.0 / TURNOVER_1W

summary = pd.DataFrame([
    ["Gross relative return", GROSS_ALPHA * 100, "% p.a."],
    ["Tracking error", TRACKING_ERROR * 100, "% p.a."],
    ["One-way turnover", TURNOVER_1W * 100, "% p.a."],
    ["Average holdings", N_HOLDINGS, "count"],
    ["Alpha per holding slot", alpha_per_holding_slot * 10000, "bp p.a."],
    ["Portfolio contribution/replacement", portfolio_contribution_per_replacement * 10000, "bp"],
    ["Alpha per unit capital recycled", alpha_per_capital_cycle * 100, "% per cycle"],
    ["Approx. average holding period", average_holding_years, "years"],
    ["Participation scale elasticity", PARTICIPATION_SCALE_ELASTICITY, "x"],
    ["Tail-thickening elasticity", TAIL_THICKENING_ELASTICITY, "x"],
    ["Target daily participation", TARGET_DAILY_PARTICIPATION * 100, "% ADV"],
    ["Alpha half-life", ALPHA_HALF_LIFE_DAYS, "trading days"],
], columns=["Metric", "Value", "Unit"])
summary.to_csv(OUT / "toy_strategy_summary.csv", index=False)

distribution_fit = buckets[["bucket", "notional_share"]].copy()
distribution_fit["burr_fitted_share"] = migrated_bucket_shares(AUM0_BN).reindex(buckets["bucket"]).values
distribution_fit.to_csv(OUT / "toy_distribution_fit.csv", index=False)

scenario_aums = [5.0, 10.0, 20.0]
scenarios = pd.DataFrame([strategy_metrics(a) for a in scenario_aums])
scenarios.to_csv(OUT / "toy_aum_scenarios.csv", index=False)

migration = pd.DataFrame({
    "bucket": migration_buckets["bucket"],
    "share_5bn": migrated_bucket_shares(5.0).values,
    "share_10bn": migrated_bucket_shares(10.0).values,
    "share_20bn": migrated_bucket_shares(20.0).values,
})
migration.to_csv(OUT / "toy_bucket_migration.csv", index=False)

aum_grid = np.linspace(1.0, 100.0, 397)
curve = pd.DataFrame([strategy_metrics(a) for a in aum_grid])
curve.to_csv(OUT / "toy_capacity_curve.csv", index=False)


def exact_crossing(metric: str, threshold: float, direction: str = "below"):
    values = curve[metric].to_numpy(float)
    condition = values <= threshold if direction == "below" else values >= threshold
    indices = np.where(condition)[0]
    if len(indices) == 0:
        return None
    idx = int(indices[0])
    if idx == 0:
        return float(curve.iloc[0]["aum_bn"])
    left = float(curve.iloc[idx - 1]["aum_bn"])
    right = float(curve.iloc[idx]["aum_bn"])
    return float(brentq(lambda a: strategy_metrics(a)[metric] - threshold, left, right))


thresholds = {
    "AUM where net IR <= 0.75": exact_crossing("net_ir", 0.75),
    "AUM where alpha retained <= 80%": exact_crossing("alpha_retained_pct", 80.0),
    "AUM where annual impact drag >= 100 bp": exact_crossing("annual_drag_bp", 100.0, "above"),
    "AUM where alpha capture <= 95%": exact_crossing("alpha_capture_pct", 95.0),
}
pd.DataFrame(list(thresholds.items()), columns=["Threshold", "AUM_bn"]).to_csv(
    OUT / "toy_capacity_thresholds.csv", index=False
)


# -----------------------------------------------------------------------------
# 6) Figures
# -----------------------------------------------------------------------------
p_grid = np.geomspace(0.003, 3.0, 250)
plt.figure(figsize=(7.2, 4.4))
plt.scatter(buckets["p_adv"] * 100, buckets["expected_bp"], label="Expected bucket cost")
plt.plot(p_grid * 100, impact_curve(p_grid, *PARAM_EXPECTED), label="Fitted cost curve", linewidth=2)
plt.xscale("log")
plt.xlabel("Participation rate (% ADV, log scale)")
plt.ylabel("Expected impact (bp)")
plt.title("Smooth impact curve fitted to ADV buckets")
plt.legend()
plt.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(OUT / "fig_impact_curve_fit.pdf", bbox_inches="tight")
plt.savefig(OUT / "fig_impact_curve_fit.png", dpi=180, bbox_inches="tight")
plt.close()

plt.figure(figsize=(7.2, 4.4))
for aum in scenario_aums:
    plt.plot(
        p_grid * 100,
        participation_cdf(p_grid, aum) * 100,
        linewidth=2,
        label=f"£{aum:g}bn",
    )
plt.xscale("log")
plt.xlabel("Parent-order participation (% ADV, log scale)")
plt.ylabel("Cumulative executed-notional share (%)")
plt.title("AUM shifts the continuous participation distribution")
plt.legend()
plt.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(OUT / "fig_participation_distribution.pdf", bbox_inches="tight")
plt.savefig(OUT / "fig_participation_distribution.png", dpi=180, bbox_inches="tight")
plt.close()

x = np.arange(len(migration))
w = 0.25
plt.figure(figsize=(8.2, 4.6))
plt.bar(x - w, migration["share_5bn"] * 100, width=w, label="£5bn")
plt.bar(x, migration["share_10bn"] * 100, width=w, label="£10bn")
plt.bar(x + w, migration["share_20bn"] * 100, width=w, label="£20bn")
plt.xticks(x, migration["bucket"])
plt.ylabel("Share of annual traded notional (%)")
plt.xlabel("Parent-order participation bucket")
plt.title("Distributional migration into higher ADV buckets")
plt.legend()
plt.grid(axis="y", alpha=0.25)
plt.tight_layout()
plt.savefig(OUT / "fig_bucket_migration.pdf", bbox_inches="tight")
plt.savefig(OUT / "fig_bucket_migration.png", dpi=180, bbox_inches="tight")
plt.close()

plt.figure(figsize=(7.2, 4.4))
plt.plot(curve["aum_bn"], curve["weighted_impact_bp"], linewidth=2)
plt.xlabel("AUM (£bn)")
plt.ylabel("Expected impact (bp / executed notional)")
plt.title("Expected impact after execution-horizon adaptation")
plt.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(OUT / "fig_impact_vs_aum.pdf", bbox_inches="tight")
plt.savefig(OUT / "fig_impact_vs_aum.png", dpi=180, bbox_inches="tight")
plt.close()

plt.figure(figsize=(7.2, 4.4))
plt.plot(curve["aum_bn"], curve["baseline_gross_alpha_pct"], label="Gross alpha before delay", linewidth=2)
plt.plot(curve["aum_bn"], curve["implemented_gross_alpha_pct"], label="Gross alpha after delay", linewidth=2)
plt.plot(curve["aum_bn"], curve["net_alpha_pct"], label="Net alpha after impact", linewidth=2)
plt.xlabel("AUM (£bn)")
plt.ylabel("Annualised relative return (%)")
plt.title("Capacity with execution delay and alpha decay")
plt.legend()
plt.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(OUT / "fig_alpha_vs_aum.pdf", bbox_inches="tight")
plt.savefig(OUT / "fig_alpha_vs_aum.png", dpi=180, bbox_inches="tight")
plt.close()

plt.figure(figsize=(7.2, 4.4))
plt.plot(curve["aum_bn"], curve["net_ir"], label="Net IR", linewidth=2)
plt.axhline(0.75, linestyle="--", linewidth=1.2, label="Illustrative threshold = 0.75")
plt.xlabel("AUM (£bn)")
plt.ylabel("Information ratio")
plt.title("Net information ratio with alpha decay")
plt.legend()
plt.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(OUT / "fig_ir_vs_aum.pdf", bbox_inches="tight")
plt.savefig(OUT / "fig_ir_vs_aum.png", dpi=180, bbox_inches="tight")
plt.close()

fig, ax_days = plt.subplots(figsize=(7.2, 4.4))
line_days = ax_days.plot(
    curve["aum_bn"], curve["average_execution_days"],
    label="Average execution days", linewidth=2, color="tab:blue",
)
ax_days.set_xlabel("AUM (£bn)")
ax_days.set_ylabel("Average execution days", color="tab:blue")
ax_days.tick_params(axis="y", labelcolor="tab:blue")
ax_days.grid(alpha=0.25)

ax_share = ax_days.twinx()
line_share = ax_share.plot(
    curve["aum_bn"], curve["share_3plus_days_pct"],
    label="Notional requiring 3+ days", linewidth=2, color="tab:orange",
)
ax_share.set_ylabel("Notional requiring 3+ days (%)", color="tab:orange")
ax_share.tick_params(axis="y", labelcolor="tab:orange")

lines = line_days + line_share
ax_days.legend(lines, [line.get_label() for line in lines], loc="upper left")
ax_days.set_title("Execution horizon increases with AUM")
fig.tight_layout()
fig.savefig(OUT / "fig_execution_horizon.pdf", bbox_inches="tight")
fig.savefig(OUT / "fig_execution_horizon.png", dpi=180, bbox_inches="tight")
plt.close(fig)

print("Expected impact parameters a,b,gamma:", PARAM_EXPECTED)
print("Realised impact parameters a,b,gamma:", PARAM_REALISED)
print("Burr XII parameters c,d,scale:", (BURR_C0, BURR_D0, BURR_SCALE0))
print("Burr tail index c*d:", BURR_C0 * BURR_D0)
print("\nDistribution fit:\n", distribution_fit.to_string(index=False))
print("\nScenario table:\n", scenarios.to_string(index=False))
print("\nThresholds:", thresholds)
