import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from capacity_model import Scenario,BUCKETS
from alpha_decay import DEFAULT_POINTS
from transfer_coefficient import DEFAULT_TC_POINTS
from empirical_model import EmpiricalIRModel

class EmpiricalModelTests(unittest.TestCase):
    def model(self,**kwargs):
        return EmpiricalIRModel(Scenario(),DEFAULT_POINTS,DEFAULT_TC_POINTS,BUCKETS,**kwargs)

    def test_multiplication_incremental_cost_and_reconciliation(self):
        model=self.model(mode='Deterministic')
        start=model.metric(.5)
        self.assertAlmostEqual(start['Net IR'],.6)
        self.assertEqual(start['Incremental impact drag (bp)'],0)
        for a in [3.,6.]:
            m=model.metric(a)
            before_cost={3.:.57*.6,6.:.5*.3}[a]
            self.assertAlmostEqual(m['Net IR'],before_cost-m['Incremental impact drag (bp)']/130)
            self.assertAlmostEqual(m['Net alpha (%)'],m['Net IR']*1.3)
            self.assertAlmostEqual(.6-m['Alpha-decay loss (IR)']-m['TC loss (IR)']-m['Impact loss (IR)'],m['Net IR'])
        # Legacy cost and half-life do not enter this newly calibrated model.
        changed=EmpiricalIRModel(replace(Scenario(),annual_cost_bps=900,half_life=.1,gross_alpha=7),DEFAULT_POINTS,DEFAULT_TC_POINTS,BUCKETS,mode='Deterministic')
        self.assertAlmostEqual(model.metric(3)['Net IR'],changed.metric(3)['Net IR'])
        self.assertAlmostEqual(self.model(mode='Deterministic',turnover=0).metric(3)['Net IR'],.342)

    def test_bucket_cost_edit_changes_only_impact_component(self):
        original=self.model(mode='Deterministic')
        changed=BUCKETS.copy();changed['cost']*=2
        model=EmpiricalIRModel(Scenario(),DEFAULT_POINTS,DEFAULT_TC_POINTS,changed,mode='Deterministic')
        base=original.metric(3);now=model.metric(3)
        self.assertAlmostEqual(now['Incremental impact drag (bp)'],2*base['Incremental impact drag (bp)'],places=5)
        self.assertEqual(now['Alpha retention (%)'],base['Alpha retention (%)'])
        self.assertEqual(now['TC alpha retention (%)'],base['TC alpha retention (%)'])
        self.assertLess(now['Net IR'],base['Net IR'])
        self.assertAlmostEqual(model.metric(.5)['Net IR'],.6)

    def test_mc_anchor_reproducibility_monotonicity_and_capacity(self):
        model=self.model(samples=500)
        frame=model.curve(6); repeated=model.curve(6)
        np.testing.assert_array_equal(frame['Net IR P20'],repeated['Net IR P20'])
        self.assertEqual(frame.iloc[0]['Net IR P20'],.6)
        self.assertEqual(frame.iloc[0]['Net IR P80'],.6)
        self.assertTrue((np.diff(frame['Net IR'])<=0).all())
        self.assertLess(frame.iloc[-1]['Net IR P20'],frame.iloc[-1]['Net IR P80'])
        self.assertAlmostEqual(model.capacity(model.metric(3.45)['Net IR'],6),3.45,places=8)
        self.assertIsNotNone(model.capacity(0,model.maximum))
        self.assertIsNone(model.capacity(.1,3))
        self.assertAlmostEqual(model.tc.metric(model.maximum)['Net alpha (%)'],0,places=8)
        with self.assertRaises(ValueError):model.metric(model.maximum+1)

    def test_capacity_draws_solve_each_full_path_and_reproduce_quantiles(self):
        model=self.model(samples=100)
        draws=model.capacity_samples(.4,6)
        pd.testing.assert_frame_equal(draws,model.capacity_samples(.4,6))
        capacity=draws['AUM at minimum IR (USD bn)'].to_numpy()
        coefficients=model._impact_coefficients()
        self.assertTrue(draws['Threshold reached'].all())
        np.testing.assert_allclose(model._paired_ir(capacity,coefficients),.4,atol=1e-12)
        interval=model.capacity_interval(draws)
        expected=np.quantile(capacity,[.2,.5,.8],method='inverted_cdf')
        np.testing.assert_allclose([interval[k] for k in ('P20','P50','P80')],expected)
        self.assertLess(interval['P20'],interval['P80'])
        self.assertEqual(interval['Censored simulations'],0)
        path=model.simulated_curves([.5,2,4,6])
        self.assertTrue((np.diff(path,axis=1)<=0).all())
        np.testing.assert_array_equal(path,model.simulated_curves([.5,1,2,3,4,5,6])[:,[0,2,4,6]])
        frame=model.curve(6)
        np.testing.assert_allclose(frame['Net IR P20'],np.quantile(model.simulated_curves(frame.AUM),.2,axis=0))
        np.testing.assert_allclose(frame['Net IR P80'],np.quantile(model.simulated_curves(frame.AUM),.8,axis=0))
        np.testing.assert_allclose(frame['Net IR'],model.simulated_curves(frame.AUM).mean(axis=0),atol=1e-12)

    def test_censoring_is_preserved_instead_of_dropping_non_crossings(self):
        model=self.model(samples=100)
        full=model.capacity_samples(.4,6)
        horizon=float(full['AUM at minimum IR (USD bn)'].quantile(.3))
        limited=model.capacity_samples(.4,horizon)
        interval=model.capacity_interval(limited)
        self.assertIsNotNone(interval['P20'])
        self.assertIsNone(interval['P50'])
        self.assertIsNone(interval['P80'])
        self.assertEqual(interval['Censored simulations'],70)
        self.assertTrue(limited.loc[~limited['Threshold reached'],'AUM at minimum IR (USD bn)'].isna().all())
        self.assertTrue((limited.loc[~limited['Threshold reached'],'Capacity lower bound (USD bn)']==horizon).all())
        none=model.capacity_interval(model.capacity_samples(.1,.5))
        self.assertEqual(none['Threshold reached (%)'],0)
        self.assertIsNone(none['P20'])
        np.testing.assert_allclose(model.capacity_samples(.6,6)['AUM at minimum IR (USD bn)'],.5)
        with self.assertRaises(ValueError):model.capacity_samples(.4,.1)
        with self.assertRaises(ValueError):self.model(mode='Deterministic').capacity_samples(.4,6)

    def test_stock_only_uncertainty_collapses_without_costs(self):
        model=self.model(samples=100,turnover=0)
        paths=model.simulated_curves([.5,3,6])
        np.testing.assert_allclose(paths,np.broadcast_to(paths[0],paths.shape))
        interval=model.capacity_interval(model.capacity_samples(.4,6))
        self.assertEqual(interval['P20'],interval['P80'])
        self.assertAlmostEqual(interval['P50'],model.capacity(.4,6),places=10)
