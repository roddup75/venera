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

The confirmed saved percentiles in `data/universe-adv-data.json` approximate 300 stock ADVs by log-dollar interpolation at midpoint stock ranks. Select stocks uniformly with replacement for 971 equal-ticket annual orders. Each ticket is `2 * annual_turnover_fraction * AUM_USD / annual_orders`. Annual count and turnover are annual inputs; the strategy rebalances monthly. The inspected book can be exported as 12 monthly books while preserving annual stock counts and notional. Fixed ADV and independent selections make calendar grouping neutral for annual costs.

Historical bucket frequencies are diagnostic comparisons, not sampling probabilities or calibration targets. Actual-order CSV mode bootstraps complete q/ADV pairs and uses their actual notionals. The same sampled selections are reused across AUM; tickets scale, ADV stays fixed. Migration charts compare current AUM, ×2 and ×3, retaining an overflow bucket.

## Capacity uncertainty

Monte Carlo is default; deterministic mode is optional. Set sample count (2,000) and seed (2026) in Model Calibration. Only stock selection or CSV resampling varies. Alpha-decay, TC, tracking error and fitted impact parameters stay fixed. Pointwise P20–P80 IR bands and per-path capacity percentiles are distinct outputs. Solve each complete curve's first crossing of minimum IR, then report capacity P20, median and P80: a central 60% conditional range.

Keep unreached paths as right-censored beyond the horizon/model domain. The empirical inverse-CDF percentiles retain all draws; unknown percentiles display lower bounds. The histogram shows reached crossings only and the CSV retains every draw. Calibration, liquidity-regime and forecast uncertainty are excluded.

## Persistence and checks

Private cases remain in `data/strategies.user.json` (never committed). Old cases retain parameters and inputs but load into the one combined model. Saving uses `three-pillar-current-gross-v4`. Inputs missing universe percentiles receive the confirmed default distribution; loading does not rewrite the private file. Tables display up to two decimals; calculations, saves and CSVs retain precision.

```sh
.venv/bin/python -m unittest discover -s . -p 'test_*.py'
```

See [METHODOLOGY.md](METHODOLOGY.md) for details and academic references.
