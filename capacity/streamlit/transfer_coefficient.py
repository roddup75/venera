"""Independent three-point TC calibration: AUM -> TC -> annual alpha."""
from types import SimpleNamespace
import numpy as np
import pandas as pd

DEFAULT_TC_POINTS = [[60., .5, 1.], [40., 3., .6], [25., 6., .3]]


class TransferCoefficientModel:
    def __init__(self, points, tracking_error=1.3, aum0=.5):
        v = np.asarray(points, float)
        if v.shape != (3,3) or not np.isfinite(v).all():
            raise ValueError('Enter exactly three finite (TC %, AUM $bn, annual alpha %) triples.')
        tc,a,alpha = v.T
        if a[0] != .5 or not (np.diff(a)>0).all() or not np.allclose(a*2,np.round(a*2)):
            raise ValueError('Start at $0.5bn; subsequent AUM values must increase in $0.5bn increments.')
        if not (np.diff(tc)<0).all() or tc[-1]<0 or tc[0]>100:
            raise ValueError('TC must decrease strictly within 0–100%.')
        if not (np.diff(alpha)<0).all():
            raise ValueError('Annual alpha must decrease strictly across the three points.')
        if not np.isfinite(tracking_error) or tracking_error<=0:
            raise ValueError('Tracking error must be positive.')
        self.points = v
        self.k = np.log((tc[0]-tc[2])/(tc[0]-tc[1]))/np.log((a[2]-a[0])/(a[1]-a[0]))
        self.gamma = np.log((alpha[0]-alpha[2])/(alpha[0]-alpha[1]))/np.log((tc[0]-tc[2])/(tc[0]-tc[1]))
        self.maximum = float(a[0]+(a[1]-a[0])*(tc[0]/(tc[0]-tc[1]))**(1/self.k))
        self.p = SimpleNamespace(aum0=aum0,tracking_error=tracking_error)
        self.source='three-point-transfer-coefficient'

    def alpha_from_tc(self, tc_value):
        tc,a,alpha = self.points.T
        return alpha[0]-(alpha[0]-alpha[1])*((tc[0]-np.asarray(tc_value))/(tc[0]-tc[1]))**self.gamma

    def metric(self,aum):
        if not np.isfinite(aum) or not .5<=aum<=self.maximum+1e-10:
            raise ValueError(f'TC curve is defined from $0.5bn to ${self.maximum:.3f}bn (zero TC).')
        tc,a,alpha = self.points.T
        value=max(0.,tc[0]-(tc[0]-tc[1])*((aum-a[0])/(a[1]-a[0]))**self.k)
        annual_alpha=float(self.alpha_from_tc(value))
        return {'AUM':aum,'Transfer coefficient (%)':value,'Net alpha (%)':annual_alpha,
                'Net IR':annual_alpha/self.p.tracking_error,'Extrapolated':bool(aum>a[-1])}

    def capacity(self,minimum_ir,maximum):
        tc,a,alpha = self.points.T
        target=minimum_ir*self.p.tracking_error
        if target>=alpha[0]: return .5
        loss=(tc[0]-tc[1])*((alpha[0]-target)/(alpha[0]-alpha[1]))**(1/self.gamma)
        if loss>tc[0]: return None
        crossing=a[0]+(a[1]-a[0])*(loss/(tc[0]-tc[1]))**(1/self.k)
        return float(crossing) if crossing<=min(maximum,self.maximum)+1e-10 else None

    def curve(self,maximum):
        maximum=min(maximum,self.maximum)
        grid=np.unique(np.r_[np.linspace(.5,maximum,121),self.points[:,1][self.points[:,1]<=maximum],
                             [self.p.aum0] if .5<=self.p.aum0<=maximum else []])
        return pd.DataFrame([self.metric(a) for a in grid])
