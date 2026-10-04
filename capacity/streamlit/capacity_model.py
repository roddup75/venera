"""Core calculations for the Streamlit Capacity Lab dashboard."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
LIVE = json.loads((ROOT / "dashboard/app/bucket-data.json").read_text())
UNIVERSE = json.loads((ROOT / "dashboard/app/universe-adv-data.json").read_text())
BUCKETS = pd.DataFrame(LIVE["buckets"])
ADV_POINTS = pd.DataFrame(UNIVERSE["quantiles"])
MIGRATION_LABELS = [*BUCKETS["label"].tolist(), ">100%"]
HISTORICAL_AUM = 3.4e9
HISTORICAL_HOLDINGS = 40


@dataclass(frozen=True)
class Scenario:
    aum0: float = 3.4
    gross_alpha: float = 0.5
    tracking_error: float = 1.3
    turnover: float = 13.9
    holdings: int = 40
    universe_size: int = 203
    scale_elasticity: float = 0.85
    tail_elasticity: float = 0.0
    daily_participation: float = 20.0
    max_days: int = 10
    half_life: float = 10.0
    adv_volume: float = 100.0
    liquidity_deterioration: float = 0.0
    burr_c: float = LIVE["calibration"]["burrC"]
    burr_d: float = LIVE["calibration"]["burrD"]
    burr_scale: float = LIVE["calibration"]["burrScale"]
    impact_a: float = LIVE["calibration"]["impactA"]
    impact_b: float = LIVE["calibration"]["impactB"]
    impact_gamma: float = LIVE["calibration"]["impactGamma"]


def adv_at(q: float, adv_points: pd.DataFrame | None = None) -> float:
    points = ADV_POINTS if adv_points is None else adv_points
    percentiles = points["percentile"].to_numpy(float)
    values = points["advUsd"].to_numpy(float)
    target = q * 100
    hi = int(np.searchsorted(percentiles, target, side="left"))
    if hi <= 0:
        return float(values[0])
    if hi >= len(values):
        return float(values[-1])
    t = (target - percentiles[hi - 1]) / (percentiles[hi] - percentiles[hi - 1])
    return float(np.exp(np.log(values[hi - 1]) * (1 - t) + np.log(values[hi]) * t))


def calibrate_orders(
    preference: float = 0.0,
    buckets: pd.DataFrame | None = None,
    adv_points: pd.DataFrame | None = None,
    universe_size: int = 203,
) -> pd.DataFrame:
    bucket_data = BUCKETS if buckets is None else buckets.reset_index(drop=True)
    points = ADV_POINTS if adv_points is None else adv_points.reset_index(drop=True)
    stock_grid_size = max(2, min(int(universe_size), 1000))
    rows: list[dict] = []
    for bucket, b in bucket_data.iterrows():
        mean = b.valueUsdMillion * 1e6 / b.trades
        cells = []
        for j in range(stock_grid_size):
            q = (j + 0.5) / stock_grid_size
            adv = adv_at(q, points)
            for k in range(16):
                participation = b.lower + (b.upper - b.lower) * (k + 0.5) / 16
                ticket = participation * adv
                prior = preference * (2 * q - 1) - 0.5 * (np.log(ticket / mean) / 1.5) ** 2
                cells.append((adv, ticket, prior))
        frame = pd.DataFrame(cells, columns=["adv", "ticket", "prior"])
        maximum = frame.ticket.max()
        if not frame.ticket.min() < mean < maximum:
            raise ValueError(f"Cannot reconcile {b.label} with supplied ADV support")

        def weights(tilt: float) -> np.ndarray:
            logs = frame.prior.to_numpy() + tilt * frame.ticket.to_numpy() / maximum
            raw = np.exp(logs - logs.max())
            return raw / raw.sum()

        def expectation(tilt: float) -> float:
            return float(np.dot(weights(tilt), frame.ticket))

        lo, hi = -1.0, 1.0
        while expectation(lo) > mean and lo > -1e9:
            lo *= 2
        while expectation(hi) < mean and hi < 1e9:
            hi *= 2
        for _ in range(70):
            mid = (lo + hi) / 2
            if expectation(mid) < mean:
                lo = mid
            else:
                hi = mid
        frame["count"] = weights((lo + hi) / 2) * b.trades
        frame["bucket"] = bucket
        rows.extend(frame[["adv", "ticket", "count", "bucket"]].to_dict("records"))
    return pd.DataFrame(rows)


def alpha_capture(days: np.ndarray | float, half_life: float) -> np.ndarray:
    d = np.asarray(days, dtype=float)
    decay = np.log(2) / max(half_life, 0.01)
    return -np.expm1(-decay * d) / (d * -np.expm1(-decay))


class AdvEngine:
    def __init__(
        self,
        scenario: Scenario,
        orders: pd.DataFrame,
        buckets: pd.DataFrame | None = None,
        anchor_aum: float = HISTORICAL_AUM / 1e9,
        anchor_holdings: int = HISTORICAL_HOLDINGS,
        impact_reference: tuple[float, float, float] | None = None,
    ):
        self.p = scenario
        self.orders = orders
        self.buckets = (BUCKETS if buckets is None else buckets).reset_index(drop=True)
        self.anchor_aum = max(float(anchor_aum), 0.0001)
        self.anchor_holdings = max(int(anchor_holdings), 1)
        self.base_value = float((self.buckets.valueUsdMillion * 1e6).sum())
        self.historical_turnover = self.base_value / (2 * self.anchor_aum * 1e9)
        self.rho = max(scenario.daily_participation / 100, 0.0001)
        observed_participation = self.orders.ticket.to_numpy() / self.orders.adv.to_numpy()
        self.daily_capacity = np.maximum(self.rho, observed_participation)
        self.horizon = max(1, int(scenario.max_days))
        self.impact_reference = impact_reference or (
            scenario.impact_a, scenario.impact_b, scenario.impact_gamma,
        )
        base = self._distribution(scenario.aum0)
        self.base_alpha = max(base["alpha_raw"], 1e-12)
        observed = float(np.average(self.buckets.cost, weights=self.buckets.valueUsdMillion))
        reference = self._distribution(scenario.aum0, self.impact_reference)
        self.cost_scale = observed / max(reference["cost_raw"], 1e-12)

    def _execution(
        self,
        participation: np.ndarray,
        impact_parameters: tuple[float, float, float] | None = None,
    ) -> tuple[np.ndarray, ...]:
        required = np.maximum(
            1, np.ceil(participation / self.daily_capacity - 1e-12),
        ).astype(int)
        days = np.minimum(self.horizon, required)
        fraction = np.minimum(
            1, self.horizon * self.daily_capacity / np.maximum(participation, 1e-12),
        )
        alpha = fraction * alpha_capture(days, self.p.half_life)
        a, b, gamma = impact_parameters or (
            self.p.impact_a, self.p.impact_b, self.p.impact_gamma,
        )
        cost = a + b * np.minimum(participation, self.daily_capacity) ** gamma
        return required, days, fraction, alpha, cost

    def _distribution(
        self,
        aum_bn: float,
        impact_parameters: tuple[float, float, float] | None = None,
    ) -> dict:
        holdings = min(max(self.p.holdings, 1), max(self.p.universe_size, 1))
        aum_ratio = max(aum_bn, 0.0001) / self.anchor_aum
        size = aum_ratio * self.anchor_holdings / holdings
        frequency = holdings / self.anchor_holdings * max(self.p.turnover, 0) / 100 / self.historical_turnover
        ticket = self.orders.ticket.to_numpy() * size
        liquidity_factor = aum_ratio ** -max(self.p.liquidity_deterioration, 0.0)
        adv = self.orders.adv.to_numpy() * max(self.p.adv_volume, 0.01) / 100 * liquidity_factor
        count = self.orders["count"].to_numpy() * frequency
        participation = ticket / adv
        bucket = np.searchsorted(self.buckets.upper.to_numpy(), participation, side="left")
        counts = np.bincount(bucket, weights=count, minlength=len(self.buckets) + 1)
        values = np.bincount(bucket, weights=ticket * count, minlength=len(self.buckets) + 1)
        required, _, fraction, alpha, cost = self._execution(participation, impact_parameters)
        historical_weights = self.orders.ticket.to_numpy() * self.orders["count"].to_numpy() / self.base_value
        count_total = float(count.sum())
        average_execution_days = (
            float(np.dot(count, participation / self.daily_capacity) / count_total)
            if count_total else 0.0
        )
        order = np.argsort(participation)
        cumulative_notional = np.cumsum(historical_weights[order])
        p90_index = min(int(np.searchsorted(cumulative_notional, 0.90, side="left")), len(order) - 1)
        p90_participation = float(participation[order[p90_index]])
        return {
            "counts": counts, "values": values,
            "alpha_raw": float(np.dot(historical_weights, alpha)),
            "cost_raw": float(np.dot(historical_weights, fraction * cost)),
            "avg_days": average_execution_days,
            "multi": float(np.dot(historical_weights, required >= 2)),
            "three": float(np.dot(historical_weights, required >= 3)),
            "mean_participation": float(np.dot(historical_weights, participation)),
            "p90_participation": p90_participation,
            "notional_above_10": float(np.dot(historical_weights, participation > 0.10)),
            "notional_above_25": float(np.dot(historical_weights, participation > 0.25)),
            "unfinished": float(np.dot(historical_weights, 1 - fraction)),
            "required": required, "count_weights": count,
        }

    @staticmethod
    def _shares(values: np.ndarray) -> np.ndarray:
        return values / values.sum() * 100 if values.sum() else np.zeros_like(values)

    def metric(self, aum_bn: float) -> dict:
        d = self._distribution(aum_bn)
        impact = d["cost_raw"] * self.cost_scale
        capture_pct = 100 * d["alpha_raw"] / self.base_alpha
        implemented = self.p.gross_alpha * capture_pct / 100
        annual_drag = 2 * self.p.turnover / 100 * impact
        net_alpha = implemented - annual_drag / 100
        return {
            "AUM": aum_bn, "Impact (bp)": impact, "Annual drag (bp)": annual_drag,
            "Alpha capture (%)": capture_pct, "After delay (%)": implemented,
            "Net alpha (%)": net_alpha, "Net IR": net_alpha / max(self.p.tracking_error, 0.01),
            "Retained alpha (%)": 100 * net_alpha / max(self.p.gross_alpha, 0.01),
            "Average days": d["avg_days"], "Multi-day (%)": 100 * d["multi"],
            "3+ days (%)": 100 * d["three"], "Mean participation (%)": 100 * d["mean_participation"],
            "P90 participation (%)": 100 * d["p90_participation"],
            "Notional above 10% ADV (%)": 100 * d["notional_above_10"],
            "Notional above 25% ADV (%)": 100 * d["notional_above_25"],
            "Unfinished notional (%)": 100 * d["unfinished"],
            "Annual parent orders": float(d["counts"].sum()), "Annual value": float(d["values"].sum()),
        }

    def dollar_shares(self, aum_bn: float) -> np.ndarray:
        return self._shares(self._distribution(aum_bn)["values"])

    def count_shares(self, aum_bn: float) -> np.ndarray:
        return self._shares(self._distribution(aum_bn)["counts"])

    def execution_shares(self, aum_bn: float) -> np.ndarray:
        d = self._distribution(aum_bn)
        required, weights = d["required"], d["count_weights"]
        groups = np.array([
            weights[required == 1].sum(),
            weights[(required >= 2) & (required <= 5)].sum(),
            weights[(required >= 6) & (required <= self.horizon)].sum(),
            weights[required > self.horizon].sum(),
        ])
        return self._shares(groups)


def burr_cdf(x: float, c: float, d: float, scale: float) -> float:
    if x <= 0:
        return 0.0
    if not np.isfinite(x):
        return 1.0
    return float(1 - (1 + (x / max(scale, 1e-12)) ** c) ** -d)


def burr_ppf(q: np.ndarray, c: float, d: float, scale: float) -> np.ndarray:
    return scale * ((1 - q) ** (-1 / d) - 1) ** (1 / c)


def burr_shares(
    aum_bn: float,
    scenario: Scenario,
    count_fit: bool = False,
    eta: float | None = None,
    kappa: float | None = None,
    buckets: pd.DataFrame | None = None,
) -> np.ndarray:
    fit = LIVE["countCalibration"] if count_fit else {"burrC": scenario.burr_c, "burrD": scenario.burr_d, "burrScale": scenario.burr_scale, "scaleElasticity": scenario.scale_elasticity, "tailElasticity": scenario.tail_elasticity}
    ratio = aum_bn / scenario.aum0
    e = fit["scaleElasticity"] if eta is None else eta
    k = fit["tailElasticity"] if kappa is None else kappa
    scale = fit["burrScale"] * ratio ** e
    d = fit["burrD"] * ratio ** -k
    bucket_data = BUCKETS if buckets is None else buckets
    edges = [0, *bucket_data.upper.tolist(), np.inf]
    return np.array([(burr_cdf(edges[i + 1], fit["burrC"], d, scale) - burr_cdf(edges[i], fit["burrC"], d, scale)) * 100 for i in range(len(edges) - 1)])


class BurrEngine:
    def __init__(
        self,
        scenario: Scenario,
        buckets: pd.DataFrame | None = None,
        impact_reference: tuple[float, float, float] | None = None,
    ):
        self.p = scenario
        self.buckets = (BUCKETS if buckets is None else buckets).reset_index(drop=True)
        self.q = (np.arange(700) + 0.5) / 700
        self.base = burr_ppf(self.q, scenario.burr_c, scenario.burr_d, scenario.burr_scale)
        self.base_days = np.minimum(scenario.max_days, np.maximum(1, np.ceil(self.base / (scenario.daily_participation / 100))))
        self.base_capture = alpha_capture(self.base_days, scenario.half_life)
        observed = float(np.average(self.buckets.cost, weights=self.buckets.share))
        self.impact_reference = impact_reference or (
            scenario.impact_a, scenario.impact_b, scenario.impact_gamma,
        )
        raw = np.mean(self._cost(self.base, self.impact_reference))
        self.impact_scale = observed / max(raw, 1e-12)

    def _cost(
        self,
        participation: np.ndarray,
        impact_parameters: tuple[float, float, float] | None = None,
    ) -> np.ndarray:
        a, b, gamma = impact_parameters or (
            self.p.impact_a, self.p.impact_b, self.p.impact_gamma,
        )
        return a + b * np.maximum(0, participation) ** gamma

    def metric(self, aum_bn: float) -> dict:
        ratio = max(aum_bn, 0.01) / max(self.p.aum0, 0.01)
        scale = self.p.burr_scale * ratio ** self.p.scale_elasticity
        d = self.p.burr_d * ratio ** -self.p.tail_elasticity
        participation = burr_ppf(self.q, self.p.burr_c, d, scale)
        days = np.minimum(self.p.max_days, np.maximum(1, np.ceil(participation / (self.p.daily_participation / 100))))
        effective = participation * self.base_days / days
        impact = float(np.mean(self._cost(effective)) * self.impact_scale)
        capture_pct = float(np.mean(alpha_capture(days, self.p.half_life) / self.base_capture) * 100)
        implemented = self.p.gross_alpha * capture_pct / 100
        annual_drag = 2 * self.p.turnover / 100 * impact
        net_alpha = implemented - annual_drag / 100
        return {
            "AUM": aum_bn, "Impact (bp)": impact, "Annual drag (bp)": annual_drag,
            "Alpha capture (%)": capture_pct, "After delay (%)": implemented,
            "Net alpha (%)": net_alpha, "Net IR": net_alpha / max(self.p.tracking_error, .01),
            "Retained alpha (%)": 100 * net_alpha / max(self.p.gross_alpha, .01),
            "Average days": float(np.mean(participation / (self.p.daily_participation / 100))),
            "Multi-day (%)": float((days >= 2).mean() * 100),
            "3+ days (%)": float((days >= 3).mean() * 100), "Mean participation (%)": float(participation.mean() * 100),
            "P90 participation (%)": float(np.quantile(participation, 0.90) * 100),
            "Notional above 10% ADV (%)": float((participation > 0.10).mean() * 100),
            "Notional above 25% ADV (%)": float((participation > 0.25).mean() * 100),
            "Unfinished notional (%)": 0.0,
        }

    def dollar_shares(self, aum_bn: float) -> np.ndarray:
        return burr_shares(aum_bn, self.p, buckets=self.buckets)


def curve(engine, maximum: float) -> pd.DataFrame:
    return pd.DataFrame([engine.metric(max(0.1, maximum * (i + 1) / 61)) for i in range(61)])
