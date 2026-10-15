"""Equal-notional annual orders sampled uniformly from an approximate ADV universe."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from capacity_model import ExecutionEngine, MonteCarloEngine, alpha_capture, create_engine

UNIVERSE = json.loads((Path(__file__).parent / "data/universe-adv-data.json").read_text())
ADV_POINTS = pd.DataFrame(UNIVERSE["quantiles"])


def validate_universe(points, universe_size=300, annual_trades=971):
    for value, maximum, label in ((universe_size, 10000, "Universe size"), (annual_trades, 1000000, "Annual parent-order count")):
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not 1 <= value <= maximum:
            raise ValueError(f"{label} must be an integer between 1 and {maximum:,}.")
    try:
        values = points[["percentile", "advUsd"]].to_numpy(float)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("ADV percentiles require numeric percentile and advUsd columns.") from error
    if len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("Provide at least two finite ADV percentile boundaries.")
    percentiles, adv = values.T
    if percentiles[0] != 0 or percentiles[-1] != 100 or np.any(np.diff(percentiles) <= 0):
        raise ValueError("ADV percentiles must increase strictly from 0 to 100.")
    if np.any(adv <= 0) or np.any(np.diff(adv) < 0):
        raise ValueError("ADV values must be positive and nondecreasing.")
    return percentiles, adv


def universe_adv(points=ADV_POINTS, universe_size=300):
    """Log-dollar interpolation at equally spaced midpoint stock ranks.

    This approximates individual stocks from percentile boundaries; it is not
    a recovered stock-level tape. Each synthetic stock is equally likely.
    """
    percentiles, adv = validate_universe(points, universe_size)
    ranks = 100 * (np.arange(universe_size) + .5) / universe_size
    return np.exp(np.interp(ranks, percentiles, np.log(adv)))


class UniverseMonteCarloEngine(MonteCarloEngine):
    def sampled_book(self, index, aum_bn):
        book = super().sampled_book(index, aum_bn)
        book.insert(0, "Synthetic stock", np.arange(1, len(self.x) + 1))
        book.insert(1, "Stock ADV (USD/day)", self.universe_adv)
        book.insert(2, "Order notional (USD)", self.order_notional_usd * aum_bn / self.p.aum0)
        return book

    def monthly_book(self,index,aum_bn):
        """Partition the inspected annual book into 12 monthly rebalances.

        Conditional random allocation preserves the exact annual stock counts.
        Monthly counts differ by at most one; fixed ADV and equal tickets mean
        this calendar allocation does not change annual impact or capacity.
        """
        annual=self.sampled_book(index,aum_bn)
        remaining=annual['Sampled orders'].to_numpy(int).copy()
        counts=np.full(12,self.book_size//12,dtype=int)
        counts[:self.book_size%12]+=1
        rng=np.random.default_rng(np.random.SeedSequence([self.seed,2,int(index)]))
        records=[]
        for month,n in enumerate(counts,1):
            if n==0:continue
            selected=remaining.copy() if n==remaining.sum() else rng.multivariate_hypergeometric(remaining,int(n))
            remaining-=selected
            for stock in np.flatnonzero(selected):
                records.append({'Month':month,'Synthetic stock':int(stock+1),
                                'Stock ADV (USD/day)':self.universe_adv[stock],
                                'Parent orders':int(selected[stock]),
                                'Order notional (USD)':annual['Order notional (USD)'].iloc[stock],
                                'Traded notional (USD)':selected[stock]*annual['Order notional (USD)'].iloc[stock]})
        return pd.DataFrame(records)


def create_liquidity_engine(scenario, buckets=None, trades=None, mode="Monte Carlo",
                            samples=2000, seed=2026, adv_points=None,
                            universe_size=300, annual_trades=971, turnover=13.9):
    if trades is not None:
        engine = create_engine(scenario, buckets, trades, mode, samples, seed)
        engine.book_size = len(trades)
        return engine
    points = ADV_POINTS if adv_points is None else adv_points
    validate_universe(points, universe_size, annual_trades)
    if not np.isfinite(turnover) or turnover < 0:
        raise ValueError("One-way annual turnover must be finite and nonnegative.")
    adv = universe_adv(points, universe_size)
    q = 2 * turnover / 100 * scenario.aum0 * 1e9 / annual_trades
    # Unit-dollar orders establish uniform stock probabilities and equal weights.
    # Apply the actual ticket afterwards, including the zero-turnover limit.
    unit_tape = pd.DataFrame({"q": np.ones(universe_size), "adv": adv})
    if mode == "Monte Carlo":
        engine = UniverseMonteCarloEngine(scenario, trades=unit_tape, samples=samples,
                                         seed=seed, book_size=annual_trades)
    elif mode == "Deterministic":
        engine = ExecutionEngine(scenario, trades=unit_tape)
        engine.book_size = annual_trades
    else:
        raise ValueError("Calculation mode must be Monte Carlo or Deterministic.")
    engine.x = q / adv
    engine.universe_adv = adv
    engine.source = "universe-adv-equal-notional"
    base = alpha_capture(engine.x / (scenario.daily_participation / 100), scenario.half_life)
    engine.base_capture = float(engine.weights @ base)
    if mode == "Monte Carlo":
        engine.order_notional_usd = np.full(universe_size, q)
        engine.effective_weights = np.zeros(universe_size)
        for weights, _ in engine._books():
            engine.effective_weights += (weights / (weights @ base)[:, None]).sum(axis=0) / engine.samples
    return engine
