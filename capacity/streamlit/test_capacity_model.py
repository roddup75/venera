import unittest

import numpy as np

from capacity_model import BUCKETS, AdvEngine, Scenario, calibrate_orders


class CapacityModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orders = calibrate_orders()
        cls.engine = AdvEngine(Scenario(), cls.orders)

    def test_historical_calibration(self):
        self.assertAlmostEqual(self.orders["count"].sum(), 971, places=6)
        self.assertAlmostEqual((self.orders.ticket * self.orders["count"]).sum(), (BUCKETS.valueUsdMillion * 1e6).sum(), places=2)
        self.assertAlmostEqual(self.engine.metric(3.4)["Alpha capture (%)"], 100, places=7)

    def test_migration_shares_sum_to_100(self):
        for aum in (3.4, 6.8, 13.6):
            self.assertAlmostEqual(self.engine.dollar_shares(aum).sum(), 100, places=7)
            self.assertAlmostEqual(self.engine.count_shares(aum).sum(), 100, places=7)
            self.assertAlmostEqual(self.engine.execution_shares(aum).sum(), 100, places=7)

    def test_participation_changes_execution_outcomes(self):
        slow = AdvEngine(Scenario(daily_participation=5), self.orders)
        np.testing.assert_allclose(self.engine.count_shares(6.8), slow.count_shares(6.8))
        self.assertFalse(np.allclose(self.engine.execution_shares(6.8), slow.execution_shares(6.8)))

    def test_universe_size_sets_finite_adv_grid(self):
        small = calibrate_orders(universe_size=25)
        self.assertEqual(len(small), len(BUCKETS) * 25 * 16)
        self.assertAlmostEqual(small["count"].sum(), BUCKETS.trades.sum(), places=6)


if __name__ == "__main__":
    unittest.main()
