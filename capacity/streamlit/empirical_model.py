"""Three calibrated pillars, anchored to net IR at $500m."""
import numpy as np
import pandas as pd
from alpha_decay import AlphaDecayModel
from transfer_coefficient import TransferCoefficientModel
from capacity_model import create_engine
from impact_cost import fit_impact_cost,impact_bps


class EmpiricalIRModel:
    def __init__(self,scenario,alpha_points,tc_points,buckets,trades=None,turnover=13.9,
                 mode='Monte Carlo',samples=2000,seed=2026):
        self.p=scenario
        self.alpha=AlphaDecayModel(alpha_points,scenario.tracking_error)
        self.tc=TransferCoefficientModel(tc_points,scenario.tracking_error)
        self.initial_ir=float(self.alpha.points[0,2])
        self.initial_tc_alpha=float(self.tc.points[0,2])
        if self.initial_ir<=0 or self.initial_tc_alpha<=0:
            raise ValueError('Combined retention factors require positive initial IR and initial TC alpha.')
        if not np.isfinite(turnover) or turnover<0:
            raise ValueError('One-way annual turnover must be finite and nonnegative.')
        self.turnover=float(turnover)
        self.mode=mode;self.samples=int(samples);self.seed=int(seed)
        self.orders=create_engine(scenario,buckets,trades,mode,samples,seed)
        self.book_size=len(trades) if trades is not None else max(1,int(round(buckets.trades.sum())))
        self.fit=fit_impact_cost(buckets)
        self.maximum=min(self.alpha.maximum,self.tc.maximum)
        for model in (self.alpha,self.tc):
            zero=model.capacity(0,self.maximum)
            if zero is not None:self.maximum=min(self.maximum,zero)
        self.source='three-pillar-empirical'
        self.baseline_cost=self.annual_impact(.5)

    def annual_impact(self,aum):
        costs=impact_bps(self.orders.x*aum/self.p.aum0,self.fit.a,self.fit.b,self.fit.gamma)
        return float(2*self.turnover/100*np.dot(self.orders.weights,costs))

    def metric(self,aum):
        if not np.isfinite(aum) or not .5<=aum<=self.maximum+1e-10:
            raise ValueError(f'Empirical IR is defined from $0.5bn to ${self.maximum:.3f}bn, where a retention factor reaches zero.')
        alpha=self.alpha.metric(aum);tc=self.tc.metric(aum)
        retention=max(0.,tc['Net alpha (%)']/self.initial_tc_alpha)
        decay_ir=max(0.,alpha['Net IR'])
        cost=self.annual_impact(aum);incremental=cost-self.baseline_cost
        cost_ir=incremental/(100*self.p.tracking_error)
        net_ir=decay_ir*retention-cost_ir
        return {'AUM':aum,'Multi-day count (%)':alpha['Multi-day count (%)'],
                'Transfer coefficient (%)':tc['Transfer coefficient (%)'],
                'Alpha retention (%)':100*decay_ir/self.initial_ir,'TC alpha retention (%)':100*retention,
                'Alpha-decay loss (IR)':self.initial_ir-decay_ir,
                'TC loss (IR)':decay_ir*(1-retention),'Impact loss (IR)':cost_ir,
                'Annual impact drag (bp)':cost,'Incremental impact drag (bp)':incremental,
                'Net IR':net_ir,'Net alpha (%)':net_ir*self.p.tracking_error,
                'Extrapolated':bool(aum>min(self.alpha.points[-1,0],self.tc.points[-1,1]))}

    def capacity(self,minimum_ir,maximum):
        maximum=min(maximum,self.maximum)
        if self.metric(.5)['Net IR']<=minimum_ir:return .5
        if self.metric(maximum)['Net IR']>minimum_ir:return None
        lo,hi=.5,maximum
        for _ in range(60):
            mid=(lo+hi)/2
            if self.metric(mid)['Net IR']>minimum_ir:lo=mid
            else:hi=mid
        return hi

    def curve(self,maximum,uncertainty=True):
        maximum=min(maximum,self.maximum)
        points=np.r_[self.alpha.points[:,0],self.tc.points[:,1],self.p.aum0]
        grid=np.unique(np.r_[np.linspace(.5,maximum,121),points[(points>=.5)&(points<=maximum)]])
        frame=pd.DataFrame([self.metric(float(a)) for a in grid])
        if uncertainty and self.mode=='Monte Carlo':
            # The same bootstrap book prices all AUMs, including the $500m cost anchor.
            cost_draws=self.orders.impact_samples(np.r_[.5,grid],self.fit.a,self.fit.b,self.fit.gamma)
            delta=2*self.turnover/100*(cost_draws[:,1:]-cost_draws[:,[0]])
            # Independent congestion-count uncertainty conditional on the fitted share.
            congestion_rng=np.random.default_rng(np.random.SeedSequence([self.seed,1]))
            low=[];high=[]
            for j,(_,row) in enumerate(frame.iterrows()):
                counts=congestion_rng.binomial(self.book_size,row['Multi-day count (%)']/100,size=self.samples)
                decay=np.maximum(0.,self.alpha.ir_from_percentage(100*counts/self.book_size))
                tc_retention=row['TC alpha retention (%)']/100
                draws=decay*tc_retention-delta[:,j]/(100*self.p.tracking_error)
                bounds=np.quantile(draws,[.05,.95]);low.append(bounds[0]);high.append(bounds[1])
            frame['Net IR P05']=low;frame['Net IR P95']=high
            frame['Net alpha P05 (%)']=frame['Net IR P05']*self.p.tracking_error
            frame['Net alpha P95 (%)']=frame['Net IR P95']*self.p.tracking_error
        return frame
