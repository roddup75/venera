# Capacity Lab — Streamlit

This folder contains the Streamlit version of the Capacity Lab dashboard. It reads the same live bucket and universe ADV JSON files as the TypeScript dashboard and recalculates scenarios when inputs change.

## Run locally

Python 3.11 or later is recommended.

```sh
cd streamlit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Streamlit normally opens `http://localhost:8501`. Stop it with `Ctrl+C`.

## Included views

- Overview capacity metrics, net IR and alpha decomposition
- Traded-dollar, parent-order count and execution-outcome migration
- Count-calibrated Burr, impact and alpha-decay demos
- Live execution buckets and universe ADV quantiles
- Strategy creator for saving model defaults, execution buckets and ADV curves together

## Saved strategies

Use **Strategy creator** to start from an existing case, edit its Capacity Lab defaults and input tables, and save it under a new or existing name. The **Saved strategy** menu in the sidebar loads the selected strategy throughout the dashboard.

The Swiss case is built in. User-created cases are stored locally in `data/strategies.user.json`; this runtime file is excluded from Git so private calibration data is not committed accidentally. Back up that file separately if the saved strategies need to move to another computer.

Each strategy also stores its trading-universe size. The Swiss default is 203 stocks. Holdings cannot exceed the eligible universe, and the ADV calibration converts the percentile curve into a finite stock-count grid (using every stock up to 1,000 names and a 1,000-point approximation for larger universes).
