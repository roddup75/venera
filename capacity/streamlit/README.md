# Capacity Lab — Streamlit

One capacity model combines impact costs, alpha decay and transfer-coefficient retention. The sidebar's **Baseline gross alpha (%)** is annual alpha at **Current AUM**, before impact costs. The calibration pillars define relative shape, normalised at current AUM; full annual impact costs are deducted once. The separate backtest IR fit remains an independent comparison.

## Run

```sh
cd streamlit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Python 3.11+; open http://localhost:8501.

## Views

- **Summary:** capacity results and two tables comparing empirical and backtest approaches. The Monte Carlo histogram and crossing export are last.
- **Empirical IR curve:** net IR and net alpha, optional P10–P90 bands, scenario table, pillar-loss breakdown and exports.
- **Backtest IR curve:** independent fit to historical AUM/IR observations; replace illustrative defaults with actual backtests.
- **Model Calibration:** ADV sampler and alpha-decay/TC calibration charts. Edit the triples in Inputs & strategy. All three pillars feed the same combined curve immediately; there are no separate capacity-model options.
- **Inputs & strategy:** universe ADV percentiles, universe size, annual parent-order count, historical impact buckets or actual `q,adv` CSV. Save current inputs and parameters here.
- **Methodology:** download the current PDF.

## Gross-alpha anchor and costs

Let `R(A)` be alpha-decay retention times TC-alpha retention. Gross alpha at AUM A is `gross_alpha_current * R(A) / R(current_AUM)`. Net IR is `(gross_alpha(A) - annual_impact_bp(A)/100) / tracking_error_pct`. Annual alpha and tracking error are percentage points. The initial calibration values normalise pillar shapes, not the combined performance level. USD 0.5bn is only the lower calculation boundary. Gross alpha at current AUM is fixed across simulations; net IR varies through sampled costs and final-IR uncertainty. Current AUM must have positive combined retention.

The impact curve `a+b*x**gamma` is fitted to estimated historical bucket costs with equal fitting weights. Annual impact is twice one-way turnover fraction times notional-weighted impact. Full annual costs are deducted once. The optional IR breakdown measures losses from model-implied net IR at $0.5bn; baseline costs are already included in that reference.

Daily participation is an execution-time reference in alpha calibration, not an input to bucket assignment or the combined IR curve. Retired half-life, cost-stress and retained-alpha controls are preserved only as saved metadata.

## Annual sampling and monthly rebalancing

The saved percentiles in `data/universe-adv-data.json` approximate 300 stock ADVs by log-dollar interpolation at midpoint ranks. Historical bucket counts fix annual composition (971 orders by default). A bucket ticket is `2 * annual_turnover_fraction * AUM_USD * bucket_value_share / bucket_order_count`. Within each bucket, draw uniformly with replacement among stocks whose ticket/ADV fits its bounds. This preserves both historical count and notional shares at current AUM; tickets differ across buckets. Custom annual counts use largest-remainder allocation with at least one order per populated bucket. Infeasible inputs raise errors. Zero turnover gives zero tickets and drag, without baseline bucket matching.

Counts and turnover are annual. Monthly books preserve annual bucket/stock counts and ticket sizes. Actual CSV mode bootstraps complete q/ADV pairs. Reuse the same stock selections across AUM, scaling tickets with ADV fixed. Migration charts show mean frequencies across simulated books at current AUM, ×2 and ×3, including overflow. Daily participation does not cap bucket assignment.

## Capacity uncertainty

Monte Carlo is default; deterministic mode is optional. Set sample count (2,000) and seed (2026) in Model Calibration. Stock selection or CSV resampling varies, plus an independent final-IR Gaussian term when enabled. Alpha-decay, TC, tracking error and fitted impact parameters stay fixed. Pointwise P10–P90 IR bands and per-path capacity percentiles are distinct outputs. Solve each complete curve's first crossing of minimum IR, then report capacity P10, median and P90: a central 80% conditional range.

Keep unreached paths as right-censored beyond the horizon/model domain. The empirical inverse-CDF percentiles retain all draws; unknown percentiles display lower bounds. The histogram shows reached crossings only and the CSV retains every draw. Specific calibration parameters and liquidity-regime uncertainty remain excluded; the final Gaussian term represents assumed residual model uncertainty.

## Persistence and checks

Private cases remain in `data/strategies.user.json` (never committed). Old cases retain parameters and inputs but load into the one combined model. Saving uses `three-pillar-calibrated-books-v5`. Inputs missing universe percentiles receive the confirmed default distribution; loading does not rewrite the private file. Tables display up to two decimals; calculations, saves and CSVs retain precision.

```sh
.venv/bin/python -m unittest discover -s . -p 'test_*.py'
```

See [METHODOLOGY.md](METHODOLOGY.md) for details and academic references.


## Backtest uncertainty

Model Calibration → d) Backtest uncertainty sets `backtest_sd` (default 0.03 IR at current AUM) and `backtest_expansion` (default 1). Deviation scales as `(AUM/current_AUM)**rate`. Saved strategies preserve both; older strategies receive defaults. The fitted backtest curve stays central. Full paths use one Gaussian shock across all AUMs, so errors are perfectly correlated and pointwise bands widen with AUM. These are assumed estimation-uncertainty inputs, not standard errors fitted from the observations.

Monte Carlo mode shows exact Gaussian P10–P90 IR bands, simulated first-crossing capacity percentiles and CSV exports. Unreached paths remain censored beyond the independent backtest chart horizon. Summary compares both approaches and overlays their capacity histograms. Deterministic mode hides result bands/intervals. Use the ADV sample count and seed, with a separate backtest random stream. `test_backtest_uncertainty.py` checks Gaussian calibration, full-path coherence, crossings including turning points and censoring.

The Capacity Lab sidebar also exposes both uncertainty controls under **Backtest IR curve — advanced parameters**, alongside the fitted-curve coefficients. Sidebar and calibration-tab edits stay synchronized and save as the same strategy settings.

**Empirical IR curve — advanced parameters** in Capacity Lab exposes alpha-decay and transfer-coefficient calibration triples in two sidebar tabs. Both directions stay synchronized with Inputs & strategy; the same values drive the empirical curve, Summary and saved strategies.

The two sets of three calibration triples are edited in **Inputs & strategy**, alongside the baseline inputs and strategy save form. Model Calibration retains the alpha-decay and transfer-coefficient charts; sidebar edits remain synchronized with the input widgets.

Backtest observations and their editor start at **$0.5bn**. Legacy zero-AUM anchors migrate to $0.5bn with IR preserved on load; saving persists the change. Strategy saves also preserve manual backtest a/b/γ coefficients; changing the backtest observations refits those coefficients.


## Final empirical IR uncertainty

The empirical advanced sidebar menu and the Empirical IR curve tab expose saved `empirical_sd` (default 0.03 IR) and `empirical_expansion` (default 1). Add `Z * sd * (A/current_AUM)**rate` after all three pillars; reuse one independent standard-normal shock across each complete path, paired with its sampled cost book. The central curve is unchanged; pointwise bands and capacity quantiles include both uncertainty sources. Zero deviation restores stock-only behavior. Quantiles use each path's first threshold crossing, scanning 1,025 AUM grid points plus knots, refining local minima and bisecting roots. Non-crossing paths remain censored. UI tests use isolated temporary stores, never the user's strategy file.
