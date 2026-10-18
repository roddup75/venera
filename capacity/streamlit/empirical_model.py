"""Three calibrated pillars, anchored to gross alpha at current AUM."""
import numpy as np
import pandas as pd
from alpha_decay import AlphaDecayModel
from transfer_coefficient import TransferCoefficientModel
from universe_sampler import create_liquidity_engine
from impact_cost import fit_impact_cost,impact_bps


class EmpiricalIRModel:
    def __init__(self,scenario,alpha_points,tc_points,buckets,trades=None,turnover=13.9,
                 mode='Monte Carlo',samples=2000,seed=2026,adv_points=None,universe_size=300,annual_trades=971,ir_deviation=0.,uncertainty_expansion=1.):
        if not np.isfinite([ir_deviation,uncertainty_expansion]).all() or ir_deviation<0 or not 0<=uncertainty_expansion<=3:
            raise ValueError('Final empirical IR deviation must be nonnegative and expansion between 0 and 3.')
        self.ir_deviation=float(ir_deviation)
        self.uncertainty_expansion=float(uncertainty_expansion)
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
        self.maximum=min(self.alpha.maximum,self.tc.maximum)
        for model in (self.alpha,self.tc):
            zero=model.capacity(0,self.maximum)
            if zero is not None:self.maximum=min(self.maximum,zero)
        self.source='three-pillar-empirical'
        if not .5 <= scenario.aum0 < self.maximum:
            raise ValueError('Current AUM must lie below the zero-retention boundary to anchor gross alpha.')
        self.orders=create_liquidity_engine(scenario,buckets,trades,mode,samples,seed,adv_points,universe_size,annual_trades,turnover)
        self.book_size=self.orders.book_size
        self.fit=fit_impact_cost(buckets)
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

    def ir_standard_deviation(self,aums):
        return self.ir_deviation*(np.asarray(aums)/self.p.aum0)**self.uncertainty_expansion

    def _ir_shocks(self):
        if not hasattr(self,'_final_ir_shocks'):
            self._final_ir_shocks=np.random.default_rng(np.random.SeedSequence([self.seed,1291])).standard_normal(self.samples)
        return self._final_ir_shocks

    def _paired_ir(self,aums,coefficients,shocks=None):
        cost_ir=self._impact_intercept_ir()+coefficients*(np.asarray(aums)/self.p.aum0)**self.fit.gamma
        shocks=self._ir_shocks() if shocks is None else shocks
        return self._gross_ir(aums)-cost_ir+shocks*self.ir_standard_deviation(aums)

    def simulated_curves(self,aums):
        """Return complete paired IR paths (samples x AUM).

        Each book is shared across AUM, independent of the plotting grid.
        An independent Gaussian final-IR shock is reused across AUM when enabled.
        """
        aums=np.asarray(aums,float)
        if aums.ndim!=1 or not len(aums) or not np.isfinite(aums).all() or np.any(aums<.5) or np.any(aums>self.maximum+1e-10):
            raise ValueError('Simulation AUM must lie within the empirical model domain.')
        coefficients=self._impact_coefficients()
        base_ir=self._gross_ir(aums)
        cost_scale=(aums/self.p.aum0)**self.fit.gamma
        return (base_ir[None,:]-self._impact_intercept_ir()-coefficients[:,None]*cost_scale[None,:]
                +self._ir_shocks()[:,None]*self.ir_standard_deviation(aums)[None,:])

    def _first_crossing_brackets(self,minimum_ir,maximum,coefficients):
        """Scan for first crossings, refining every intervening local minimum.

        Gaussian perturbations can make optimistic paths turn upward. Inspect
        a shared 1,025-point grid plus calibration knots, then refine local
        minima with golden-section search before bisection of the first root.
        """
        grid=np.unique(np.r_[np.linspace(.5,maximum,1025),self.alpha.points[:,0],self.tc.points[:,1],self.p.aum0])
        grid=grid[(grid>=.5)&(grid<=maximum)]
        shocks=self._ir_shocks()
        lo=np.full(self.samples,.5);hi=np.full(self.samples,maximum)
        reached=np.zeros(self.samples,dtype=bool)
        batch=max(1,min(128,500000//len(grid)))
        golden=(np.sqrt(5)-1)/2
        for start in range(0,self.samples,batch):
            stop=min(start+batch,self.samples)
            c=coefficients[start:stop];z=shocks[start:stop]
            values=self._paired_ir(grid[None,:],c[:,None],z[:,None])
            below=values<=minimum_ir
            found=below.any(axis=1)
            first=np.where(found,below.argmax(axis=1),len(grid)-1)
            local_lo=grid[np.maximum(first-1,0)].copy();local_hi=grid[first].copy()
            # A crossing followed by recovery may lie between two above-threshold
            # grid points. Refine all local minima preceding the detected root.
            minima=(values[:,1:-1]<values[:,:-2])&(values[:,1:-1]<=values[:,2:])
            rows,indices=np.nonzero(minima)
            indices+=1
            keep=(~found[rows])|(indices<first[rows])
            rows=rows[keep];indices=indices[keep]
            if len(rows):
                left=grid[indices-1].copy();right=grid[indices+1].copy()
                x1=right-golden*(right-left);x2=left+golden*(right-left)
                f1=self._paired_ir(x1,c[rows],z[rows]);f2=self._paired_ir(x2,c[rows],z[rows])
                for _ in range(40):
                    choose_left=f1<=f2
                    right=np.where(choose_left,x2,right)
                    left=np.where(choose_left,left,x1)
                    x1=right-golden*(right-left);x2=left+golden*(right-left)
                    f1=self._paired_ir(x1,c[rows],z[rows]);f2=self._paired_ir(x2,c[rows],z[rows])
                minimum=(left+right)/2
                valid=self._paired_ir(minimum,c[rows],z[rows])<=minimum_ir
                rows=rows[valid];indices=indices[valid];minimum=minimum[valid]
                # Keep the earliest qualifying minimum for each simulated path.
                order=np.lexsort((minimum,rows))
                _,positions=np.unique(rows[order],return_index=True)
                chosen=order[positions]
                r=rows[chosen]
                local_lo[r]=grid[indices[chosen]-1];local_hi[r]=minimum[chosen];found[r]=True
            lo[start:stop]=local_lo;hi[start:stop]=local_hi;reached[start:stop]=found
        return lo,hi,reached

    def capacity_samples(self,minimum_ir,maximum):
        """Solve the first threshold crossing separately for every simulated path.

        Unreached thresholds are right-censored at the chosen horizon, never
        dropped or replaced by an invented crossing at the horizon.
        """
        maximum=self._validate_horizon(maximum)
        if not np.isfinite(minimum_ir):
            raise ValueError('Minimum IR must be finite.')
        coefficients=self._impact_coefficients()
        already=self._paired_ir(np.full(self.samples,.5),coefficients)<=minimum_ir
        if self.ir_deviation>0:
            lo,hi,reached=self._first_crossing_brackets(minimum_ir,maximum,coefficients)
        else:
            hi=np.full(self.samples,maximum);lo=np.full(self.samples,.5)
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
        for name,q in [('P10',.1),('P50',.5),('P90',.9)]:
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
            low,high=np.quantile(self.simulated_curves(grid),[.1,.9],axis=0)
            frame['Net IR P10']=low;frame['Net IR P90']=high
            frame['Net alpha P10 (%)']=low*self.p.tracking_error
            frame['Net alpha P90 (%)']=high*self.p.tracking_error
        return frame
