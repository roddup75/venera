import unittest
import tempfile
from pathlib import Path
import numpy as np
from transfer_coefficient import TransferCoefficientModel, DEFAULT_TC_POINTS
from strategy_store import default_strategy, save_strategy, load_strategies
import pandas as pd

class TransferCoefficientTests(unittest.TestCase):
    def test_triples_and_linear_alpha_link(self):
        model=TransferCoefficientModel(DEFAULT_TC_POINTS)
        for tc,a,alpha in DEFAULT_TC_POINTS:
            m=model.metric(a)
            self.assertAlmostEqual(m['Transfer coefficient (%)'],tc)
            self.assertAlmostEqual(m['Net alpha (%)'],alpha)
            self.assertAlmostEqual(m['Net IR'],alpha/1.3)
        self.assertAlmostEqual(model.gamma,1.)
        self.assertAlmostEqual(float(model.alpha_from_tc(50)),.8)
        self.assertAlmostEqual(model.capacity(.6/1.3,6),3.)
        self.assertIsNone(model.capacity(0,6))

    def test_domain_monotonicity_and_curved_alpha_link(self):
        model=TransferCoefficientModel([[60,.5,1],[40,3,.6],[25,6,.2]])
        frame=model.curve(model.maximum)
        self.assertNotAlmostEqual(model.gamma,1.)
        self.assertTrue((np.diff(frame['Transfer coefficient (%)'])<=0).all())
        self.assertTrue((np.diff(frame['Net alpha (%)'])<=0).all())
        self.assertAlmostEqual(frame.iloc[-1]['Transfer coefficient (%)'],0.)
        self.assertTrue(model.metric(7)['Extrapolated'])
        with self.assertRaises(ValueError): model.metric(model.maximum+1)
        with self.assertRaises(ValueError): model.metric(.4)

    def test_invalid_and_save_reload(self):
        for points in ([[60,.5,1],[70,3,.6],[25,6,.3]],[[101,.5,1],[40,3,.6],[25,6,.3]],[[60,.5,1],[40,3,.6],[25,6,.7]],[[60,1,1],[40,3,.6],[25,6,.3]]):
            with self.assertRaises(ValueError): TransferCoefficientModel(points)
        strategy=default_strategy()
        params={**strategy['parameters'],'model_kind':'Three-pillar empirical','tc_points':[[60,.5,1],[40,3,.6],[25,6,.2]]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'strategies.json'
            save_strategy('TC',params,pd.DataFrame(strategy['buckets']),path=path)
            loaded=load_strategies(path)['TC']
            self.assertEqual(loaded['parameters']['tc_points'],params['tc_points'])
            self.assertEqual(loaded['parameters']['model_kind'],params['model_kind'])
            self.assertEqual(loaded['methodology'],'three-pillar-calibrated-books-v5')
