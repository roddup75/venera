"""Historical bucket counts and ticket sizes with conditional ADV sampling."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from capacity_model import ExecutionEngine, MonteCarloEngine, alpha_capture, create_engine, BUCKETS, validate_buckets

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
    a recovered stock-level tape. Selection is conditional on its calibrated baseline bucket.
    """
    percentiles, adv = validate_universe(points, universe_size)
    ranks = 100 * (np.arange(universe_size) + .5) / universe_size
    return np.exp(np.interp(ranks, percentiles, np.log(adv)))


def calibrated_support(scenario, buckets, points, universe_size, annual_trades, turnover):
    """Return compatible bucket/stock cells and a fixed integer annual allocation."""
    validate_universe(points, universe_size, annual_trades)
    validate_buckets(buckets)
    if not np.isfinite(turnover) or turnover < 0:
        raise ValueError("One-way annual turnover must be finite and nonnegative.")
    lower=buckets.lower.to_numpy(float); upper=buckets.upper.to_numpy(float)
    if lower[0]!=0 or not np.allclose(lower[1:],upper[:-1],rtol=0,atol=1e-10):
        raise ValueError("Calibrated sampling requires contiguous ordered buckets starting at zero.")
    observed = buckets.trades.to_numpy(float)
    values = buckets.valueUsdMillion.to_numpy(float)
    if np.any((observed > 0) != (values > 0)):
        raise ValueError("Each populated bucket needs both positive counts and traded value.")
    active = observed > 0
    if annual_trades < active.sum():
        raise ValueError("Annual order count must cover every populated historical bucket.")
    quota = annual_trades * observed / observed.sum()
    counts = np.floor(quota).astype(int)
    for i in np.argsort(-(quota-counts), kind="stable")[:annual_trades-counts.sum()]:
        counts[i] += 1
    for i in np.flatnonzero(active & (counts == 0)):
        donors = np.flatnonzero(counts > 1)
        donor = donors[np.argmax((counts-quota)[donors])]
        counts[donor] -= 1
        counts[i] = 1
    adv = universe_adv(points, universe_size)
    target = 2 * turnover / 100 * scenario.aum0 * 1e9
    # A positive historical reference selects compatible names in no-trading mode.
    allocation_target = target if target else values.sum()*1e6
    tickets = np.divide(allocation_target*values/values.sum(), counts,
                        out=np.zeros_like(values), where=counts > 0)
    rows=[]; groups=[]; expected=[]
    for b in np.flatnonzero(active):
        ratio=tickets[b]/adv
        eligible=np.flatnonzero((ratio >= buckets.lower.iloc[b]) & (ratio < buckets.upper.iloc[b]))
        if len(eligible)==0:
            raise ValueError(f"No compatible stock ADV for bucket {buckets.label.iloc[b]} "
                             f"with a ${tickets[b]:,.2f} ticket. Review ADV, turnover, bucket values and annual counts.")
        start=len(rows)
        for stock in eligible:
            rows.append({"bucket":b,"stock":stock+1,"adv":adv[stock],"q":tickets[b]})
            expected.append(counts[b]/annual_trades/len(eligible))
        groups.append((slice(start,len(rows)),int(counts[b])))
    support=pd.DataFrame(rows)
    return support,groups,np.asarray(expected),target


class UniverseMonteCarloEngine(MonteCarloEngine):
    def __init__(self,scenario,groups,**kwargs):
        self.groups=groups
        super().__init__(scenario,**kwargs)

    def _books(self):
        # Independent bucket streams keep seeded books stable across batch sizes.
        streams=[np.random.default_rng(np.random.SeedSequence([self.seed,b]))
                 for b in range(len(self.groups))]
        batch=max(1,min(128,500000//len(self.x)))
        for start in range(0,self.samples,batch):
            size=min(batch,self.samples-start)
            counts=np.zeros((size,len(self.x)),dtype=int)
            for rng,(cells,n) in zip(streams,self.groups):
                width=cells.stop-cells.start
                counts[:,cells]=rng.multinomial(n,np.full(width,1/width),size=size)
            dollars=counts*self.unit_notional
            yield dollars/dollars.sum(axis=1,keepdims=True),counts/self.book_size

    def sampled_book(self,index,aum_bn):
        book=super().sampled_book(index,aum_bn)
        book.insert(0,"Support row",np.arange(len(self.x)))
        book.insert(1,"Baseline bucket",self.baseline_labels)
        book.insert(2,"Synthetic stock",self.stock_ids)
        book.insert(3,"Stock ADV (USD/day)",self.universe_adv)
        book.insert(4,"Order notional (USD)",self.order_notional_usd*aum_bn/self.p.aum0)
        return book

    def monthly_book(self,index,aum_bn):
        """Partition annual bucket/stock cells without changing their tickets."""
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
            for cell in np.flatnonzero(selected):
                records.append({'Month':month,'Support row':int(cell),
                                'Baseline bucket':self.baseline_labels[cell],
                                'Synthetic stock':int(self.stock_ids[cell]),
                                'Stock ADV (USD/day)':self.universe_adv[cell],
                                'Parent orders':int(selected[cell]),
                                'Order notional (USD)':annual['Order notional (USD)'].iloc[cell],
                                'Traded notional (USD)':selected[cell]*annual['Order notional (USD)'].iloc[cell]})
        return pd.DataFrame(records)


def create_liquidity_engine(scenario, buckets=None, trades=None, mode="Monte Carlo",
                            samples=2000, seed=2026, adv_points=None,
                            universe_size=300, annual_trades=971, turnover=13.9):
    if trades is not None:
        engine=create_engine(scenario,buckets,trades,mode,samples,seed)
        engine.book_size=len(trades)
        return engine
    buckets=BUCKETS if buckets is None else buckets
    points=ADV_POINTS if adv_points is None else adv_points
    support,groups,expected,target=calibrated_support(scenario,buckets,points,universe_size,annual_trades,turnover)
    tape=support[['q','adv']]
    if mode=="Monte Carlo":
        engine=UniverseMonteCarloEngine(scenario,groups,trades=tape,samples=samples,
                                      seed=seed,book_size=annual_trades)
    elif mode=="Deterministic":
        engine=ExecutionEngine(scenario,trades=tape)
        engine.book_size=annual_trades
        engine.count_weights=expected
        dollars=expected*support.q.to_numpy()
        engine.weights=dollars/dollars.sum()
    else:
        raise ValueError("Calculation mode must be Monte Carlo or Deterministic.")
    engine.universe_adv=support.adv.to_numpy()
    engine.stock_ids=support.stock.to_numpy()
    engine.baseline_labels=buckets.label.iloc[support.bucket].to_numpy()
    engine.order_notional_usd=support.q.to_numpy() if target else np.zeros(len(support))
    engine.x=engine.order_notional_usd/engine.universe_adv
    engine.source="calibrated-universe-adv"
    base=alpha_capture(engine.x/(scenario.daily_participation/100),scenario.half_life)
    engine.base_capture=float(engine.weights@base)
    if mode=="Monte Carlo":
        engine.effective_weights=np.zeros(len(support))
        for weights,_ in engine._books():
            engine.effective_weights+=(weights/(weights@base)[:,None]).sum(axis=0)/engine.samples
    return engine
