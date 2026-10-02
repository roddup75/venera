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
