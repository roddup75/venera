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
- **Empirical IR curve:** net IR and net alpha, optional P20–P80 bands, scenario table, pillar-loss breakdown and exports.
- **Backtest IR curve:** independent fit to historical AUM/IR observations; replace illustrative defaults with actual backtests.
- **Model Calibration:** ADV sampler, alpha-decay triples and TC triples. All three pillars feed the same combined curve immediately; there are no separate capacity-model options.
- **Inputs & strategy:** universe ADV percentiles, universe size, annual parent-order count, historical impact buckets or actual `q,adv` CSV. Save current inputs and parameters here.
- **Methodology:** download the current PDF.

## Gross-alpha anchor and costs

Let `R(A)` be alpha-decay retention times TC-alpha retention. Gross alpha at AUM A is `gross_alpha_current * R(A) / R(current_AUM)`. Net IR is `(gross_alpha(A) - annual_impact_bp(A)/100) / tracking_error_pct`. Annual alpha and tracking error are percentage points. The initial calibration values normalise pillar shapes, not the combined performance level. USD 0.5bn is only the lower calculation boundary. Gross alpha at current AUM is fixed across simulations; net IR varies through sampled costs. Current AUM must have positive combined retention.

The impact curve `a+b*x**gamma` is fitted to estimated historical bucket costs with equal fitting weights. Annual impact is twice one-way turnover fraction times notional-weighted impact. Full annual costs are deducted once. The optional IR breakdown measures losses from model-implied net IR at $0.5bn; baseline costs are already included in that reference.

Daily participation is an execution-time reference in alpha calibration, not an input to bucket assignment or the combined IR curve. Retired half-life, cost-stress and retained-alpha controls are preserved only as saved metadata.

## Annual sampling and monthly rebalancing

The saved percentiles in `data/universe-adv-data.json` approximate 300 stock ADVs by log-dollar interpolation at midpoint ranks. Historical bucket counts fix annual composition (971 orders by default). A bucket ticket is `2 * annual_turnover_fraction * AUM_USD * bucket_value_share / bucket_order_count`. Within each bucket, draw uniformly with replacement among stocks whose ticket/ADV fits its bounds. This preserves both historical count and notional shares at current AUM; tickets differ across buckets. Custom annual counts use largest-remainder allocation with at least one order per populated bucket. Infeasible inputs raise errors. Zero turnover gives zero tickets and drag, without baseline bucket matching.

Counts and turnover are annual. Monthly books preserve annual bucket/stock counts and ticket sizes. Actual CSV mode bootstraps complete q/ADV pairs. Reuse the same stock selections across AUM, scaling tickets with ADV fixed. Migration charts show mean frequencies across simulated books at current AUM, ×2 and ×3, including overflow. Daily participation does not cap bucket assignment.

## Capacity uncertainty

Monte Carlo is default; deterministic mode is optional. Set sample count (2,000) and seed (2026) in Model Calibration. Only stock selection or CSV resampling varies. Alpha-decay, TC, tracking error and fitted impact parameters stay fixed. Pointwise P20–P80 IR bands and per-path capacity percentiles are distinct outputs. Solve each complete curve's first crossing of minimum IR, then report capacity P20, median and P80: a central 60% conditional range.

Keep unreached paths as right-censored beyond the horizon/model domain. The empirical inverse-CDF percentiles retain all draws; unknown percentiles display lower bounds. The histogram shows reached crossings only and the CSV retains every draw. Calibration, liquidity-regime and forecast uncertainty are excluded.

## Persistence and checks

Private cases remain in `data/strategies.user.json` (never committed). Old cases retain parameters and inputs but load into the one combined model. Saving uses `three-pillar-calibrated-books-v5`. Inputs missing universe percentiles receive the confirmed default distribution; loading does not rewrite the private file. Tables display up to two decimals; calculations, saves and CSVs retain precision.

```sh
.venv/bin/python -m unittest discover -s . -p 'test_*.py'
```

See [METHODOLOGY.md](METHODOLOGY.md) for details and academic references.


## Backtest uncertainty

Model Calibration → d) Backtest uncertainty sets `backtest_sd` (default 0.03 IR at current AUM) and `backtest_expansion` (default 1). Deviation scales as `(AUM/current_AUM)**rate`. Saved strategies preserve both; older strategies receive defaults. The fitted backtest curve stays central. Full paths use one Gaussian shock across all AUMs, so errors are perfectly correlated and pointwise bands widen with AUM. These are assumed estimation-uncertainty inputs, not standard errors fitted from the observations.

Monte Carlo mode shows exact Gaussian P20–P80 IR bands, simulated first-crossing capacity percentiles and CSV exports. Unreached paths remain censored beyond the independent backtest chart horizon. Summary compares both approaches and overlays their capacity histograms. Deterministic mode hides result bands/intervals. Use the ADV sample count and seed, with a separate backtest random stream. `test_backtest_uncertainty.py` checks Gaussian calibration, full-path coherence, crossings including turning points and censoring.

The Capacity Lab sidebar also exposes both uncertainty controls under **Backtest IR curve — advanced parameters**, alongside the fitted-curve coefficients. Sidebar and calibration-tab edits stay synchronized and save as the same strategy settings.

**Empirical IR curve — advanced parameters** in Capacity Lab exposes alpha-decay and transfer-coefficient calibration triples in two sidebar tabs. Both directions stay synchronized with Model Calibration; the same values drive the empirical curve, Summary and saved strategies.
