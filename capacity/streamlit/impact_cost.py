"""Legacy nonnegative power-law impact fit, in bp per traded dollar."""
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ImpactFit:
    a: float
    b: float
    gamma: float
    rmse: float


def impact_bps(order_adv, a, b, gamma):
    x=np.asarray(order_adv,float)
    if not np.isfinite([a,b,gamma]).all() or a<0 or b<0 or gamma<=0:
        raise ValueError('Impact intercept and scale must be nonnegative; curvature must be positive.')
    if not np.isfinite(x).all() or (x<0).any():
        raise ValueError('Order/ADV must be finite and nonnegative.')
    return a+b*x**gamma


def fit_impact_cost(buckets, target='cost'):
    """Equal-weight bucket least squares, matching the legacy fit convention.

    Fit a,b >= 0 and .05 <= gamma <= 3. Aggregation subsequently uses
    notional weights; fitting weights are intentionally distinct.
    """
    x=buckets['p'].to_numpy(float); y=buckets[target].to_numpy(float)
    if len(x)<3 or len(np.unique(x))<3 or not np.isfinite(x).all() or not np.isfinite(y).all() or (x<0).any() or (y<0).any():
        raise ValueError('Impact fitting requires three distinct finite nonnegative order/ADV points and nonnegative costs.')
    def candidate(gamma):
        z=x**gamma
        matrix=np.column_stack([np.ones(len(x)),z])
        a,b=np.linalg.lstsq(matrix,y,rcond=None)[0]
        candidates=[(float(np.mean(y)),0.)]
        if a>=0 and b>=0: candidates.append((a,b))
        if np.dot(z,z)>0: candidates.append((0.,max(0.,np.dot(z,y)/np.dot(z,z))))
        return min((float(np.sum((a+b*z-y)**2)),float(a),float(b),float(gamma)) for a,b in candidates)
    grid=np.linspace(.05,3.,601)
    results=[candidate(g) for g in grid]
    index=min(range(len(results)),key=lambda i:results[i][0])
    lo,hi=grid[max(0,index-1)],grid[min(len(grid)-1,index+1)]
    ratio=(np.sqrt(5)-1)/2
    left=hi-ratio*(hi-lo); right=lo+ratio*(hi-lo)
    fleft,fright=candidate(left),candidate(right)
    for _ in range(60):
        if fleft[0]<fright[0]:
            hi,right,fright=right,left,fleft
            left=hi-ratio*(hi-lo); fleft=candidate(left)
        else:
            lo,left,fleft=left,right,fright
            right=lo+ratio*(hi-lo); fright=candidate(right)
    error,a,b,gamma=min(results[index],fleft,fright)
    return ImpactFit(a,b,gamma,float(np.sqrt(error/len(x))))


def impact_curve(sampler, maximum, a, b, gamma, turnover_pct):
    if not np.isfinite(turnover_pct) or turnover_pct<0:
        raise ValueError('One-way annual turnover must be finite and nonnegative.')
    grid=np.unique(np.r_[np.linspace(.5,maximum,81),sampler.p.aum0] )
    grid=grid[grid<=maximum]
    draws=sampler.impact_samples(grid,a,b,gamma)
    low,high=np.quantile(draws,[.05,.95],axis=0)
    factor=2*turnover_pct/100
    return pd.DataFrame({'AUM':grid,'Mean impact (bp/traded dollar)':draws.mean(axis=0),
                         'Impact P05 (bp/traded dollar)':low,'Impact P95 (bp/traded dollar)':high,
                         'Annual drag (portfolio bp)':factor*draws.mean(axis=0),
                         'Annual drag P05 (portfolio bp)':factor*low,
                         'Annual drag P95 (portfolio bp)':factor*high})
