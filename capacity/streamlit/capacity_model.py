"""Notional-weighted execution-delay model with default Monte Carlo bootstrap.

Percent inputs are percentage points; annual costs are portfolio basis points.
The bucket approximation uses one explicitly supplied order/ADV point per bucket.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import numpy as np
import pandas as pd

LIVE = json.loads((Path(__file__).parent / "data/bucket-data.json").read_text())
BUCKETS = pd.DataFrame(LIVE["buckets"])
MODEL_VERSION = "execution-delay-mc-v2"
MIN_AUM = 0.5  # USD billions; lower bound for scenario calculations.


def annual_cost_from_buckets(buckets: pd.DataFrame, one_way_turnover_pct: float) -> float:
    """Legacy conversion: buys + sells / AUM = 2 * one-way turnover."""
    return float(2 * one_way_turnover_pct / 100 * np.average(buckets.cost, weights=buckets.valueUsdMillion))


@dataclass(frozen=True)
class Scenario:
    aum0: float = 3.4
    gross_alpha: float = 0.5
    tracking_error: float = 1.3
    daily_participation: float = 20.0
    half_life: float = 10.0
    annual_cost_bps: float = annual_cost_from_buckets(BUCKETS, 13.9)
    cost_elasticity: float = 0.0


def alpha_capture(duration, half_life: float):
    """Average exp(-lambda*t) over continuous uniform fills, including g(0)=1."""
    d = np.asarray(duration, dtype=float)
    if not np.isfinite(half_life) or half_life <= 0 or not np.isfinite(d).all() or (d < 0).any():
        raise ValueError("Duration must be finite and non-negative; half-life must be positive.")
    z = np.log(2) * d / half_life
    result = np.ones_like(z)
    np.divide(-np.expm1(-z), z, out=result, where=z != 0)
    return result


def validate_trades(tape: pd.DataFrame) -> pd.DataFrame:
    if tape.empty or not {"q", "adv"}.issubset(tape.columns):
        raise ValueError("Trade CSV requires at least one row and q, adv columns in the same currency.")
    try:
        frame = tape[["q", "adv"]].apply(pd.to_numeric, errors="raise")
    except (ValueError, TypeError) as error:
        raise ValueError("q and adv must contain positive finite numbers.") from error
    if not np.isfinite(frame.to_numpy()).all() or (frame <= 0).any().any():
        raise ValueError("q and adv must contain positive finite numbers.")
    return frame


def validate_buckets(buckets: pd.DataFrame) -> None:
    columns = ["p", "valueUsdMillion", "trades", "cost", "lower", "upper"]
    try:
        values = buckets[columns].to_numpy(float)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Order buckets require numeric bounds, p, valueUsdMillion, trades and cost.") from error
    if buckets.empty or not np.isfinite(values).all():
        raise ValueError("Order bucket inputs must be finite and non-empty.")
    if (buckets[["p", "valueUsdMillion", "trades", "cost", "lower"]] < 0).any().any():
        raise ValueError("Order bucket sizes, values, counts and costs cannot be negative.")
    if buckets.valueUsdMillion.sum() <= 0 or buckets.trades.sum() <= 0:
        raise ValueError("Order buckets require positive total notional and count.")
    if (buckets.upper <= buckets.lower).any() or (buckets.p < buckets.lower).any() or (buckets.p > buckets.upper).any():
        raise ValueError("Representative order/ADV must lie within valid bucket bounds.")


class ExecutionEngine:
    def __init__(self, scenario: Scenario, buckets: pd.DataFrame | None = None, trades: pd.DataFrame | None = None):
        self.p = scenario
        vals = np.array(list(vars(scenario).values()), float)
        if not np.isfinite(vals).all():
            raise ValueError("Model parameters must be finite.")
        if scenario.aum0 < MIN_AUM or scenario.tracking_error <= 0 or scenario.half_life <= 0 or not 0 < scenario.daily_participation <= 100:
            raise ValueError("Baseline AUM must be at least $500m; tracking error and half-life must be positive; daily participation must be in (0, 100].")
        if min(scenario.gross_alpha, scenario.annual_cost_bps, scenario.cost_elasticity) < 0:
            raise ValueError("Gross alpha, annual cost and cost elasticity cannot be negative.")
        if trades is not None:
            tape = validate_trades(trades)
            self.x = (tape.q / tape.adv).to_numpy()
            notionals = tape.q.to_numpy()
            counts = np.ones(len(tape))
            self.source = "trade-csv"
        else:
            frame = (BUCKETS if buckets is None else buckets).copy()
            validate_buckets(frame)
            self.x = frame.p.to_numpy(float)
            notionals = frame.valueUsdMillion.to_numpy(float)
            counts = frame.trades.to_numpy(float)
            self.source = "bucket-representatives"
        if not np.isfinite(self.x).all() or not np.isfinite(notionals.sum()) or not np.isfinite(counts.sum()):
            raise ValueError("Order ratios and total weights must be finite.")
        self.weights = notionals / notionals.sum()
        self.count_weights = counts / counts.sum()
        self.base_capture = float(np.dot(self.weights, alpha_capture(self.x / (scenario.daily_participation / 100), scenario.half_life)))
        if self.base_capture <= 0:
            raise ValueError("Baseline alpha capture must be positive.")

    def metric(self, aum_bn: float) -> dict:
        if not np.isfinite(aum_bn) or aum_bn < MIN_AUM:
            raise ValueError("Scenario AUM must be finite and at least $500m.")
        s = aum_bn / self.p.aum0
        days = s * self.x / (self.p.daily_participation / 100)
        raw = float(np.dot(self.weights, alpha_capture(days, self.p.half_life)))
        h = raw / self.base_capture
        gross = self.p.gross_alpha * h
        cost = self.p.annual_cost_bps * s ** self.p.cost_elasticity
        net = gross - cost / 100
        return {
            "AUM": aum_bn, "AUM multiple": s,
            "Alpha capture (%)": 100 * h, "Absolute capture (%)": 100 * raw,
            "After delay (%)": gross, "Annual drag (bp)": cost,
            "Net alpha (%)": net, "Net IR": net / self.p.tracking_error,
            "Retained alpha (%)": 100 * net / self.p.gross_alpha if self.p.gross_alpha else np.nan,
            "Average days": float(np.dot(self.weights, days)),
            "Multi-day (%)": float(100 * np.dot(self.weights, days > 1)),
            "Multi-day count (%)": float(100 * np.dot(self.count_weights, days > 1)),
            "Mean order/ADV (%)": float(100 * np.dot(self.weights, s * self.x)),
        }

    def contributions(self, aum_bn: float) -> pd.DataFrame:
        self.metric(aum_bn)
        s = aum_bn / self.p.aum0
        days = self.x * s / (self.p.daily_participation / 100)
        return pd.DataFrame({"Baseline order/ADV": self.x, "Notional weight": self.weights,
                             "Execution days": days, "Absolute capture": alpha_capture(days, self.p.half_life)})

    def capacity(self, minimum_ir: float, maximum: float) -> float | None:
        """First threshold crossing from $500m; bounded by chart horizon."""
        if not np.isfinite(maximum) or maximum < MIN_AUM:
            raise ValueError("Capacity horizon must be finite and at least $500m.")
        if self.metric(MIN_AUM)["Net IR"] <= minimum_ir:
            return MIN_AUM
        if self.metric(maximum)["Net IR"] > minimum_ir:
            return None
        lo, hi = MIN_AUM, maximum
        for _ in range(60):
            mid = (lo + hi) / 2
            if self.metric(mid)["Net IR"] > minimum_ir:
                lo = mid
            else:
                hi = mid
        return hi


def curve(engine: ExecutionEngine, maximum: float, uncertainty: bool = True) -> pd.DataFrame:
    if maximum < engine.p.aum0:
        raise ValueError("Chart horizon must be at least current AUM.")
    grid = np.unique(np.r_[np.linspace(MIN_AUM, maximum, 121), engine.p.aum0])
    result = pd.DataFrame([engine.metric(float(a)) for a in grid])
    if uncertainty and isinstance(engine, MonteCarloEngine):
        result = pd.concat([result, engine.intervals(grid)], axis=1)
    return result


class MonteCarloEngine(ExecutionEngine):
    """IID parent-order bootstrap, conditional on observed/proxy orders.

    Store only mean weights, not a samples-by-orders matrix. Replaying the seed
    yields identical books for uncertainty ranges and all AUM checkpoints.
    """
    def __init__(self, scenario: Scenario, buckets=None, trades=None, samples=2000, seed=2026, book_size=None):
        super().__init__(scenario, buckets, trades)
        if isinstance(samples, bool) or not isinstance(samples, (int, np.integer)) or not 2 <= samples <= 20000:
            raise ValueError("Monte Carlo samples must be an integer between 2 and 20,000.")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or not 0 <= seed <= 2**32-1:
            raise ValueError("Random seed must be an integer between 0 and 4,294,967,295.")
        self.samples, self.seed = int(samples), int(seed)
        if trades is not None:
            tape = validate_trades(trades)
            self.book_size = len(tape)
            self.unit_notional = tape.q.to_numpy(float)
        else:
            frame = BUCKETS if buckets is None else buckets
            counts = frame.trades.to_numpy(float)
            value = frame.valueUsdMillion.to_numpy(float)
            if np.any((counts > 0) != (value > 0)):
                raise ValueError("Monte Carlo buckets require positive traded value exactly where order counts are positive.")
            self.book_size = max(1, int(round(counts.sum())))
            self.unit_notional = np.divide(value, counts, out=np.zeros_like(value), where=counts > 0)
        if book_size is not None:
            if isinstance(book_size, bool) or not isinstance(book_size, (int, np.integer)) or not 1 <= book_size <= 1_000_000:
                raise ValueError("Annual parent-order count must be an integer between 1 and 1,000,000.")
            self.book_size = int(book_size)
        self.order_notional_usd = self.unit_notional.copy() * (1 if trades is not None else 1e6)
        self.unit_notional = self.unit_notional / self.unit_notional.max()
        self.probabilities = self.count_weights.copy()
        mean_weights = np.zeros_like(self.x)
        mean_counts = np.zeros_like(self.x)
        self.effective_weights = np.zeros_like(self.x)
        base_g = alpha_capture(self.x / (scenario.daily_participation/100), scenario.half_life)
        for weights, counts in self._books():
            g0 = weights @ base_g
            mean_weights += weights.sum(axis=0) / self.samples
            mean_counts += counts.sum(axis=0) / self.samples
            self.effective_weights += (weights / g0[:, None]).sum(axis=0) / self.samples
        self.weights = mean_weights
        self.count_weights = mean_counts

    def _books(self):
        rng = np.random.default_rng(self.seed)
        batch = max(1, min(128, 500000 // len(self.x)))
        for start in range(0, self.samples, batch):
            counts = rng.multinomial(self.book_size, self.probabilities, size=min(batch, self.samples-start))
            dollars = counts * self.unit_notional
            weights = dollars / dollars.sum(axis=1, keepdims=True)
            yield weights, counts / self.book_size

    def metric(self, aum_bn):
        result = super().metric(aum_bn)
        s = aum_bn / self.p.aum0
        g = alpha_capture(s*self.x/(self.p.daily_participation/100), self.p.half_life)
        h = 1.0 if s == 1 else float(np.dot(self.effective_weights, g))
        gross = self.p.gross_alpha*h
        net = gross-result['Annual drag (bp)']/100
        result.update({'Alpha capture (%)':100*h, 'After delay (%)':gross,
                       'Net alpha (%)':net, 'Net IR':net/self.p.tracking_error,
                       'Retained alpha (%)':100*net/self.p.gross_alpha if self.p.gross_alpha else np.nan})
        return result

    def sampled_book(self, index: int, aum_bn: float) -> pd.DataFrame:
        """Inspect one of the exact seeded books used by the capacity calculation."""
        if isinstance(index, bool) or not isinstance(index, (int, np.integer)) or not 0 <= index < self.samples:
            raise ValueError("Sample index must be an integer within the simulation count.")
        self.metric(aum_bn)  # Common AUM-domain validation.
        start = 0
        for weights, counts in self._books():
            if index < start + len(weights):
                row = index-start
                number = np.rint(counts[row]*self.book_size).astype(int)
                s = aum_bn/self.p.aum0
                days = self.x*s/(self.p.daily_participation/100)
                return pd.DataFrame({
                    "Baseline order/ADV": self.x,
                    "Order/ADV at selected AUM": self.x*s,
                    "Sampled orders": number,
                    "Sampled notional (USD)": number*self.order_notional_usd*s,
                    "Sampled notional weight": weights[row],
                    "Execution days": days,
                    "Absolute capture": alpha_capture(days,self.p.half_life),
                })
            start += len(weights)
        raise RuntimeError("Sampled book was not generated.")

    def impact_samples(self, aums, a, b, gamma):
        """Dollar-weighted power-law costs for the same seeded bootstrap books."""
        from impact_cost import impact_bps
        aums=np.asarray(aums,float)
        if not np.isfinite(aums).all() or np.any(aums<MIN_AUM):
            raise ValueError("Impact scenarios must start at $500m.")
        # Bound the temporary orders-by-AUM kernel for large actual-order tapes.
        samples=np.empty((self.samples,len(aums)))
        width=max(1,min(16,500000//len(self.x)))
        for j in range(0,len(aums),width):
            costs=impact_bps(self.x[:,None]*(aums[None,j:j+width]/self.p.aum0),a,b,gamma)
            start=0
            for weights,_ in self._books():
                samples[start:start+len(weights),j:j+width] = weights @ costs
                start+=len(weights)
        return samples

    def intervals(self, aums):
        aums = np.asarray(aums, float)
        if not np.isfinite(aums).all() or np.any(aums < MIN_AUM):
            raise ValueError("Scenario AUM must be finite and at least $500m.")
        multiples = aums/self.p.aum0
        ratios = np.empty((self.samples, len(aums)))
        base_g = alpha_capture(self.x/(self.p.daily_participation/100), self.p.half_life)
        start = 0
        for weights, _ in self._books():
            g0 = weights @ base_g
            for j in range(0, len(aums), 16):
                kernel = alpha_capture(self.x[:,None]*multiples[None,j:j+16]/(self.p.daily_participation/100), self.p.half_life)
                ratios[start:start+len(weights),j:j+16] = (weights @ kernel)/g0[:,None]
            start += len(weights)
        ratios[:,multiples == 1] = 1.0
        lo, hi = np.quantile(ratios, [.05,.95], axis=0)
        cost = self.p.annual_cost_bps*multiples**self.p.cost_elasticity/100
        alpha_lo, alpha_hi = self.p.gross_alpha*lo-cost, self.p.gross_alpha*hi-cost
        return pd.DataFrame({'Alpha capture P05 (%)':100*lo, 'Alpha capture P95 (%)':100*hi,
                             'Net alpha P05 (%)':alpha_lo, 'Net alpha P95 (%)':alpha_hi,
                             'Net IR P05':alpha_lo/self.p.tracking_error, 'Net IR P95':alpha_hi/self.p.tracking_error})


def create_engine(scenario, buckets=None, trades=None, mode='Monte Carlo', samples=2000, seed=2026):
    if mode == 'Monte Carlo':
        return MonteCarloEngine(scenario, buckets, trades, samples, seed)
    if mode == 'Deterministic':
        return ExecutionEngine(scenario, buckets, trades)
    raise ValueError("Calculation mode must be Monte Carlo or Deterministic.")
