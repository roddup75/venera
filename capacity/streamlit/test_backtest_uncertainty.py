import unittest
from statistics import NormalDist
import numpy as np
from backtest_uncertainty import BacktestUncertainty


class BacktestUncertaintyTests(unittest.TestCase):
    def model(self,**kwargs):
        return BacktestUncertainty(.6,.065,1.,3.4,**kwargs)

    def test_gaussian_band_anchor_and_expansion(self):
        m=self.model(sd0=.03,expansion=1.5)
        np.testing.assert_allclose(m.deviation([3.4,6.8,10.2]),.03*np.array([1,2,3])**1.5)
        frame=m.curve([.5,3.4,6.8])
        np.testing.assert_allclose(frame['Backtest net IR P90']-frame['Backtest net IR'],NormalDist().inv_cdf(.9)*m.deviation([.5,3.4,6.8]))
        paths=m.simulated_curves([.5,3.4,6.8])
        residual=(paths-m.mean([.5,3.4,6.8]))/m.deviation([.5,3.4,6.8])
        np.testing.assert_allclose(residual[:,0],residual[:,2],atol=1e-12)
        np.testing.assert_array_equal(paths,self.model(sd0=.03,expansion=1.5).simulated_curves([.5,3.4,6.8]))
        self.assertFalse(np.array_equal(paths,self.model(sd0=.03,expansion=1.5,seed=7).simulated_curves([.5,3.4,6.8])))

    def test_zero_deviation_and_constant_width(self):
        m=self.model(sd0=0)
        draws=m.capacity_samples(.4,15)
        np.testing.assert_allclose(draws['AUM at minimum IR (USD bn)'],(.6-.4)/.065)
        summary=m.capacity_interval(draws)
        self.assertEqual(summary['P10'],summary['P90'])
        np.testing.assert_allclose(self.model(expansion=0).deviation([.5,3.4,15]),.03)

    def test_first_crossings_reconcile_paths_and_censoring(self):
        m=self.model(expansion=2.5,sd0=.1,samples=100)
        draws=m.capacity_samples(.4,15)
        reached=draws['Threshold reached'].to_numpy()
        crossings=draws['AUM at minimum IR (USD bn)'].to_numpy()
        at_start=m.simulated_curves([.5])[:,0]<=.4
        np.testing.assert_array_equal(crossings==.5,at_start)
        interior=reached&~at_start
        values=m.mean(crossings[interior])+m.z[interior]*m.deviation(crossings[interior])
        np.testing.assert_allclose(values,.4,atol=1e-12)
        # Compare against a dense grid, including paths which cross then recover.
        grid=np.linspace(.5,15,20001)
        paths=m.simulated_curves(grid)
        np.testing.assert_array_equal(reached,(paths<=.4).any(axis=1))
        recovered=reached&(paths[:,-1]>.4)&~at_start
        self.assertTrue(recovered.any())
        self.assertTrue(draws.loc[~reached,'AUM at minimum IR (USD bn)'].isna().all())
        all_censored=self.model(sd0=0).capacity_samples(0,3.4)
        self.assertIsNone(m.capacity_interval(all_censored)['P90'])
        self.assertTrue((all_censored['Capacity lower bound (USD bn)']==3.4).all())

    def test_invalid_inputs(self):
        for kwargs in ({'sd0':-1},{'sd0':np.nan},{'expansion':-1},{'expansion':4},{'samples':1},{'samples':2.5},{'seed':-1}):
            with self.assertRaises(ValueError):self.model(**kwargs)
        with self.assertRaises(ValueError):self.model().curve([0])
        with self.assertRaises(ValueError):self.model().capacity_samples(np.nan,15)
