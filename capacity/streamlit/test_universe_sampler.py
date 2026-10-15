import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from capacity_model import Scenario, BUCKETS
from universe_sampler import ADV_POINTS, universe_adv, create_liquidity_engine
from bucket_sampler import bucket_migration
from impact_cost import impact_bps
from empirical_model import EmpiricalIRModel
from alpha_decay import DEFAULT_POINTS
from transfer_coefficient import DEFAULT_TC_POINTS


class UniverseSamplerTests(unittest.TestCase):
    def engine(self, **kwargs):
        return create_liquidity_engine(Scenario(), BUCKETS, samples=100, **kwargs)

    def test_percentile_interpolation_and_validation(self):
        adv=universe_adv(pd.DataFrame({'percentile':[0,100],'advUsd':[100.,10000.]}),2)
        np.testing.assert_allclose(adv,[100*np.sqrt(10),1000*np.sqrt(10)])
        self.assertEqual(len(universe_adv()),300)
        for points in (ADV_POINTS.iloc[::-1], ADV_POINTS.assign(advUsd=0), ADV_POINTS.iloc[1:]):
            with self.assertRaises(ValueError):universe_adv(points)
        for kwargs in ({'universe_size':0},{'annual_trades':2.5},{'annual_trades':True},{'turnover':-1}):
            with self.assertRaises(ValueError):self.engine(**kwargs)

    def test_seed_equal_tickets_turnover_and_migration(self):
        engine=self.engine(seed=42)
        first=engine.sampled_book(0,3.4)
        pd.testing.assert_frame_equal(first,self.engine(seed=42).sampled_book(0,3.4))
        self.assertFalse(np.array_equal(first['Sampled orders'],self.engine(seed=43).sampled_book(0,3.4)['Sampled orders']))
        self.assertEqual(first['Sampled orders'].sum(),971)
        self.assertEqual(first['Order notional (USD)'].nunique(),1)
        self.assertAlmostEqual(first['Sampled notional (USD)'].sum(),2*.139*3.4e9,places=5)
        doubled=engine.sampled_book(0,6.8)
        np.testing.assert_array_equal(first['Sampled orders'],doubled['Sampled orders'])
        np.testing.assert_allclose(doubled['Sampled notional (USD)'],2*first['Sampled notional (USD)'])
        np.testing.assert_allclose(doubled['Order/ADV at selected AUM'],2*first['Baseline order/ADV'])
        dist,_=bucket_migration(first,BUCKETS,3.4)
        for stage in range(3):self.assertEqual(dist[dist.Stage==stage].Trades.sum(),971)
        self.assertFalse(np.array_equal(dist[dist.Stage==1].Trades,dist[dist.Stage==2].Trades))
        np.testing.assert_allclose(first['Sampled notional weight'],first['Sampled orders']/971)

    def test_sampled_impact_matches_inspected_book_and_baseline_pairing(self):
        engine=self.engine(seed=7)
        draws=engine.impact_samples([.5,3.4,6.8],1.,3.,.7)
        for i in (0,99):
            for j,aum in enumerate((.5,3.4,6.8)):
                book=engine.sampled_book(i,aum)
                expected=np.dot(book['Sampled notional weight'],impact_bps(book['Order/ADV at selected AUM'],1.,3.,.7))
                self.assertAlmostEqual(draws[i,j],expected)
        np.testing.assert_allclose((draws[:,2]-1)/(draws[:,1]-1),2**.7)

    def test_annual_order_count_changes_ticket_and_zero_turnover(self):
        normal=self.engine(mode='Deterministic')
        twice=self.engine(mode='Deterministic',annual_trades=1942)
        np.testing.assert_allclose(twice.x,normal.x/2)
        zero=self.engine(turnover=0)
        self.assertEqual(zero.sampled_book(0,3.4)['Sampled notional (USD)'].sum(),0)
        self.assertTrue(np.isfinite(zero.impact_samples([.5,3.4],0,3,.5)).all())
        model=EmpiricalIRModel(Scenario(),DEFAULT_POINTS,DEFAULT_TC_POINTS,BUCKETS,
                               mode='Monte Carlo',samples=100,turnover=0)
        self.assertAlmostEqual(model.metric(3)['Net IR'],.342)
        self.assertEqual(model.curve(6).iloc[0]['Net IR P20'],.6)

    def test_csv_retains_actual_pairs_and_book_size(self):
        tape=pd.DataFrame({'q':[10.,20.,30.],'adv':[100.,100.,200.]})
        engine=create_liquidity_engine(Scenario(),BUCKETS,trades=tape,samples=100)
        self.assertEqual(engine.book_size,3)
        np.testing.assert_allclose(engine.x,tape.q/tape.adv)
        self.assertEqual(engine.source,'trade-csv')

    def test_monthly_rebalance_partition_preserves_annual_book(self):
        engine=self.engine(seed=42)
        annual=engine.sampled_book(0,3.4)
        monthly=engine.monthly_book(0,3.4)
        pd.testing.assert_frame_equal(monthly,engine.monthly_book(0,3.4))
        counts=monthly.groupby('Month')['Parent orders'].sum()
        self.assertEqual(len(counts),12)
        self.assertEqual(counts.sum(),971)
        self.assertEqual(counts.max()-counts.min(),1)
        stock_counts=monthly.groupby('Synthetic stock')['Parent orders'].sum().reindex(range(1,301),fill_value=0)
        np.testing.assert_array_equal(stock_counts,annual['Sampled orders'])
        self.assertAlmostEqual(monthly['Traded notional (USD)'].sum(),annual['Sampled notional (USD)'].sum(),places=5)
