import unittest

import numpy as np

from capacity_model import BUCKETS, AdvEngine, BurrEngine, Scenario, calibrate_orders


class CapacityModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orders = calibrate_orders()
        cls.engine = AdvEngine(Scenario(), cls.orders)

    def test_historical_calibration(self):
        self.assertAlmostEqual(self.orders["count"].sum(), 971, places=6)
        self.assertAlmostEqual((self.orders.ticket * self.orders["count"]).sum(), (BUCKETS.valueUsdMillion * 1e6).sum(), places=2)
        self.assertAlmostEqual(self.engine.metric(3.4)["Alpha capture (%)"], 100, places=7)
        self.assertAlmostEqual(self.engine.metric(3.4)["Multi-day (%)"], 0, places=7)
        self.assertAlmostEqual(self.engine.metric(3.4)["3+ days (%)"], 0, places=7)

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

    def test_average_execution_is_fractional_and_count_weighted(self):
        current = self.engine.metric(3.4)["Average days"]
        twice = self.engine.metric(6.8)["Average days"]
        self.assertLess(current, 1.0)
        self.assertAlmostEqual(twice, current * 2, places=7)

    def test_liquidity_deterioration_accelerates_tail_pressure(self):
        stressed = AdvEngine(
            Scenario(liquidity_deterioration=0.20), self.orders,
            anchor_aum=3.4, anchor_holdings=40,
        )
        baseline_current = self.engine.metric(3.4)
        stressed_current = stressed.metric(3.4)
        baseline_twice = self.engine.metric(6.8)
        stressed_twice = stressed.metric(6.8)
        self.assertAlmostEqual(
            baseline_current["Mean participation (%)"],
            stressed_current["Mean participation (%)"], places=7,
        )
        self.assertGreater(
            stressed_twice["Mean participation (%)"],
            baseline_twice["Mean participation (%)"],
        )
        self.assertGreater(
            stressed_twice["Notional above 25% ADV (%)"],
            baseline_twice["Notional above 25% ADV (%)"],
        )
        self.assertGreaterEqual(stressed_twice["P90 participation (%)"], 0.0)

    def test_impact_gamma_uses_fixed_saved_calibration(self):
        reference = (Scenario().impact_a, Scenario().impact_b, Scenario().impact_gamma)
        engines = (
            (
                AdvEngine(Scenario(), self.orders, impact_reference=reference),
                AdvEngine(Scenario(impact_gamma=1.5), self.orders, impact_reference=reference),
            ),
            (
                BurrEngine(Scenario(), impact_reference=reference),
                BurrEngine(Scenario(impact_gamma=1.5), impact_reference=reference),
            ),
        )
        for baseline, changed in engines:
            with self.subTest(engine=type(baseline).__name__):
                self.assertNotAlmostEqual(
                    baseline.metric(3.4)["Impact (bp)"],
                    changed.metric(3.4)["Impact (bp)"],
                    places=6,
                )
                self.assertNotAlmostEqual(
                    baseline.metric(10.0)["Impact (bp)"],
                    changed.metric(10.0)["Impact (bp)"],
                    places=6,
                )


if __name__ == "__main__":
    unittest.main()
