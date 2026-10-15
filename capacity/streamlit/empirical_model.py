"""Three calibrated pillars, anchored to gross alpha at current AUM."""
import numpy as np
import pandas as pd
from alpha_decay import AlphaDecayModel
from transfer_coefficient import TransferCoefficientModel
from universe_sampler import create_liquidity_engine
from impact_cost import fit_impact_cost,impact_bps


class EmpiricalIRModel:
    def __init__(self,scenario,alpha_points,tc_points,buckets,trades=None,turnover=13.9,
                 mode='Monte Carlo',samples=2000,seed=2026,adv_points=None,universe_size=300,annual_trades=971):
        self.p=scenario
        self.alpha=AlphaDecayModel(alpha_points,scenario.tracking_error)
        self.tc=TransferCoefficientModel(tc_points,scenario.tracking_error)
        self.shape_initial_ir=float(self.alpha.points[0,2])
        self.initial_tc_alpha=float(self.tc.points[0,2])
        if self.shape_initial_ir<=0 or self.initial_tc_alpha<=0:
            raise ValueError('Combined retention factors require positive initial IR and initial TC alpha.')
        if not np.isfinite(turnover) or turnover<0:
            raise ValueError('One-way annual turnover must be finite and nonnegative.')
        self.turnover=float(turnover)
        self.mode=mode;self.samples=int(samples);self.seed=int(seed)
        self.orders=create_liquidity_engine(scenario,buckets,trades,mode,samples,seed,adv_points,universe_size,annual_trades,turnover)
        self.book_size=self.orders.book_size
        self.fit=fit_impact_cost(buckets)
        self.maximum=min(self.alpha.maximum,self.tc.maximum)
        for model in (self.alpha,self.tc):
            zero=model.capacity(0,self.maximum)
            if zero is not None:self.maximum=min(self.maximum,zero)
        self.source='three-pillar-empirical'
        if not .5 <= scenario.aum0 < self.maximum:
            raise ValueError('Current AUM must lie below the zero-retention boundary to anchor gross alpha.')
        self.anchor_retention=float(self._retention(scenario.aum0))
        if self.anchor_retention<=0:
            raise ValueError('Current AUM requires positive calibrated retention to anchor gross alpha.')
        self.reference_gross_alpha=scenario.gross_alpha/self.anchor_retention
        self.baseline_cost=self.annual_impact(.5)
        self.initial_ir=(self.reference_gross_alpha-self.baseline_cost/100)/scenario.tracking_error

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
        alpha_retention=decay_ir/self.shape_initial_ir
        gross=self.reference_gross_alpha*alpha_retention*retention
        net_ir=(gross-cost/100)/self.p.tracking_error
        reference_gross_ir=self.reference_gross_alpha/self.p.tracking_error
        return {'AUM':aum,'Multi-day count (%)':alpha['Multi-day count (%)'],
                'Transfer coefficient (%)':tc['Transfer coefficient (%)'],
                'Alpha retention (%)':100*alpha_retention,'TC alpha retention (%)':100*retention,
                'Alpha-decay loss (IR)':reference_gross_ir*(1-alpha_retention),
                'TC loss (IR)':reference_gross_ir*alpha_retention*(1-retention),'Impact loss (IR)':cost_ir,
                'Annual impact drag (bp)':cost,'Incremental impact drag (bp)':incremental,
                'Gross alpha (%)':gross,'Net IR':net_ir,'Net alpha (%)':net_ir*self.p.tracking_error,
                'Extrapolated':bool(aum>min(self.alpha.points[-1,0],self.tc.points[-1,1]))}

    def capacity(self,minimum_ir,maximum):
        maximum=self._validate_horizon(maximum)
        if self.metric(.5)['Net IR']<=minimum_ir:return .5
        if self.metric(maximum)['Net IR']>minimum_ir:return None
        lo,hi=.5,maximum
        for _ in range(60):
            mid=(lo+hi)/2
            if self.metric(mid)['Net IR']>minimum_ir:lo=mid
            else:hi=mid
        return hi

    def _validate_horizon(self, maximum):
        if not np.isfinite(maximum) or maximum < .5:
            raise ValueError('Capacity horizon must be finite and at least $500m.')
        return min(float(maximum),self.maximum)

    def _tc_retention(self, aums):
        tc,a,alpha=self.tc.points.T
        value=np.maximum(0.,tc[0]-(tc[0]-tc[1])*((np.asarray(aums)-a[0])/(a[1]-a[0]))**self.tc.k)
        return np.maximum(0.,self.tc.alpha_from_tc(value)/self.initial_tc_alpha)

    def _congestion_probability(self, aums):
        a,b,_=self.alpha.points.T
        return np.clip(b[1]/100*((np.asarray(aums)-a[0])/(a[1]-a[0]))**self.alpha.k,0.,1.)

    def _retention(self,aums):
        alpha=np.maximum(0.,self.alpha.ir_from_percentage(100*self._congestion_probability(aums)))
        return alpha/self.shape_initial_ir*self._tc_retention(aums)

    def _gross_ir(self,aums):
        return self.reference_gross_alpha*self._retention(aums)/self.p.tracking_error

    def _impact_intercept_ir(self):
        return 2*self.turnover/100*self.fit.a/(100*self.p.tracking_error)

    def _impact_coefficients(self):
        if self.mode!='Monte Carlo':
            raise ValueError('Select Monte Carlo to simulate capacity intervals.')
        if not hasattr(self,'_simulation_cost_coefficients'):
            # Full annual costs are deducted once from current-AUM gross alpha.
            costs=self.orders.impact_samples([self.p.aum0],0.,self.fit.b,self.fit.gamma)[:,0]
            self._simulation_cost_coefficients=2*self.turnover/100*costs/(100*self.p.tracking_error)
        return self._simulation_cost_coefficients

    def _paired_ir(self,aums,coefficients):
        # Gross alpha at current AUM is fixed; only trading-book costs vary.
        cost_ir=self._impact_intercept_ir()+coefficients*(np.asarray(aums)/self.p.aum0)**self.fit.gamma
        return self._gross_ir(aums)-cost_ir

    def simulated_curves(self,aums):
        """Return complete, paired, nonincreasing IR paths (samples x AUM).

        Each book is shared across AUM, independent of the plotting grid.
        Only stock selection (or actual-order resampling) varies.
        """
        aums=np.asarray(aums,float)
        if aums.ndim!=1 or not len(aums) or not np.isfinite(aums).all() or np.any(aums<.5) or np.any(aums>self.maximum+1e-10):
            raise ValueError('Simulation AUM must lie within the empirical model domain.')
        coefficients=self._impact_coefficients()
        base_ir=self._gross_ir(aums)
        cost_scale=(aums/self.p.aum0)**self.fit.gamma
        return base_ir[None,:]-self._impact_intercept_ir()-coefficients[:,None]*cost_scale[None,:]

    def capacity_samples(self,minimum_ir,maximum):
        """Solve the first threshold crossing separately for every simulated path.

        Unreached thresholds are right-censored at the chosen horizon, never
        dropped or replaced by an invented crossing at the horizon.
        """
        maximum=self._validate_horizon(maximum)
        if not np.isfinite(minimum_ir):
            raise ValueError('Minimum IR must be finite.')
        coefficients=self._impact_coefficients()
        hi=np.full(self.samples,maximum);lo=np.full(self.samples,.5)
        already=self._paired_ir(lo,coefficients)<=minimum_ir
        reached=self._paired_ir(hi,coefficients)<=minimum_ir
        for _ in range(45):
            mid=(lo+hi)/2
            above=self._paired_ir(mid,coefficients)>minimum_ir
            lo=np.where(above,mid,lo);hi=np.where(above,hi,mid)
        crossing=np.where(already,.5,np.where(reached,hi,np.nan))
        reached=np.isfinite(crossing)
        return pd.DataFrame({'Simulation':np.arange(1,self.samples+1),
                             'AUM at minimum IR (USD bn)':crossing,
                             'Threshold reached':reached,
                             'Capacity lower bound (USD bn)':np.where(reached,crossing,maximum),
                             'Minimum net IR':minimum_ir,'Search horizon (USD bn)':maximum})

    @staticmethod
    def capacity_interval(draws):
        """Empirical inverse-CDF percentiles retain all right-censored draws."""
        if draws.empty:
            raise ValueError('Capacity samples cannot be empty.')
        ordered=np.sort(draws['AUM at minimum IR (USD bn)'].fillna(np.inf).to_numpy(float))
        result={}
        for name,q in [('P20',.2),('P50',.5),('P80',.8)]:
            value=ordered[max(0,int(np.ceil(q*len(ordered)))-1)]
            result[name]=float(value) if np.isfinite(value) else None
        result['Threshold reached (%)']=100*float(draws['Threshold reached'].mean())
        result['Censored simulations']=int((~draws['Threshold reached']).sum())
        return result

    def curve(self,maximum,uncertainty=True):
        maximum=self._validate_horizon(maximum)
        points=np.r_[self.alpha.points[:,0],self.tc.points[:,1],self.p.aum0]
        grid=np.unique(np.r_[np.linspace(.5,maximum,121),points[(points>=.5)&(points<=maximum)]])
        frame=pd.DataFrame([self.metric(float(a)) for a in grid])
        if uncertainty and self.mode=='Monte Carlo':
            low,high=np.quantile(self.simulated_curves(grid),[.2,.8],axis=0)
            frame['Net IR P20']=low;frame['Net IR P80']=high
            frame['Net alpha P20 (%)']=low*self.p.tracking_error
            frame['Net alpha P80 (%)']=high*self.p.tracking_error
        return frame
