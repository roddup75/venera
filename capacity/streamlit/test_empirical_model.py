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

    def test_current_gross_anchor_full_cost_and_reconciliation(self):
        model=self.model(mode='Deterministic')
        for a in [.5,3.,3.4,6.]:
            m=model.metric(a)
            self.assertAlmostEqual(m['Gross alpha (%)'],Scenario().gross_alpha*float(model._retention(a))/model.anchor_retention)
            self.assertAlmostEqual(m['Net IR'],(m['Gross alpha (%)']-m['Annual impact drag (bp)']/100)/1.3)
            self.assertAlmostEqual(m['Net alpha (%)'],m['Net IR']*1.3)
            self.assertAlmostEqual(model.initial_ir-m['Alpha-decay loss (IR)']-m['TC loss (IR)']-m['Impact loss (IR)'],m['Net IR'])
        self.assertAlmostEqual(model.metric(3.4)['Gross alpha (%)'],.5)
        changed=EmpiricalIRModel(replace(Scenario(),annual_cost_bps=900,half_life=.1),DEFAULT_POINTS,DEFAULT_TC_POINTS,BUCKETS,mode='Deterministic')
        self.assertAlmostEqual(model.metric(3)['Net IR'],changed.metric(3)['Net IR'])
        higher=EmpiricalIRModel(replace(Scenario(),gross_alpha=.63),DEFAULT_POINTS,DEFAULT_TC_POINTS,BUCKETS,mode='Deterministic')
        self.assertAlmostEqual(higher.metric(3.4)['Net IR']-model.metric(3.4)['Net IR'],.1)
        self.assertEqual(higher.metric(3.4)['Annual impact drag (bp)'],model.metric(3.4)['Annual impact drag (bp)'])
        for aum in [.5,6.]:
            anchored=EmpiricalIRModel(replace(Scenario(),aum0=aum),DEFAULT_POINTS,DEFAULT_TC_POINTS,BUCKETS,mode='Deterministic')
            self.assertAlmostEqual(anchored.metric(aum)['Gross alpha (%)'],.5)
        with self.assertRaisesRegex(ValueError,'zero-retention'):
            EmpiricalIRModel(replace(Scenario(),aum0=20),DEFAULT_POINTS,DEFAULT_TC_POINTS,BUCKETS)

    def test_bucket_cost_edit_changes_only_impact_component(self):
        original=self.model(mode='Deterministic')
        changed=BUCKETS.copy();changed['cost']*=2
        model=EmpiricalIRModel(Scenario(),DEFAULT_POINTS,DEFAULT_TC_POINTS,changed,mode='Deterministic')
        base=original.metric(3);now=model.metric(3)
        self.assertAlmostEqual(now['Incremental impact drag (bp)'],2*base['Incremental impact drag (bp)'],places=5)
        self.assertEqual(now['Alpha retention (%)'],base['Alpha retention (%)'])
        self.assertEqual(now['TC alpha retention (%)'],base['TC alpha retention (%)'])
        self.assertLess(now['Net IR'],base['Net IR'])
        self.assertAlmostEqual(model.metric(3.4)['Gross alpha (%)'],original.metric(3.4)['Gross alpha (%)'])

    def test_mc_anchor_reproducibility_monotonicity_and_capacity(self):
        model=self.model(samples=500)
        frame=model.curve(6); repeated=model.curve(6)
        np.testing.assert_array_equal(frame['Net IR P20'],repeated['Net IR P20'])
        self.assertLess(frame.iloc[0]['Net IR P20'],frame.iloc[0]['Net IR P80'])
        self.assertTrue((np.diff(frame['Net IR'])<=0).all())
        start_ir=model.simulated_curves([.5])[:,0]
        threshold=float(np.median(start_ir))
        partial=model.capacity_samples(threshold,6)
        np.testing.assert_array_equal(partial['AUM at minimum IR (USD bn)'].to_numpy()==.5,start_ir<=threshold)
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
        np.testing.assert_allclose(model.capacity_samples(100.,6)['AUM at minimum IR (USD bn)'],.5)
        with self.assertRaises(ValueError):model.capacity_samples(.4,.1)
        with self.assertRaises(ValueError):self.model(mode='Deterministic').capacity_samples(.4,6)

    def test_stock_only_uncertainty_collapses_without_costs(self):
        model=self.model(samples=100,turnover=0)
        paths=model.simulated_curves([.5,3,6])
        np.testing.assert_allclose(paths,np.broadcast_to(paths[0],paths.shape))
        interval=model.capacity_interval(model.capacity_samples(.4,6))
        self.assertEqual(interval['P20'],interval['P80'])
        self.assertAlmostEqual(interval['P50'],model.capacity(.4,6),places=10)

    def test_final_gaussian_ir_uncertainty_is_paired_reproducible_and_independent(self):
        base=self.model(samples=100)
        model=self.model(samples=100,ir_deviation=.03,uncertainty_expansion=1.5)
        aums=np.array([.5,3.4,6.])
        noise=model.simulated_curves(aums)-base.simulated_curves(aums)
        np.testing.assert_allclose(model.ir_standard_deviation([3.4,6.8]),[.03,.03*2**1.5])
        np.testing.assert_allclose(noise/model.ir_standard_deviation(aums),np.broadcast_to(model._ir_shocks()[:,None],noise.shape),atol=1e-12)
        np.testing.assert_array_equal(model.simulated_curves(aums),self.model(samples=100,ir_deviation=.03,uncertainty_expansion=1.5).simulated_curves(aums))
        np.testing.assert_array_equal(base._impact_coefficients(),model._impact_coefficients())
        for a in aums:self.assertEqual(base.metric(a),model.metric(a))
        frame=model.curve(6)
        low,high=np.quantile(model.simulated_curves(frame.AUM),[.2,.8],axis=0)
        np.testing.assert_allclose(frame['Net IR P20'],low)
        np.testing.assert_allclose(frame['Net alpha P80 (%)'],high*model.p.tracking_error)
        for kwargs in ({'ir_deviation':-1},{'uncertainty_expansion':4},{'ir_deviation':np.nan}):
            with self.assertRaises(ValueError):self.model(**kwargs)

    def test_combined_capacity_quantiles_solve_each_path(self):
        model=self.model(samples=100,ir_deviation=.2,uncertainty_expansion=3)
        draws=model.capacity_samples(.2,6)
        crossing=draws['AUM at minimum IR (USD bn)'].to_numpy()
        interior=np.isfinite(crossing)&(crossing>.5)
        np.testing.assert_allclose(model._paired_ir(crossing[interior],model._impact_coefficients()[interior],model._ir_shocks()[interior]),.2,atol=1e-11)
        grid=np.linspace(.5,6,10001)
        below=(model.simulated_curves(grid)<=.2).any(axis=1)
        np.testing.assert_array_equal(draws['Threshold reached'],below)
        expected=np.quantile(np.where(np.isfinite(crossing),crossing,np.inf),[.2,.5,.8],method='inverted_cdf')
        result=model.capacity_interval(draws)
        for key,value in zip(['P20','P50','P80'],expected):
            self.assertEqual(result[key],float(value) if np.isfinite(value) else None)

    def test_hidden_crossing_followed_by_recovery_is_detected(self):
        model=self.model(samples=10,turnover=0,ir_deviation=.1)
        centre=2.345678
        model._gross_ir=lambda a:(np.asarray(a)-centre)**2-1e-10
        model._final_ir_shocks=np.zeros(10)
        draws=model.capacity_samples(0,6)
        self.assertTrue(draws['Threshold reached'].all())
        np.testing.assert_allclose(draws['AUM at minimum IR (USD bn)'],centre-1e-5,atol=1e-9)
