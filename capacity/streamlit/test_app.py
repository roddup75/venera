"""UI regression checks using Streamlit's real script runner."""
import unittest
import tempfile
from unittest.mock import patch
import strategy_store
from pathlib import Path
from streamlit.testing.v1 import AppTest

class AppTests(unittest.TestCase):
    def app(self):
        app=AppTest.from_file(str(Path(__file__).with_name('app.py')),default_timeout=30).run()
        self.assertEqual(len(app.exception),0, str(app.exception))
        return app

    def test_default_and_cost_edits_recalculate(self):
        app=self.app()
        labels=[tab.label for tab in app.tabs]
        self.assertEqual(labels[:2],['Summary','Empirical IR curve'])
        self.assertNotIn('Overview',labels)
        self.assertIn('Inputs & strategy',labels)
        self.assertNotIn('Input data',labels)
        self.assertNotIn('Strategy creator',labels)
        method_tab = next(t for t in app.tabs if t.label=='Methodology')
        self.assertEqual(len(method_tab.markdown),0)
        self.assertEqual(len(method_tab.get('download_button')),1)
        self.assertIn('Backtest IR curve',labels)
        self.assertIn('Methodology',labels)
        self.assertIn('Model Calibration',labels)
        self.assertIn('a) ADV bucket sampler',labels)
        self.assertIn('b) Alpha decay',labels)
        self.assertIn('c) Transfer coefficient decay',labels)
        self.assertNotIn('Execution & sensitivity',labels)
        self.assertNotIn('Liquidity migration',labels)
        self.assertFalse(any(s.label=='Capacity model' for s in app.selectbox))
        initial=float(next(m.value for m in app.metric if m.label=='Current net IR'))
        def backtest_ir():return next(d.value for d in app.dataframe if 'Approach' in d.value.columns).loc[lambda f:f.Approach=='Backtest IR curve','Current net IR'].iloc[0]
        before_backtest=backtest_ir()
        field=next(n for n in app.number_input if n.label=='Baseline gross alpha (%)')
        self.assertFalse(field.disabled)
        field.set_value(field.value+.13).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        current=float(next(m.value for m in app.metric if m.label=='Current net IR'))
        self.assertAlmostEqual(current-initial,.1,places=3)
        self.assertEqual(backtest_ir(),before_backtest)
        self.assertFalse(any(n.label in ('Baseline annual cost drag (bp)','Signal half-life (trading days)','Cost stress elasticity γ','Minimum retained alpha (%)') for n in app.number_input))
        summary=next(t for t in app.tabs if t.label=='Summary')
        self.assertEqual(len(summary.dataframe),2)
        self.assertEqual(len(summary.get('plotly_chart')),1)
        self.assertEqual(summary.subheader[-1].value,'Simulation distribution')
        self.assertFalse(any(h.value=='Three-pillar IR breakdown' for h in summary.subheader))

    def test_tables_use_two_decimal_display_without_rounding_inputs(self):
        import json
        import pandas as pd
        app=self.app()
        for table in app.dataframe:
            config=json.loads(table.proto.columns)
            for column in table.value:
                dtype=table.value[column].dtype
                if pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype):
                    self.assertIn(config[column]['type_config']['format'],('%.2f','%d'))
        editor=next(d for d in app.dataframe if 'p' in d.value.columns)
        self.assertEqual(editor.value.iloc[0]['p'],.5)
        book=next(d.value for d in app.dataframe if 'Baseline order/ADV (%)' in d.value.columns)
        self.assertGreater(book.iloc[0]['Baseline order/ADV (%)'],0)
        net=next(d.value for d in app.dataframe if 'Scenario' in d.value.columns and 'Net IR' in d.value.columns)['Net IR']
        self.assertTrue(any(abs(v-round(v,2))>1e-5 for v in net))

    def test_empirical_capacity_intervals_are_default_and_optional(self):
        import json
        app=self.app()
        def plot(title):
            return next(json.loads(c.proto.spec) for c in app.get('plotly_chart') if json.loads(c.proto.spec).get('layout',{}).get('title',{}).get('text')==title)
        self.assertEqual(next(s.value for s in app.selectbox if s.label=='Calculation mode'),'Monte Carlo')
        self.assertEqual(len(plot('Net information ratio')['data']),4)
        self.assertTrue(any(m.label=='Capacity P20' for m in app.metric))
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Deterministic').run()
        self.assertEqual(len(plot('Net information ratio')['data']),2)
        self.assertEqual(len(plot('Net alpha')['data']),2)
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Monte Carlo').run()
        for title in ['Net information ratio','Net alpha']:
            self.assertEqual(len(plot(title)['data']),4)
            self.assertEqual(plot(title)['data'][-2]['fill'],'tonexty')
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Deterministic').run()
        self.assertEqual(len(plot('Net information ratio')['data']),2)
        self.assertEqual(len(app.exception),0,str(app.exception))

    def test_capacity_interval_summary_and_censoring_follow_threshold(self):
        app=self.app()
        def metric(label):return next(m.value for m in app.metric if m.label==label)
        self.assertEqual(metric('Threshold reached within horizon'),'100.00%')
        p20=float(metric('Capacity P20').strip('$').replace('bn',''))
        p80=float(metric('Capacity P80').strip('$').replace('bn',''))
        self.assertLess(p20,p80)
        next(n for n in app.number_input if n.label=='Minimum net IR').set_value(0.).run()
        next(n for n in app.number_input if n.label=='Chart horizon ($bn)').set_value(3.4).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertEqual(metric('Threshold reached within horizon'),'0.00%')
        self.assertTrue(metric('Capacity P80').startswith('>'))
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Deterministic').run()
        self.assertFalse(any(m.label=='Capacity P20' for m in app.metric))

    def test_demo_controls_and_500m_grid(self):
        app=self.app()
        sampler_aum=next(n for n in app.number_input if n.label=='Sampler AUM (USD bn)')
        self.assertEqual(sampler_aum.value,next(n.value for n in app.number_input if n.label=='Current AUM ($bn)'))
        plots=app.get('plotly_chart')
        import json
        for chart in plots:
            spec=json.loads(chart.proto.spec)
            if spec.get('layout',{}).get('xaxis',{}).get('title',{}).get('text')=='AUM (USD bn)':
                self.assertEqual(spec['layout']['xaxis']['range'][0],.5)
        next(n for n in app.number_input if n.label=='Simulated book to inspect').set_value(2000).run()
        next(n for n in app.number_input if n.label=='Sampler Monte Carlo samples').set_value(100).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertEqual(next(n for n in app.number_input if n.label=='Simulated book to inspect').value,100)

    def test_sampler_preview_follows_anchor_until_custom_scenario(self):
        app=self.app()
        def field(label):return next(n for n in app.number_input if n.label==label)
        self.assertEqual(field('Sampler AUM (USD bn)').value,field('Current AUM ($bn)').value)
        book=next(d.value for d in app.dataframe if 'Baseline order/ADV (%)' in d.value.columns)
        self.assertEqual(book['Baseline order/ADV (%)'].tolist(),book['Order/ADV at selected AUM (%)'].tolist())
        field('Current AUM ($bn)').set_value(6.).run()
        self.assertEqual(field('Sampler AUM (USD bn)').value,6.)
        field('Sampler AUM (USD bn)').set_value(2.).run()
        field('Current AUM ($bn)').set_value(5.).run()
        self.assertEqual(field('Sampler AUM (USD bn)').value,2.)
        self.assertEqual(len(app.exception),0,str(app.exception))

    def test_alpha_calibration_is_live_and_remains_editable(self):
        app=self.app()
        self.assertEqual(next(m.value for m in app.metric if m.label=='Implied AUM curvature'),'2.04125')
        next(n for n in app.number_input if n.label=='Demo point 3 net IR').set_value(.48).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertFalse(any('Apply alpha' in b.label for b in app.button))
        next(n for n in app.number_input if n.label=='Demo point 2 trades >1 day (%)').set_value(0.).run()
        self.assertTrue(any('increase' in e.value for e in app.warning))

    def test_simple_impact_controls_and_isolation(self):
        app=self.app()
        def metric(label): return next(m.value for m in app.metric if m.label==label)
        self.assertEqual(metric('Observed weighted bucket impact'),'8.69 bp')
        sampler_tab=next(t for t in app.tabs if t.label=='a) ADV bucket sampler')
        self.assertEqual(len(sampler_tab.slider),0)
        self.assertEqual(len(sampler_tab.radio),0)
        self.assertFalse(any('Demo signal' in n.label or 'Impact intercept' in n.label for n in app.number_input))
        base_ir=metric('Current net IR')
        before=float(metric('Sampled weighted impact').split()[0])
        next(n for n in app.number_input if n.label=='Sampler AUM (USD bn)').set_value(6.).run()
        self.assertGreater(float(metric('Sampled weighted impact').split()[0]),before)
        self.assertEqual(metric('Current net IR'),base_ir)
        impact=metric('Sampled weighted impact')
        next(n for n in app.number_input if n.label=='Impact one-way annual turnover (%)').set_value(0.).run()
        self.assertEqual(metric('Implied annual portfolio drag'),'0.00 bp')
        self.assertEqual(metric('Sampled traded notional'),'USD 0.00m')
        self.assertEqual(len(app.exception),0,str(app.exception))

    def test_tc_calibration_and_tracking_error_are_live(self):
        app=self.app()
        self.assertEqual(next(m.value for m in app.metric if m.label=='Implied TC-to-alpha curvature'),'1.00000')
        def current_alpha():return next(d.value for d in app.dataframe if 'Scenario' in d.value.columns and 'Net alpha (%)' in d.value.columns).loc[lambda f:f.AUM==3.4,'Net alpha (%)'].iloc[0]
        before=current_alpha()
        next(n for n in app.number_input if n.label=='Tracking error (%)').set_value(1.).run()
        self.assertAlmostEqual(current_alpha(),before)
        self.assertFalse(any('Apply TC' in b.label for b in app.button))
        self.assertEqual(len(app.exception),0,str(app.exception))

    def test_pillars_change_projection_but_preserve_current_gross_anchor(self):
        app=self.app()
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Deterministic').run()
        def table():return next(d.value for d in app.dataframe if 'Starting net IR' in d.value.columns)
        def future():return float(table().loc[lambda f:f.AUM==6.,'Net IR'].iloc[0])
        current=next(m.value for m in app.metric if m.label=='Current net IR')
        before=future()
        next(n for n in app.number_input if n.label=='Demo point 3 net IR').set_value(.48).run()
        self.assertLess(future(),before)
        self.assertEqual(next(m.value for m in app.metric if m.label=='Current net IR'),current)
        before=future()
        next(n for n in app.number_input if n.label=='Demo TC point 3 annual alpha (%)').set_value(.2).run()
        self.assertLess(future(),before)
        self.assertEqual(next(m.value for m in app.metric if m.label=='Current net IR'),current)
        before=future()
        next(n for n in app.number_input if n.label=='Impact one-way annual turnover (%)').set_value(30.).run()
        self.assertLess(future(),before)
        self.assertEqual(len(app.exception),0,str(app.exception))

    def test_universe_sampler_annual_count_recalculates_cost_and_summary(self):
        app=self.app()
        def metric(label):return next(m.value for m in app.metric if m.label==label)
        self.assertEqual(next(r.value for r in app.radio if r.label=='Order input source'),'Universe ADV sampler')
        self.assertEqual(next(n.value for n in app.number_input if n.label=='Stocks in universe'),300)
        self.assertEqual(metric('Orders in sampled book'),'971')
        before=float(metric('Sampled weighted impact').split()[0])
        before_ir=float(metric('Current net IR'))
        next(n for n in app.number_input if n.label=='Annual parent orders (12 monthly rebalances)').set_value(1942).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertEqual(metric('Orders in sampled book'),'1,942')
        self.assertLess(float(metric('Sampled weighted impact').split()[0]),before)
        self.assertGreater(float(metric('Current net IR')),before_ir)

    def test_invalid_combined_calibration_remains_editable(self):
        app=self.app()
        next(n for n in app.number_input if n.label=='Demo point 3 net IR').set_value(.7).run()
        self.assertTrue(any('decrease' in e.value for e in app.error))
        next(n for n in app.number_input if n.label=='Demo point 3 net IR').set_value(.5).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertTrue(any(m.label=='Current net IR' for m in app.metric))

    def test_bucket_migration_uses_current_aum_and_one_book(self):
        import json
        app=self.app()
        def migration():
            return next(spec for item in app.get('plotly_chart') if (spec:=json.loads(item.proto.spec)).get('layout',{}).get('title',{}).get('text')=='Trade frequency by ADV bucket')
        before=migration()
        trace=before['data'][0]
        self.assertEqual(trace['type'],'bar')
        self.assertEqual(trace['orientation'],'v')
        self.assertEqual(len(before['data']),3)
        self.assertEqual(before['layout']['yaxis']['title']['text'],'Trade frequency (%)')
        total=int(next(m.value for m in app.metric if m.label=='Orders in sampled book').replace(',',''))
        self.assertIn('≥100%',trace['x'])
        aum=next(n.value for n in app.number_input if n.label=='Current AUM ($bn)')
        self.assertEqual([x['name'] for x in before['data']],[f'Current · ${aum:g}bn',f'×2 · ${2*aum:g}bn',f'×3 · ${3*aum:g}bn'])
        next(n for n in app.number_input if n.label=='Sampler AUM (USD bn)').set_value(1.).run()
        self.assertEqual(migration()['data'],before['data'])
        self.assertEqual(len(app.exception),0,str(app.exception))

    def test_sampler_seed_changes_book_without_changing_calibrations(self):
        import json
        app=self.app()
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Monte Carlo').run()
        def plot(title):
            return next(spec for item in app.get('plotly_chart') if (spec:=json.loads(item.proto.spec)).get('layout',{}).get('title',{}).get('text')==title)['data']
        before={title:plot(title) for title in ['Net alpha','Resulting AUM → alpha','Resulting AUM → IR','Sampled order-size distribution']}
        next(n for n in app.number_input if n.label=='Sampler random seed').set_value(27).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertNotEqual(plot('Net alpha'),before['Net alpha'])
        for title in ['Resulting AUM → alpha','Resulting AUM → IR']:
            self.assertEqual(plot(title),before[title])
        self.assertNotEqual(plot('Sampled order-size distribution'),before['Sampled order-size distribution'])

    def test_demo_sampler_with_saved_actual_trades(self):
        source=strategy_store.default_strategy()
        source['trades']=[{'q':100000.,'adv':10000000.},{'q':200000.,'adv':2000000.}]
        with patch.object(strategy_store,'load_strategies',return_value={'Trade strategy':source}):
            app=self.app()
            self.assertEqual(next(m for m in app.metric if m.label=='Orders in sampled book').value,'2')
            self.assertEqual(next(n for n in app.number_input if n.label=='Sampler AUM (USD bn)').value,next(n.value for n in app.number_input if n.label=='Current AUM ($bn)'))

    def test_monte_carlo_default_and_editable_samples(self):
        app=self.app()
        mode=next(s for s in app.selectbox if s.label == 'Calculation mode')
        self.assertEqual(mode.value,'Monte Carlo')
        samples=next(n for n in app.number_input if n.label == 'Sampler Monte Carlo samples')
        self.assertEqual(samples.value,2000)
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Monte Carlo').run()
        samples=next(n for n in app.number_input if n.label=='Sampler Monte Carlo samples')
        samples.set_value(200).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        next(s for s in app.selectbox if s.label == 'Calculation mode').set_value('Deterministic').run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertFalse(next(n for n in app.number_input if n.label == 'Sampler Monte Carlo samples').disabled)

    def test_zero_alpha_and_horizon_expansion(self):
        app=self.app()
        next(n for n in app.number_input if n.label=='Baseline gross alpha (%)').set_value(0.).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        next(n for n in app.number_input if n.label=='Current AUM ($bn)').set_value(8.).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        horizon=next(n for n in app.number_input if n.label=='Chart horizon ($bn)')
        self.assertGreaterEqual(horizon.value,8)

    def test_combined_calibration_settings_save_and_reload(self):
        original_save=strategy_store.save_strategy
        original_load=strategy_store.load_strategies
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'combined.json'
            def save(name,parameters,buckets,adv_points,**kwargs):
                return original_save(name,parameters,buckets,adv_points,path=path,**kwargs)
            with patch.object(strategy_store,'save_strategy',side_effect=save), patch.object(strategy_store,'load_strategies',side_effect=lambda:original_load(path)):
                app=self.app()
                next(n for n in app.number_input if n.label=='Demo point 3 net IR').set_value(.48).run()
                next(n for n in app.number_input if n.label=='Demo TC point 3 annual alpha (%)').set_value(.25).run()
                next(n for n in app.number_input if n.label=='Impact one-way annual turnover (%)').set_value(30.).run()
                next(n for n in app.number_input if n.label=='Sampler Monte Carlo samples').set_value(100).run()
                next(n for n in app.number_input if n.label=='Sampler random seed').set_value(42).run()
                next(n for n in app.number_input if n.label=='Baseline gross alpha (%)').set_value(.73).run()
                before=next(m.value for m in app.metric if m.label=='Current net IR')
                next(n for n in app.text_input if n.label=='Strategy name').set_value('Empirical copy')
                next(b for b in app.button if b.label=='Save strategy').click().run()
                self.assertEqual(len(app.exception),0,str(app.exception))
                saved=original_load(path)['Empirical copy']
                params=saved['parameters']
                self.assertEqual(params['model_kind'],'Three-pillar empirical')
                self.assertEqual(params['alpha_points'][2][2],.48)
                self.assertEqual(params['tc_points'][2][2],.25)
                self.assertEqual(params['turnover'],30.)
                self.assertEqual(params['mc_samples'],100)
                self.assertEqual(params['mc_seed'],42)
                self.assertEqual(params['gross_alpha'],.73)
                self.assertEqual(saved['methodology'],'three-pillar-current-gross-v4')
                self.assertEqual(next(m.value for m in app.metric if m.label=='Current net IR'),before)

    def test_strategy_creator_save_and_reload(self):
        original_save = strategy_store.save_strategy
        original_load = strategy_store.load_strategies
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"strategies.json"
            def save(name, parameters, buckets, adv_points, **kwargs):
                return original_save(name, parameters, buckets, adv_points, path=path, **kwargs)
            with patch.object(strategy_store, "save_strategy", side_effect=save), patch.object(strategy_store, "load_strategies", side_effect=lambda: original_load(path)):
                app = self.app()
                next(n for n in app.number_input if n.label=='Demo point 3 net IR').set_value(.48).run()
                next(n for n in app.text_input if n.label == "Strategy name").set_value("Test copy")
                next(b for b in app.button if b.label == "Save strategy").click().run()
                self.assertEqual(len(app.exception), 0, str(app.exception))
                self.assertIn("Test copy", original_load(path))
                self.assertAlmostEqual(original_load(path)["Test copy"]["buckets"][0]["p"],.005)
                self.assertEqual(original_load(path)["Test copy"]["parameters"]["model_kind"],"Three-pillar empirical")
                self.assertEqual(original_load(path)["Test copy"]["parameters"]["alpha_points"][2][2],.48)
                selected = next(s for s in app.selectbox if s.label == "Saved strategy")
                self.assertEqual(selected.value, "Test copy")
                self.assertEqual(original_load(path)["Test copy"]["parameters"]["engine_name"], "Three-pillar empirical")

if __name__=='__main__':
    unittest.main()
