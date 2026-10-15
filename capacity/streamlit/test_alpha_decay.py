import unittest
import numpy as np
from alpha_decay import AlphaDecayModel, DEFAULT_POINTS

class AlphaDecayTests(unittest.TestCase):
    def test_exact_triples_and_conversion(self):
        model=AlphaDecayModel(DEFAULT_POINTS,tracking_error=1.3)
        for a,b,ir in DEFAULT_POINTS:
            m=model.metric(a)
            self.assertAlmostEqual(m['Multi-day count (%)'],b)
            self.assertAlmostEqual(m['Net IR'],ir)
            self.assertAlmostEqual(m['Net alpha (%)'],ir*1.3)
        self.assertAlmostEqual(model.k,2.041249144646876)
        self.assertAlmostEqual(model.gamma,.7480703635874079)
        self.assertAlmostEqual(model.capacity(.5,6),6)
        self.assertIsNone(model.capacity(.4,6))
        self.assertEqual(model.capacity(.7,6),.5)

    def test_monotonic_valid_domain_and_extrapolation(self):
        model=AlphaDecayModel(DEFAULT_POINTS)
        frame=model.curve(model.maximum)
        self.assertTrue((np.diff(frame['Net IR'])<=0).all())
        self.assertTrue((np.diff(frame['Multi-day count (%)'])>=0).all())
        self.assertAlmostEqual(frame.iloc[-1]['Multi-day count (%)'],100)
        self.assertTrue(model.metric(10)['Extrapolated'])
        self.assertFalse(model.metric(6)['Extrapolated'])
        with self.assertRaises(ValueError): model.metric(model.maximum+1)
        with self.assertRaises(ValueError): model.metric(.4)

    def test_conditional_simulation_reproducible_and_anchor_fixed(self):
        model=AlphaDecayModel(DEFAULT_POINTS,book_size=100,samples=2000)
        a=model.curve(6,True); b=model.curve(6,True)
        np.testing.assert_array_equal(a['Net IR P05'].to_numpy(),b['Net IR P05'].to_numpy())
        self.assertEqual(a.iloc[0]['Net IR P05'],.6)
        self.assertEqual(a.iloc[0]['Net IR P95'],.6)
        self.assertLess(a.iloc[-1]['Net IR P05'],.5)
        self.assertGreater(a.iloc[-1]['Net IR P95'],.5)
        # Central curve preserves calibration despite the nonlinear transformation.
        self.assertAlmostEqual(a.iloc[-1]['Net IR'],.5)
        precise=AlphaDecayModel(DEFAULT_POINTS,book_size=100000,samples=2000).curve(6,True)
        self.assertLess(precise.iloc[-1]['Net IR P95']-precise.iloc[-1]['Net IR P05'],a.iloc[-1]['Net IR P95']-a.iloc[-1]['Net IR P05'])

    def test_invalid_calibrations(self):
        for points in ([[.5,1,.6],[3,2,.57],[6,10,.5]],[[.5,0,.6],[3,2,.6],[6,10,.5]],[[.5,0,.6],[3,20,.57],[6,10,.5]],[[.5,0,.6],[3.1,2,.57],[6,10,.5]]):
            with self.assertRaises(ValueError): AlphaDecayModel(points)
