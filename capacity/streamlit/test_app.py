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
        self.assertEqual(next(s.value for s in app.selectbox if s.label=='Capacity model'),'Three-pillar empirical')
        next(s for s in app.selectbox if s.label=='Capacity model').set_value('Execution delay').run()
        initial=float(next(m.value for m in app.metric if m.label=='Current net IR'))
        field=next(n for n in app.number_input if n.label=='Baseline annual cost drag (bp)')
        field.set_value(field.value+13).run()
        self.assertEqual(len(app.exception),0, str(app.exception))
        current=float(next(m.value for m in app.metric if m.label=='Current net IR'))
        self.assertAlmostEqual(initial-current,.1,places=3)

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
        self.assertEqual(book.iloc[0]['Baseline order/ADV (%)'],.5)
        net=next(d.value for d in app.dataframe if 'Scenario' in d.value.columns and 'Net IR' in d.value.columns)['Net IR']
        self.assertTrue(any(abs(v-round(v,2))>1e-5 for v in net))

    def test_empirical_intervals_are_optional_and_off_by_default(self):
        import json
        app=self.app()
        def plot(title):
            return next(json.loads(c.proto.spec) for c in app.get('plotly_chart') if json.loads(c.proto.spec).get('layout',{}).get('title',{}).get('text')==title)
        self.assertEqual(next(s.value for s in app.selectbox if s.label=='Calculation mode'),'Deterministic')
        self.assertEqual(len(plot('Net information ratio')['data']),1)
        self.assertEqual(len(plot('Net alpha')['data']),1)
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Monte Carlo').run()
        for title in ['Net information ratio','Net alpha']:
            self.assertEqual(len(plot(title)['data']),3)
            self.assertEqual(plot(title)['data'][-1]['fill'],'tonexty')
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Deterministic').run()
        self.assertEqual(len(plot('Net information ratio')['data']),1)
        self.assertEqual(len(app.exception),0,str(app.exception))

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

    def test_three_point_calibration_apply_and_cost_isolation(self):
        app=self.app()
        next(s for s in app.selectbox if s.label=='Capacity model').set_value('Calibrated alpha decay').run()
        self.assertEqual(next(m.value for m in app.metric if m.label=='Implied AUM curvature'),'2.04125')
        self.assertEqual(next(m.value for m in app.metric if m.label=='Implied congestion-to-IR curvature'),'0.74807')
        next(n for n in app.number_input if n.label=='Demo point 3 net IR').set_value(.48).run()
        next(b for b in app.button if b.label=='Apply alpha-decay calibration to Capacity Lab').click().run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertEqual(next(s.value for s in app.selectbox if s.label=='Capacity model'),'Calibrated alpha decay')
        self.assertEqual(next(n.value for n in app.number_input if n.label=='Point 3 net IR'),.48)
        self.assertTrue(next(n for n in app.number_input if n.label=='Baseline annual cost drag (bp)').disabled)
        next(n for n in app.number_input if n.label=='Current AUM ($bn)').set_value(6.).run()
        self.assertEqual(next(m.value for m in app.metric if m.label=='Current net IR'),'0.480')
        self.assertEqual(len(app.exception),0,str(app.exception))
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Deterministic').run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        next(n for n in app.number_input if n.label=='Point 2 trades >1 day (%)').set_value(0.).run()
        self.assertTrue(any('increase' in e.value for e in app.error))

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
        self.assertEqual(metric('Sampled weighted impact'),impact)
        self.assertEqual(len(app.exception),0,str(app.exception))

    def test_tc_calibration_apply_and_te_scaling(self):
        app=self.app()
        next(s for s in app.selectbox if s.label=='Capacity model').set_value('Calibrated transfer coefficient').run()
        self.assertEqual(next(m.value for m in app.metric if m.label=='Implied TC-to-alpha curvature'),'1.00000')
        next(b for b in app.button if b.label=='Apply TC calibration to Capacity Lab').click().run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertEqual(next(s.value for s in app.selectbox if s.label=='Capacity model'),'Calibrated transfer coefficient')
        next(n for n in app.number_input if n.label=='Current AUM ($bn)').set_value(6.).run()
        self.assertEqual(next(m.value for m in app.metric if m.label=='Current transfer coefficient'),'25.00%')
        self.assertEqual(next(m.value for m in app.metric if m.label=='Current net IR'),'0.231')
        next(n for n in app.number_input if n.label=='Tracking error (%)').set_value(1.).run()
        self.assertEqual(next(m.value for m in app.metric if m.label=='Current net IR'),'0.300')
        self.assertTrue(next(n for n in app.number_input if n.label=='Baseline annual cost drag (bp)').disabled)
        self.assertTrue(next(n for n in app.number_input if n.label=='Monte Carlo samples').disabled)
        self.assertEqual(len(app.exception),0,str(app.exception))
        next(n for n in app.number_input if n.label=='TC point 3 coefficient (%)').set_value(50.).run()
        self.assertTrue(any('decrease' in e.value for e in app.error))

    def test_empirical_curve_and_summary_follow_all_three_pillars(self):
        app=self.app()
        next(s for s in app.selectbox if s.label=='Calculation mode').set_value('Deterministic').run()
        next(n for n in app.number_input if n.label=='Current AUM ($bn)').set_value(3.).run()
        def ir():return float(next(m.value for m in app.metric if m.label=='Current net IR'))
        def breakdown():return next(d.value for d in app.dataframe if 'Starting net IR' in d.value.columns)
        before=ir()
        table=breakdown()
        current=table[table.AUM==3.].iloc[0]
        self.assertAlmostEqual(current['Net IR'],.342-current['Incremental impact drag (bp)']/130,places=4)
        self.assertAlmostEqual(before,current['Net IR'],places=3)
        self.assertEqual(table[table.AUM==.5]['Net IR'].iloc[0],.6)
        next(n for n in app.number_input if n.label=='Current AUM ($bn)').set_value(3.4).run()
        before=ir()
        next(n for n in app.number_input if n.label=='Demo point 3 net IR').set_value(.48).run()
        self.assertLess(ir(),before)
        after_alpha=ir()
        next(n for n in app.number_input if n.label=='Demo TC point 3 annual alpha (%)').set_value(.2).run()
        self.assertLess(ir(),after_alpha)
        after_tc=ir()
        next(n for n in app.number_input if n.label=='Impact one-way annual turnover (%)').set_value(30.).run()
        self.assertLess(ir(),after_tc)
        self.assertAlmostEqual(ir(),breakdown()[breakdown().AUM==3.4]['Net IR'].iloc[0],places=3)
        self.assertEqual(len(app.exception),0,str(app.exception))

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
        self.assertEqual(mode.value,'Deterministic')
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
        next(s for s in app.selectbox if s.label=='Capacity model').set_value('Execution delay').run()
        next(n for n in app.number_input if n.label=='Baseline gross alpha (%)').set_value(0.).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        next(n for n in app.number_input if n.label=='Current AUM ($bn)').set_value(20.).run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        horizon=next(n for n in app.number_input if n.label=='Chart horizon ($bn)')
        self.assertGreaterEqual(horizon.value,20)

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
                self.assertEqual(saved['methodology'],'three-pillar-empirical-v1')
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
                next(s for s in app.selectbox if s.label=='Capacity model').set_value('Calibrated alpha decay').run()
                next(n for n in app.number_input if n.label=='Point 3 net IR').set_value(.48).run()
                next(n for n in app.text_input if n.label == "Strategy name").set_value("Test copy")
                next(b for b in app.button if b.label == "Save strategy").click().run()
                self.assertEqual(len(app.exception), 0, str(app.exception))
                self.assertIn("Test copy", original_load(path))
                self.assertAlmostEqual(original_load(path)["Test copy"]["buckets"][0]["p"],.005)
                self.assertEqual(original_load(path)["Test copy"]["parameters"]["model_kind"],"Calibrated alpha decay")
                self.assertEqual(original_load(path)["Test copy"]["parameters"]["alpha_points"][2][2],.48)
                selected = next(s for s in app.selectbox if s.label == "Saved strategy")
                self.assertEqual(selected.value, "Test copy")
                self.assertEqual(original_load(path)["Test copy"]["parameters"]["engine_name"], "Execution delay")

if __name__=='__main__':
    unittest.main()
