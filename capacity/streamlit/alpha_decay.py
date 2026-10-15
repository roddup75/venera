"""Three-point, count-based congestion calibration with fixed other effects."""
from types import SimpleNamespace
import numpy as np
import pandas as pd

DEFAULT_POINTS = [[.5, 0., .60], [3., 2., .57], [6., 10., .50]]
COLUMNS = ['AUM (USD bn)', 'Trades >1 day (%)', 'Net IR']


class AlphaDecayModel:
    def __init__(self, points, tracking_error=1.3, aum0=.5, samples=2000, seed=2026, book_size=None):
        v = np.asarray(points, float)
        if v.shape != (3, 3) or not np.isfinite(v).all():
            raise ValueError('Enter exactly three finite calibration triples.')
        a, b, ir = v.T
        if a[0] != .5 or b[0] != 0 or not (np.diff(a) > 0).all():
            raise ValueError('Start at $0.5bn and 0% multi-day orders; subsequent AUM values must increase.')
        if not np.allclose(a*2, np.round(a*2)):
            raise ValueError('Calibration AUM must use $0.5bn increments.')
        if not 0 < b[1] < b[2] <= 100 or not (np.diff(ir) < 0).all():
            raise ValueError('Multi-day percentages must increase within 0–100%; IR must decrease strictly.')
        if not np.isfinite(tracking_error) or tracking_error <= 0:
            raise ValueError('Tracking error must be positive.')
        self.points = v
        self.k = np.log(b[2]/b[1])/np.log((a[2]-a[0])/(a[1]-a[0]))
        self.gamma = np.log((ir[0]-ir[2])/(ir[0]-ir[1]))/np.log(b[2]/b[1])
        self.maximum = float(a[0]+(a[1]-a[0])*(100/b[1])**(1/self.k))
        self.p = SimpleNamespace(aum0=aum0, tracking_error=tracking_error)
        self.samples, self.seed, self.book_size = int(samples), int(seed), book_size
        if not 2 <= self.samples <= 20000 or not 0 <= self.seed <= 2**32-1:
            raise ValueError('Invalid simulation count or seed.')
        if book_size is not None and (int(book_size) != book_size or book_size < 1):
            raise ValueError('Simulation requires a positive integer parent-order count.')
        self.source = 'three-point-alpha-decay'

    def ir_from_percentage(self, b):
        a, pct, ir = self.points.T
        return ir[0]-(ir[0]-ir[1])*(np.asarray(b)/pct[1])**self.gamma

    def metric(self, aum):
        if not np.isfinite(aum) or not .5 <= aum <= self.maximum + 1e-10:
            raise ValueError(f'Alpha-decay curve is defined from $0.5bn to ${self.maximum:.3f}bn (100% multi-day orders).')
        a, b, ir = self.points.T
        pct = min(100., b[1]*((aum-a[0])/(a[1]-a[0]))**self.k)
        net_ir = float(self.ir_from_percentage(pct))
        return {'AUM': aum, 'Multi-day count (%)': pct, 'Net IR': net_ir,
                'Net alpha (%)': net_ir*self.p.tracking_error,
                'Extrapolated': bool(aum > a[-1])}

    def capacity(self, minimum_ir, maximum):
        a, b, ir = self.points.T
        if minimum_ir >= ir[0]:
            return .5
        pct = b[1]*((ir[0]-minimum_ir)/(ir[0]-ir[1]))**(1/self.gamma)
        if pct > 100:
            return None
        crossing = a[0]+(a[1]-a[0])*(pct/b[1])**(1/self.k)
        return float(crossing) if crossing <= min(maximum, self.maximum) else None

    def curve(self, maximum, uncertainty=False):
        maximum = min(maximum, self.maximum)
        grid = np.unique(np.r_[np.linspace(.5, maximum, 121), self.points[:,0][self.points[:,0]<=maximum],
                               [self.p.aum0] if .5<=self.p.aum0<=maximum else []])
        frame = pd.DataFrame([self.metric(a) for a in grid])
        if uncertainty:
            if self.book_size is None:
                raise ValueError('Set the parent-order count to simulate congestion uncertainty.')
            rng = np.random.default_rng(self.seed)
            bounds = []
            for pct in frame['Multi-day count (%)']:
                sampled = 100*rng.binomial(int(self.book_size), pct/100, size=self.samples)/self.book_size
                bounds.append(np.quantile(self.ir_from_percentage(sampled), [.05,.95]))
            bounds = np.asarray(bounds)
            frame['Net IR P05'], frame['Net IR P95'] = bounds.T
            frame['Net alpha P05 (%)'] = bounds[:,0]*self.p.tracking_error
            frame['Net alpha P95 (%)'] = bounds[:,1]*self.p.tracking_error
        return frame
