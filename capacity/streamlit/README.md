# Capacity Lab — Streamlit

The default **Three-pillar empirical** model combines all Model Calibration inputs: alpha retention × calibrated TC-alpha retention, less incremental estimated impact costs above the $0.5B net-IR anchor. Changes in Model Calibration update **Empirical IR curve** and **Summary** immediately. Save through Inputs & strategy. Legacy execution and isolated comparison modes remain available.


Streamlit is the only implementation. Its input JSON files live in `data/`,
and the original input CSV and spreadsheets are preserved in `data/source/`.

## Run locally

```sh
cd streamlit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Python 3.11+ is recommended. On Windows use `.venv\Scripts\Activate.ps1`.
Open http://localhost:8501 and stop with Ctrl+C.

## Views

- **Summary:** execution and historical backtest comparison, including minimum-IR and zero-IR AUM.
- **Empirical IR curve:** net IR, relative alpha capture and annual-cost metrics, one net-alpha chart with its Monte Carlo interval, and USD 500m plus ×1/×1.5/×2/×2.5/×3 current-AUM scenarios; export capacity and baseline inputs.
- **Backtest IR curve:** saved optimised-backtest observations and independent fitted `IR(A) = a - b*A^gamma`; optional sidebar parameter overrides.
- **Model Calibration:** an ADV sampler with automatic estimated-impact fitting and Monte Carlo cost curves, plus independent three-point alpha-decay and transfer-coefficient calibrations. The sampler exposes AUM, simulation count, seed and turnover; book inspection and fit details are expandable.
- **Inputs & strategy:** editable universe ADV percentiles, universe size, annual order count, historical impact buckets or actual parent-order CSV (`q`, `adv`). `p` is a total order/ADV fraction, not daily participation. Historical bucket counts and notionals are diagnostics; estimated bucket costs calibrate impact. Universe trades have equal notional and uniform stock selection. CSV trades use actual notional weights.
- **Methodology:** a download button for the current `methodology.pdf`.
  Save current sidebar parameters, edited buckets, selected actual trade tape and backtest observations under a new or existing name in the same Inputs & strategy tab.

## Saved strategies and migration

Strategies remain in `data/strategies.user.json`. Loading old strategies preserves
existing alpha, AUM, markers, backtest observations and other settings. Old model settings are retained as metadata. Saved universe ADV percentiles now drive the default equal-ticket sampler; legacy cases missing them receive the user-confirmed default distribution.
Loading does not rewrite the file. Back up this private runtime file separately.

For a legacy strategy without an explicit annual-cost input, initialization uses
`2 * (one_way_turnover_pct / 100) * notional_weighted_cost_bps`, where bucket weights
come from `valueUsdMillion`. This is portfolio annual cost in bp, not per-trade bp.
The migrated cost is editable and remains independent of subsequent bucket edits.
Saving the combined model writes the `three-pillar-universe-adv-v2` method identifier and selected trade tape.
Saving in universe mode clears the saved active tape for that case. Backtest observations
are refitted on load; transient sidebar backtest parameter overrides are not saved.

The default sampler uses the user-confirmed locally saved ADV percentiles in `data/universe-adv-data.json`, interpolated in log USD at 300 midpoint stock ranks. These are synthetic stock ADVs, not an observed 300-name tape. Each annual book selects stocks uniformly with replacement for 971 equal-notional orders. Ticket size is `2 * turnover_fraction * AUM_USD / annual_orders`, so every book reconciles exactly to annual turnover. The annual horizon is four quarters; no quarterly clustering or trade dates are simulated.

Historical ADV buckets calibrate the impact function and provide comparison frequencies; they are not the sampling distribution. Uniform selection and equal tickets need not reproduce those historical frequencies. CSV mode retains actual q/ADV pairs and their notionals. Current AUM anchors those observations; scenario previews scale tickets with fixed ADV. The empirical net-IR anchor remains $0.5B.

## Model checks

```sh
.venv/bin/python -m unittest discover -s . -p 'test_*.py'
```

Checks cover the capture integral, weighted normalization, cost units, uncapped
execution, capacity bisection, input validation, legacy strategy conversion and
persistence, plus Streamlit script execution and interactive recalculation.

See [METHODOLOGY.md](METHODOLOGY.md) for the complete methodology.

Monte Carlo is optional: set **Sampler Monte Carlo samples** (default 2,000) and
**Random seed** (default 2026) in the sidebar. In execution mode, each sample is a resampled book
with the annual order-count input (or observed row count in CSV mode). Charts show means and conditional 5th–95th
percentile ranges; deterministic mode is available for comparison. These ranges
exclude parameter and liquidity-regime uncertainty. The Fundamental Law of Active
Management relationship is documented in the Methodology tab and LaTeX source;
baseline gross alpha anchors its combined skill/breadth/construction effect.

All scenario grids, capacity searches and exported curves start at USD 500m.
Current AUM remains the calibration anchor; the execution model applies H(A) once.
Historical backtest observations below USD 500m are retained for fitting only.

## Visual calibration workflow

Summary is first; Empirical IR curve is second. Model Calibration contains three independent subtabs. The ADV sampler fits estimated bucket impact costs automatically and generates equal-ticket trading books from the universe ADV distribution (or resamples actual CSV orders). Adjust AUM, sample count, seed and turnover; inspect the books or export the cost curve from expandable details. Edit the baseline observations in Inputs & strategy when needed. No per-bucket or execution-parameter sliders are required in the sampler.

For alpha decay or TC, edit the triples; the combined Empirical IR curve and Summary update immediately. Save through Inputs & strategy. Apply buttons are used only in isolated comparison modes. Sampler controls leave the isolated triples unchanged and drive the combined model's cost and simulation assumptions.

### Calibrated alpha decay

Use the Alpha decay demo to edit three (AUM, count-weighted % parent orders >1 day, net IR) triples. Defaults are (0.5, 0, 0.60), (3, 2, 0.57), (6, 10, 0.50). The AUM and congestion-to-IR curvatures fit automatically. Edits feed the combined model immediately. Select **Calibrated alpha decay** for the isolated comparison. Save through Inputs & strategy to persist.

Other effects remain fixed: this mode uses net IR × fixed tracking error for net alpha, with no additional execution or cost adjustment. Monte Carlo uses conditional binomial multi-day counts with the annual order-count input (or observed CSV row count); the central curve is the exact calibration. Its pointwise ranges exclude calibration uncertainty and are distinct from the execution model's ADV bootstrap. Beyond the last point is labelled extrapolation; predictions stop at 100% multi-day orders.

### Calibrated transfer coefficient

Use the TC demo to edit three (TC %, AUM $bn, annual net alpha %) triples. Defaults are (60, 0.5, 1), (40, 3, 0.6), (25, 6, 0.3). Fit both links automatically; edits feed the combined model immediately. Other effects are fixed; no separate alpha-decay or cost multiplier is added. The supplied points imply nonlinear AUM-to-TC decay and a linear TC-to-alpha link. Predictions beyond the final point are labelled extrapolation and stop at zero TC. No TC uncertainty distribution is supplied, so this model is deterministic. Model selection and triples can be saved in Inputs & strategy.

### Impact costs in ADV bucket sampler

The sampler automatically fits `c(x) = a + b*x^gamma` to estimated ADV-bucket costs, giving buckets equal fitting weight. Universe portfolio aggregation uses equal ticket weights; CSV aggregation uses actual traded-value weights. Inspect the selected book's impact in bp and USD and the mean annual impact drag across AUM with an order-resampling band. Annual portfolio bp equal `2 * one_way_turnover_fraction * weighted_impact_bp`; turnover defaults to the legacy saved value or 13.9%. Baseline edits trigger a refit. Fitted parameters and CSV exports are available under Fit details and exports. There are no per-bucket sliders, fit overrides or realised-cost selector. These impact estimates drive the combined model; only incremental costs above $0.5B are deducted.

### Trade migration chart

The ADV sampler shows a grouped vertical bar chart of trade frequencies at current AUM, ×2 and ×3. The same seeded book is used for all three; scaling order/ADV changes bucket membership while preserving order count. An overflow bucket retains trades beyond the highest boundary. These scenarios are anchored to Capacity Lab current AUM, independently of Sampler AUM and the impact chart horizon. Expand Bucket migration data for the table and CSV export.

### Combined empirical model

The initial net IR is the alpha-decay first point (default 0.60 at $0.5B). Normalize the TC alpha curve by its first annual-alpha value, multiply it by the alpha-decay IR curve, then subtract `(annual_impact_bp(A) - annual_impact_bp(0.5)) / (100 * tracking_error_pct)`. The TC curve is used as a relative factor. No second baseline alpha or full baseline cost is added. Summary shows all three losses and the historical backtest comparison. Monte Carlo combines stock-sampled or CSV-resampled incremental costs with independent binomial congestion counts; TC and fitted parameters remain fixed. The domain ends when either retained-alpha factor reaches zero. The central curve is calibrated, with conditional pointwise percentile bands.

Tables display at most two decimals, with order/ADV ratios shown as percentages. Model calculations, saved values and CSV exports preserve full precision. Select Deterministic (default) or Monte Carlo in Capacity Lab to hide or show the empirical curve's conditional intervals.

Sampler AUM defaults to current AUM. Universe ticket size follows AUM, annual order count and turnover. It follows changes in current AUM until a custom preview scenario is selected. Scenario previews scale order sizes while keeping stock ADV fixed. The separate empirical net-IR anchor remains $0.5B.
