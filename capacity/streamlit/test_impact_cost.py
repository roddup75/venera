import unittest
import numpy as np
import pandas as pd
from impact_cost import fit_impact_cost,impact_bps,impact_curve
from capacity_model import BUCKETS,Scenario,MonteCarloEngine,annual_cost_from_buckets

class ImpactCostTests(unittest.TestCase):
    def test_reproduces_legacy_parameters(self):
        fit=fit_impact_cost(BUCKETS)
        self.assertAlmostEqual(fit.a,0.,places=6)
        self.assertAlmostEqual(fit.b,28.0278856827,places=3)
        self.assertAlmostEqual(fit.gamma,.3858429401,places=5)
        self.assertAlmostEqual(annual_cost_from_buckets(BUCKETS,13.9),2.4167009404,places=8)
        predicted=impact_bps([.01,.1,1.],0,20,.5)
        np.testing.assert_allclose(predicted,[2.,20*np.sqrt(.1),20.])
        # Traded value affects aggregation, not the equal-weight legacy calibration.
        changed=BUCKETS.copy();changed['valueUsdMillion']*=np.arange(1,len(changed)+1)
        self.assertEqual(fit,fit_impact_cost(changed))

    def test_book_costs_and_annual_units(self):
        engine=MonteCarloEngine(Scenario(aum0=1),trades=pd.DataFrame({'q':[1.,9.],'adv':[10.,9.]}),samples=2000,seed=17)
        draws=engine.impact_samples([1.,2.],1.,10.,1.)
        # Exact two-order bootstrap support: both small, one each, both large.
        np.testing.assert_allclose(np.unique(draws[:,0]),[2.,10.1,11.])
        for index in [0,17,1999]:
            book=engine.sampled_book(index,1.)
            costs=impact_bps(book['Order/ADV at selected AUM'],1,10,1)
            self.assertAlmostEqual(draws[index,0],np.dot(book['Sampled notional weight'],costs))
            dollar_cost=np.dot(book['Sampled notional (USD)'],costs)/10000
            self.assertAlmostEqual(dollar_cost/book['Sampled notional (USD)'].sum()*10000,draws[index,0])
        np.testing.assert_allclose(draws[:,1],2*draws[:,0]-1.)
        frame=impact_curve(engine,2,1,10,1,25)
        np.testing.assert_allclose(frame['Annual drag (portfolio bp)'],.5*frame['Mean impact (bp/traded dollar)'])
        np.testing.assert_array_equal(draws,engine.impact_samples([1.,2.],1.,10.,1.))
        np.testing.assert_allclose(impact_curve(engine,2,1,10,1,0)['Annual drag (portfolio bp)'],0)

    def test_invalid_inputs_and_realised_fit(self):
        for x,a,b,g in [([-1],0,1,1),([.1],-1,1,1),([.1],0,1,0)]:
            with self.assertRaises(ValueError): impact_bps(x,a,b,g)
        with self.assertRaises(ValueError): fit_impact_cost(BUCKETS.iloc[:2])
        bad=BUCKETS.copy();bad['realised']=np.nan
        with self.assertRaises(ValueError): fit_impact_cost(bad,'realised')
        self.assertNotEqual(fit_impact_cost(BUCKETS,'realised'),fit_impact_cost(BUCKETS))
