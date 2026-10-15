# Capacity Lab

Streamlit is the only implementation. The default **Three-pillar empirical** model combines all inputs in Model Calibration:

- Estimated impact costs fitted automatically from ADV buckets.
- Alpha retention calibrated from three (AUM, multi-day trade %, net IR) triples.
- TC-alpha retention calibrated from three (TC %, AUM, annual alpha %) triples.

The Empirical IR curve multiplies the two retention factors and subtracts only the increase in impact costs above the $0.5B net-IR anchor. Model Calibration edits update the curve and Summary immediately. Save inputs and settings through Inputs & strategy. The separate historical backtest comparison remains available. Legacy execution and isolated calibration modes can also be selected.

## Run

```sh
cd streamlit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501. On Windows activate with `.venv\Scripts\Activate.ps1`.

## Views

Summary is first and shows capacity thresholds, backtest comparison and the three-pillar IR decomposition. Empirical IR curve shows net IR and one net-alpha chart with conditional Monte Carlo ranges. Model Calibration contains the ADV sampler, alpha decay and TC calibration. Inputs & strategy combines editable input data and local saving. Methodology contains the current PDF download.

The sampler displays vertical bars for trade frequency by ADV bucket at current AUM, ×2 and ×3, using the same simulated book. AUM, simulation count, seed and turnover are editable. Detailed book inspection and exports are expandable. Representative order ratios and estimated costs come from Inputs & strategy; there are no per-bucket sliders.

## Data and interpretation

Inputs live in `streamlit/data/`; originals are preserved in `streamlit/data/source/`. Parent-order CSVs require positive `q` and `adv` columns in the same currency. Order sizes scale from current AUM while ADV stays fixed. The net-IR anchor is the first alpha-calibration point at $0.5B. TC alpha is used as a relative factor rather than a second absolute anchor.

The empirical curve defaults to Deterministic mode without intervals. Select Monte Carlo for conditional intervals, with 2,000 samples and seed 2026 as initial simulation settings. Combined bands vary order-resampled incremental costs and independent binomial congestion counts; TC and fit parameters stay fixed. They are conditional pointwise percentile ranges. The central curve uses the calibrated congestion share and mean bootstrap impact. Predictions beyond calibration points are labelled extrapolation; the combined domain ends when either retention factor reaches zero.

## Verify

```sh
streamlit/.venv/bin/python -m unittest discover -s streamlit -p 'test_*.py'
```

See [methodology](streamlit/METHODOLOGY.md) and [Streamlit documentation](streamlit/README.md).

Tables display at most two decimals, with order/ADV ratios shown as percentages. Model calculations, saved values and CSV exports preserve full precision. Select Deterministic (default) or Monte Carlo in Capacity Lab to hide or show the empirical curve's conditional intervals.
