import json
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from capacity_model import ExecutionEngine, Scenario, annual_cost_from_buckets
from strategy_store import DEFAULT_PARAMETERS, default_strategy, load_strategies, save_strategy

class StrategyStoreTests(unittest.TestCase):
    def test_strategy_and_actual_trades_round_trip(self):
        source=default_strategy()
        parameters={**DEFAULT_PARAMETERS, 'aum0':8., 'max_aum':40., 'annual_cost_bps':12., 'mc_samples':1234, 'mc_seed':42}
        trades=pd.DataFrame({'q':[100.,200.], 'adv':[1000.,2000.]})
        ir=pd.DataFrame(source['ir_points']);ir.loc[1,'ir']=.31
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'strategies.json'
            save_strategy('Global', parameters, pd.DataFrame(source['buckets']), pd.DataFrame(source['adv_points']), path, ir, trades)
            saved=load_strategies(path)['Global']
        self.assertEqual(saved['parameters']['annual_cost_bps'],12.)
        self.assertEqual(saved['parameters']['mc_samples'],1234)
        self.assertEqual(saved['parameters']['mc_seed'],42)
        self.assertEqual(saved['ir_points'][1]['ir'],.31)
        self.assertEqual(saved['trades'], trades.to_dict('records'))
        self.assertEqual(saved['methodology'],'three-pillar-empirical-v1')
        engine=ExecutionEngine(Scenario(aum0=8), trades=pd.DataFrame(saved['trades']))
        self.assertEqual(engine.metric(8)['Alpha capture (%)'],100)

    def test_legacy_cost_conversion_preserves_settings(self):
        source=default_strategy()
        source['parameters']={'aum0':3.4, 'gross_alpha':.58, 'turnover':13.9,
                              'holdings':40, 'engine_name':'ADV-calibrated migration'}
        source.pop('ir_points')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'legacy.json'
            original=json.dumps({'Swiss Strategy':source});path.write_text(original)
            saved=load_strategies(path)['Swiss Strategy']
            self.assertEqual(path.read_text(),original)
        self.assertEqual(saved['parameters']['gross_alpha'],.58)
        self.assertEqual(saved['parameters']['holdings'],40)
        self.assertEqual(saved['parameters']['engine_name'],'Execution delay')
        self.assertEqual(saved['parameters']['calculation_mode'],'Deterministic')
        self.assertEqual(saved['parameters']['mc_samples'],2000)
        expected=annual_cost_from_buckets(pd.DataFrame(source['buckets']),13.9)
        self.assertAlmostEqual(saved['parameters']['annual_cost_bps'],expected)
        self.assertEqual(len(saved['ir_points']),10)

    def test_invalid_inputs_rejected_without_overwriting_store(self):
        source=default_strategy()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'strategies.json'
            path.write_text('{}')
            for updates in [{'annual_cost_bps':-1}, {'daily':101}, {'max_aum':1}, {'half_life':0}, {'gross_alpha':float('nan')}, {'mc_samples':0}, {'mc_samples':2.5}, {'mc_seed':-1}, {'calculation_mode':'unknown'}]:
                with self.subTest(updates=updates):
                    with self.assertRaises(ValueError):
                        save_strategy('Invalid',{**DEFAULT_PARAMETERS,**updates},pd.DataFrame(source['buckets']),pd.DataFrame(source['adv_points']),path)
                    self.assertEqual(path.read_text(),'{}')

    def test_duplicate_backtest_aum_rejected(self):
        source=default_strategy();ir=pd.DataFrame(source['ir_points']);ir.loc[1,'aumBn']=0
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'unique'):
                save_strategy('Invalid',DEFAULT_PARAMETERS,pd.DataFrame(source['buckets']),pd.DataFrame(source['adv_points']),Path(directory)/'s.json',ir_points=ir)

if __name__ == '__main__':
    unittest.main()
