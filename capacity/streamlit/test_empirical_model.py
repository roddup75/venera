import unittest
from dataclasses import replace
import numpy as np
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
        np.testing.assert_array_equal(frame['Net IR P05'],repeated['Net IR P05'])
        self.assertEqual(frame.iloc[0]['Net IR P05'],.6)
        self.assertEqual(frame.iloc[0]['Net IR P95'],.6)
        self.assertTrue((np.diff(frame['Net IR'])<=0).all())
        self.assertLess(frame.iloc[-1]['Net IR P05'],frame.iloc[-1]['Net IR P95'])
        self.assertAlmostEqual(model.capacity(model.metric(3.45)['Net IR'],6),3.45,places=8)
        self.assertIsNotNone(model.capacity(0,model.maximum))
        self.assertIsNone(model.capacity(.1,3))
        self.assertAlmostEqual(model.tc.metric(model.maximum)['Net alpha (%)'],0,places=8)
        with self.assertRaises(ValueError):model.metric(model.maximum+1)
