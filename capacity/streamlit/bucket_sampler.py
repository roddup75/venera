"""Count-preserving bucket reclassification of a single simulated order book."""
import numpy as np
import pandas as pd


def bucket_migration(book, buckets, current_aum):
    """Return distributions and paired flows at current, x2 and x3 AUM.

    Order/ADV uses the baseline ratios, independent of the AUM selected for
    single-book inspection. Intervals are left-closed, right-open, with an
    explicit unbounded overflow bucket.
    """
    lower=buckets.lower.to_numpy(float); upper=buckets.upper.to_numpy(float)
    if (len(upper)==0 or not np.isfinite(lower).all() or not np.isfinite(upper).all()
        or lower[0]!=0 or np.any(upper<=lower) or np.any(np.diff(upper)<=0)
        or not np.allclose(lower[1:],upper[:-1],rtol=0,atol=1e-10)):
        raise ValueError('Migration requires ordered, contiguous ADV buckets starting at zero.')
    x=book['Baseline order/ADV'].to_numpy(float)
    n=book['Sampled orders'].to_numpy(float)
    if (not np.isfinite(x).all() or not np.isfinite(n).all() or np.any(x<0)
        or np.any(n<0) or not np.equal(n,np.round(n)).all() or n.sum()<=0):
        raise ValueError('Migration requires nonnegative order ratios and integer counts with a positive total.')
    if not np.isfinite(current_aum) or current_aum<.5:
        raise ValueError('Current AUM must be at least $500m.')
    labels=buckets.label.astype(str).tolist()+[f'≥{upper[-1]*100:g}%']
    scenarios=['Current AUM','×2 AUM','×3 AUM']
    categories=[np.searchsorted(upper,x*multiple,side='right') for multiple in (1,2,3)]
    distributions=[]; flows=[]
    for stage,category in enumerate(categories):
        counts=np.bincount(category,weights=n,minlength=len(labels))
        for i,count in enumerate(counts):
            distributions.append({'Stage':stage,'Scenario':scenarios[stage],
                                  'AUM (USD bn)':current_aum*(stage+1),'Bucket index':i,
                                  'Bucket':labels[i],'Trades':int(round(count)),
                                  'Trade share (%)':100*count/n.sum()})
    for stage in (0,1):
        pairs=categories[stage]*len(labels)+categories[stage+1]
        counts=np.bincount(pairs,weights=n,minlength=len(labels)**2).reshape(len(labels),len(labels))
        for source,target in zip(*np.nonzero(counts)):
            flows.append({'From stage':stage,'From bucket':int(source),'To stage':stage+1,
                          'To bucket':int(target),'Trades':int(round(counts[source,target]))})
    return pd.DataFrame(distributions),pd.DataFrame(flows)
