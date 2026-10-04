import tempfile
import unittest
from pathlib import Path

import pandas as pd

from capacity_model import AdvEngine, Scenario, calibrate_orders
from strategy_store import DEFAULT_PARAMETERS, default_strategy, load_strategies, save_strategy


class StrategyStoreTests(unittest.TestCase):
    def test_saved_strategy_round_trip_and_custom_anchor(self):
        source = default_strategy()
        parameters = {
            **DEFAULT_PARAMETERS, "aum0": 8.0, "holdings": 80,
            "universe_size": 1200, "max_aum": 40.0,
            "liquidity_deterioration": 0.2,
        }
        buckets = pd.DataFrame(source["buckets"])
        adv_points = pd.DataFrame(source["adv_points"])
        adv_points["advUsd"] *= 2

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "strategies.json"
            save_strategy("Global DM Strategy", parameters, buckets, adv_points, path)
            strategies = load_strategies(path)

        saved = strategies["Global DM Strategy"]
        self.assertEqual(saved["parameters"]["aum0"], 8.0)
        self.assertEqual(saved["parameters"]["holdings"], 80)
        self.assertEqual(saved["parameters"]["universe_size"], 1200)
        self.assertEqual(saved["parameters"]["liquidity_deterioration"], 0.2)
        saved_buckets = pd.DataFrame(saved["buckets"])
        saved_adv = pd.DataFrame(saved["adv_points"])
        orders = calibrate_orders(0.0, saved_buckets, saved_adv, 1200)
        engine = AdvEngine(
            Scenario(aum0=8.0, holdings=80, universe_size=1200), orders, saved_buckets,
            anchor_aum=8.0, anchor_holdings=80,
        )
        self.assertAlmostEqual(engine.metric(8.0)["Alpha capture (%)"], 100.0, places=7)
        self.assertAlmostEqual(engine.dollar_shares(8.0).sum(), 100.0, places=7)

    def test_invalid_adv_curve_is_rejected(self):
        source = default_strategy()
        adv_points = pd.DataFrame(source["adv_points"])
        adv_points.loc[1, "advUsd"] = adv_points.loc[0, "advUsd"]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "increase strictly"):
                save_strategy(
                    "Invalid", DEFAULT_PARAMETERS, pd.DataFrame(source["buckets"]),
                    adv_points, Path(directory) / "strategies.json",
                )

    def test_holdings_cannot_exceed_universe(self):
        source = default_strategy()
        parameters = {**DEFAULT_PARAMETERS, "holdings": 40, "universe_size": 30}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "cannot exceed"):
                save_strategy(
                    "Too concentrated", parameters, pd.DataFrame(source["buckets"]),
                    pd.DataFrame(source["adv_points"]), Path(directory) / "strategies.json",
                )


if __name__ == "__main__":
    unittest.main()
