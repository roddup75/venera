"""Gaussian backtest uncertainty with widening, correlated full-curve draws."""
from statistics import NormalDist
import numpy as np
import pandas as pd
from empirical_model import EmpiricalIRModel


class BacktestUncertainty:
    """IR_j(A) = a - b*A**gamma + Z_j*sd0*(A/current_AUM)**expansion.

    A single standard-normal Z per path gives perfectly correlated IR errors
    across AUM. Pointwise marginals are Gaussian; the range reflects supplied
    uncertainty assumptions, not standard errors estimated from observations.
    """
    def __init__(self,a,b,gamma,current_aum,sd0=.03,expansion=1.,samples=2000,seed=2026):
        if not np.isfinite([a,b,gamma,current_aum,sd0,expansion]).all():
            raise ValueError('Backtest uncertainty inputs must be finite.')
        if b<0 or gamma<=0 or current_aum<.5 or sd0<0 or not 0<=expansion<=3:
            raise ValueError('Require nonnegative decay and deviation, positive curvature, AUM ≥ $0.5bn and expansion between 0 and 3.')
        if isinstance(samples,bool) or not isinstance(samples,(int,np.integer)) or not 2<=samples<=20000:
            raise ValueError('Backtest simulation count must be an integer from 2 to 20,000.')
        if isinstance(seed,bool) or not isinstance(seed,(int,np.integer)) or not 0<=seed<=2**32-1:
            raise ValueError('Backtest seed must be an integer from 0 to 2**32−1.')
        self.a,self.b,self.gamma,self.aum0,self.sd0,self.expansion=map(float,[a,b,gamma,current_aum,sd0,expansion])
        self.samples=int(samples)
        # Separate stream from liquidity sampling even with the same user seed.
        self.z=np.random.default_rng(np.random.SeedSequence([int(seed),731])).standard_normal(samples)

    def _aums(self,aums):
        aums=np.asarray(aums,float)
        if not np.isfinite(aums).all() or np.any(aums<.5):
            raise ValueError('Backtest AUM must be finite and at least $0.5bn.')
        return aums

    def mean(self,aums):
        aums=self._aums(aums)
        return self.a-self.b*aums**self.gamma

    def deviation(self,aums):
        aums=self._aums(aums)
        return self.sd0*(aums/self.aum0)**self.expansion

    def curve(self,aums):
        aums=np.atleast_1d(self._aums(aums))
        mean=self.mean(aums);sd=self.deviation(aums)
        width=NormalDist().inv_cdf(.9)*sd
        return pd.DataFrame({'AUM (USD bn)':aums,'Backtest net IR':mean,
                             'Backtest IR standard deviation':sd,
                             'Backtest net IR P10':mean-width,'Backtest net IR P90':mean+width})

    def simulated_curves(self,aums):
        aums=np.atleast_1d(self._aums(aums))
        return self.mean(aums)[None,:]+self.z[:,None]*self.deviation(aums)[None,:]

    def capacity_samples(self,minimum_ir,maximum):
        self._aums([maximum])
        if not np.isfinite(minimum_ir):raise ValueError('Minimum IR must be finite.')
        def ir(a):return self.mean(a)+self.z*self.deviation(a)
        hi=np.full(self.samples,float(maximum))
        # With rapidly expanding uncertainty, optimistic paths can turn upward.
        # Their minimum, rather than their endpoint, determines a first crossing.
        if self.expansion>self.gamma and self.sd0>0 and self.b>0:
            positive=self.z>0
            log_turn=(np.log(self.b*self.gamma)-np.log(self.z[positive]*self.sd0*self.expansion)
                      +self.expansion*np.log(self.aum0))/(self.expansion-self.gamma)
            hi[positive]=np.exp(np.clip(log_turn,np.log(.5),np.log(maximum)))
        lo=np.full(self.samples,.5)
        already=ir(lo)<=minimum_ir
        reached=ir(hi)<=minimum_ir
        for _ in range(50):
            mid=(lo+hi)/2
            above=ir(mid)>minimum_ir
            lo=np.where(above,mid,lo);hi=np.where(above,hi,mid)
        crossing=np.where(already,.5,np.where(reached,hi,np.nan))
        reached=np.isfinite(crossing)
        return pd.DataFrame({'Simulation':np.arange(1,self.samples+1),
                             'AUM at minimum IR (USD bn)':crossing,'Threshold reached':reached,
                             'Capacity lower bound (USD bn)':np.where(reached,crossing,maximum),
                             'Minimum net IR':minimum_ir,'Search horizon (USD bn)':maximum})

    capacity_interval=staticmethod(EmpiricalIRModel.capacity_interval)
