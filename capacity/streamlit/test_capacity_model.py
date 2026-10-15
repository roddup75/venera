import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from capacity_model import ExecutionEngine, Scenario, alpha_capture, curve, validate_trades


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tape = pd.DataFrame({'q': [1., 9.], 'adv': [10., 9.]})
        self.p = Scenario(aum0=1, gross_alpha=3, tracking_error=2,
                          daily_participation=20, half_life=10, annual_cost_bps=22.5)
        self.engine = ExecutionEngine(self.p, trades=self.tape)

    def test_capture_integral_and_zero_limit(self):
        np.testing.assert_allclose(alpha_capture([0, 1e-13], 10), [1, 1], atol=1e-13)
        self.assertAlmostEqual(float(alpha_capture(10, 10)), .5/np.log(2))
        with self.assertRaises(ValueError):
            alpha_capture(1, 0)

    def test_weighted_aggregate_normalization_not_average_ratios(self):
        g0 = .1*alpha_capture(.5, 10) + .9*alpha_capture(5, 10)
        g2 = .1*alpha_capture(1, 10) + .9*alpha_capture(10, 10)
        result = self.engine.metric(2)
        self.assertAlmostEqual(result['Alpha capture (%)'], 100*g2/g0)
        self.assertAlmostEqual(result['Net alpha (%)'], 3*g2/g0-.225)
        self.assertAlmostEqual(result['Net IR'], (3*g2/g0-.225)/2)
        average_ratios = .1*alpha_capture(1,10)/alpha_capture(.5,10) + .9*alpha_capture(10,10)/alpha_capture(5,10)
        self.assertGreater(abs(g2/g0-average_ratios), 1e-4)

    def test_baseline_cost_and_monotone_capture(self):
        self.assertEqual(self.engine.metric(1)['Alpha capture (%)'], 100)
        self.assertAlmostEqual(self.engine.metric(1)['Net alpha (%)'], 2.775)
        results = [self.engine.metric(s) for s in [1,2,5,100]]
        self.assertTrue(all(a['Net IR'] > b['Net IR'] for a,b in zip(results,results[1:])))
        self.assertTrue(all(r['Annual drag (bp)'] == 22.5 for r in results))
        self.assertGreater(results[-1]['Average days'], 100)

    def test_fractional_days_and_weighting(self):
        result = self.engine.metric(1)
        self.assertAlmostEqual(result['Average days'], 4.55)
        self.assertAlmostEqual(result['Multi-day (%)'], 90)
        self.assertAlmostEqual(result['Multi-day count (%)'], 50)
        self.assertEqual(self.engine.contributions(1).iloc[0]['Execution days'], .5)

    def test_cost_stress_and_zero_alpha(self):
        stress = ExecutionEngine(replace(self.p, cost_elasticity=.5), trades=self.tape)
        self.assertAlmostEqual(stress.metric(4)['Annual drag (bp)'], 45)
        zero = ExecutionEngine(replace(self.p, gross_alpha=0), trades=self.tape)
        self.assertTrue(np.isnan(zero.metric(1)['Retained alpha (%)']))
        self.assertEqual(zero.capacity(0, 10), .5)

    def test_capacity_bisection_and_horizon(self):
        threshold = self.engine.metric(2.345)['Net IR']
        self.assertAlmostEqual(self.engine.capacity(threshold,10), 2.345, places=9)
        self.assertIsNone(self.engine.capacity(threshold,2))
        self.assertEqual(self.engine.capacity(2,10),.5)
        self.assertEqual(curve(self.engine,3).iloc[0]['AUM'],.5)
        with self.assertRaises(ValueError):
            curve(self.engine,.5)

    def test_500m_floor_preserves_anchor_and_searches_below_current_aum(self):
        frame=curve(self.engine,3)
        self.assertEqual(frame.iloc[0]['AUM'],.5)
        self.assertIn(self.p.aum0,frame.AUM.to_numpy())
        self.assertEqual(self.engine.metric(self.p.aum0)['Alpha capture (%)'],100)
        threshold=self.engine.metric(.75)['Net IR']
        self.assertAlmostEqual(self.engine.capacity(threshold,3),.75,places=9)
        self.assertGreater(self.engine.metric(.5)['Alpha capture (%)'],100)
        for operation in (lambda:self.engine.metric(.49),lambda:self.engine.contributions(.49),lambda:self.engine.capacity(0,.49),lambda:ExecutionEngine(replace(self.p,aum0=.49),trades=self.tape)):
            with self.assertRaises(ValueError):
                operation()

    def test_trade_validation(self):
        for frame in [pd.DataFrame(), pd.DataFrame({'q':[1], 'adv':[0]}),
                      pd.DataFrame({'q':[np.inf], 'adv':[1]}),
                      pd.DataFrame({'q':['bad'], 'adv':[1]})]:
            with self.subTest(frame=frame):
                with self.assertRaises(ValueError):
                    validate_trades(frame)
        for params in [replace(self.p, daily_participation=0), replace(self.p, half_life=-1),
                       replace(self.p, annual_cost_bps=-1), replace(self.p, tracking_error=0)]:
            with self.assertRaises(ValueError):
                ExecutionEngine(params, trades=self.tape)

    def test_bucket_values_not_rounded_shares_or_counts_determine_capture(self):
        from capacity_model import BUCKETS
        buckets=BUCKETS.copy()
        original=ExecutionEngine(self.p,buckets).metric(3)
        buckets['share']=0
        buckets['trades'] *= np.arange(1,len(buckets)+1)
        changed=ExecutionEngine(self.p,buckets).metric(3)
        self.assertAlmostEqual(original['Alpha capture (%)'], changed['Alpha capture (%)'])
        self.assertAlmostEqual(original['Average days'], changed['Average days'])
        buckets.loc[0,'p'] = 2
        with self.assertRaises(ValueError):
            ExecutionEngine(self.p,buckets)



