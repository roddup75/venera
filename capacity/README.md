# Capacity Lab

Streamlit is the only implementation. One model combines impact costs, alpha decay and transfer-coefficient retention, compared with a separate historical backtest IR curve.

Baseline gross alpha is editable at current AUM. The calibrated pillars define relative shape around that anchor; full estimated impact costs are deducted once. The sampler uses saved ADV percentiles to approximate 300 stocks and generates 971 annual orders calibrated to historical bucket counts and value shares, sampling compatible stock ADVs within buckets across monthly rebalances.

Monte Carlo combines stock selections with independent final-IR Gaussian uncertainty. Its main output is the 10th–90th percentile interval of AUM at minimum IR, solved from each simulated curve. Summary presents results and tables for both approaches, with the simulation histogram last.

## Run

```sh
cd streamlit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

See [Streamlit README](streamlit/README.md) and [methodology](streamlit/METHODOLOGY.md).

Backtest uncertainty has a separate calibration tab: set IR deviation at current AUM and its expansion rate to generate widening Gaussian bands and a P10–P90 capacity interval alongside empirical results.