class MonteCarloTests(unittest.TestCase):
    def setUp(self):
        from capacity_model import MonteCarloEngine
        self.cls = MonteCarloEngine
        self.p = Scenario(aum0=1, gross_alpha=3, tracking_error=2,
                          daily_participation=20, half_life=10, annual_cost_bps=22.5)
        self.tape = pd.DataFrame({'q':[1.,9.], 'adv':[10.,9.]})

    def test_mean_and_percentiles_against_enumerated_two_order_books(self):
        engine=self.cls(self.p, trades=self.tape, samples=20000, seed=123)
        a=float(alpha_capture(1,10)/alpha_capture(.5,10))
        b=float(alpha_capture(10,10)/alpha_capture(5,10))
        mixed=float((.1*alpha_capture(1,10)+.9*alpha_capture(10,10))/(.1*alpha_capture(.5,10)+.9*alpha_capture(5,10)))
        expected=.25*a+.25*b+.5*mixed
        self.assertAlmostEqual(engine.metric(2)['Alpha capture (%)']/100,expected,delta=.002)
        bounds=engine.intervals([1,2])
        self.assertAlmostEqual(bounds.iloc[1]['Alpha capture P05 (%)'],100*min(a,b,mixed))
        self.assertAlmostEqual(bounds.iloc[1]['Alpha capture P95 (%)'],100*max(a,b,mixed))
        self.assertEqual(bounds.iloc[0]['Alpha capture P05 (%)'],100)
        self.assertEqual(bounds.iloc[0]['Alpha capture P95 (%)'],100)
        self.assertAlmostEqual(bounds.iloc[0]['Net alpha P05 (%)'],2.775)
        self.assertAlmostEqual(bounds.iloc[1]['Net IR P05'],(3*min(a,b,mixed)-.225)/2)

    def test_seed_reproducibility_and_capacity_uses_same_mean_books(self):
        a=self.cls(self.p,trades=self.tape,samples=500,seed=5)
        b=self.cls(self.p,trades=self.tape,samples=500,seed=5)
        pd.testing.assert_frame_equal(curve(a,4),curve(b,4))
        target=a.metric(2.345)['Net IR']
        self.assertAlmostEqual(a.capacity(target,10),2.345,places=9)
        self.assertGreater(a.metric(1)['Net IR'],a.metric(4)['Net IR'])

    def test_identical_ratios_have_no_compositional_uncertainty(self):
        tape=pd.DataFrame({'q':[1.,9.], 'adv':[10.,90.]})
        engine=self.cls(self.p,trades=tape,samples=500)
        deterministic=ExecutionEngine(self.p,trades=tape)
        bounds=engine.intervals([1,2,4])
        np.testing.assert_allclose(bounds['Net IR P05'],bounds['Net IR P95'],atol=1e-12)
        self.assertAlmostEqual(engine.metric(4)['Net IR'],deterministic.metric(4)['Net IR'])

    def test_sample_count_changes_precision_not_distribution_width(self):
        widths=[]
        for samples in (1000,10000):
            bounds=self.cls(self.p,trades=self.tape,samples=samples).intervals([2]).iloc[0]
            widths.append(bounds['Net IR P95']-bounds['Net IR P05'])
        self.assertGreater(widths[0],0)
        self.assertAlmostEqual(widths[0],widths[1])

    def test_sampled_book_inspection_reuses_seeded_orders_and_scales_dollars(self):
        engine=self.cls(self.p,trades=self.tape,samples=200)
        book=engine.sampled_book(5,1)
        repeat=engine.sampled_book(5,1)
        doubled=engine.sampled_book(5,2)
        pd.testing.assert_frame_equal(book,repeat)
        self.assertEqual(book['Sampled orders'].sum(),2)
        self.assertAlmostEqual(book['Sampled notional weight'].sum(),1)
        np.testing.assert_array_equal(book['Sampled orders'],doubled['Sampled orders'])
        np.testing.assert_allclose(2*book['Sampled notional (USD)'],doubled['Sampled notional (USD)'])
        np.testing.assert_allclose(2*book['Execution days'],doubled['Execution days'])
        self.assertAlmostEqual(book['Sampled notional (USD)'].sum(),float(np.dot(book['Sampled orders'],self.tape.q)))
        for index,aum in ((200,1),(1,.49)):
            with self.assertRaises(ValueError):
                engine.sampled_book(index,aum)
        with self.assertRaises(ValueError):
            engine.intervals([.49,1])

    def test_bucket_order_count_and_invalid_simulation_parameters(self):
        from capacity_model import BUCKETS, create_engine
        self.assertIsInstance(create_engine(self.p),self.cls)
        engine=self.cls(self.p)
        self.assertEqual(engine.book_size,round(BUCKETS.trades.sum()))
        for kw in ({'samples':0},{'samples':2.5},{'samples':True},{'seed':-1}):
            with self.assertRaises(ValueError):
                self.cls(self.p,trades=self.tape,**kw)
        buckets=BUCKETS.copy();buckets.loc[0,'trades']=0
        with self.assertRaisesRegex(ValueError,'positive traded value'):
            self.cls(self.p,buckets=buckets)

if __name__ == '__main__':
    unittest.main()
