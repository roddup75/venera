# Capacity analysis

Long-only equity strategy capacity model and interactive dashboard, using the live USD liquidity bucket data.

## Start the dashboard

Requires Node.js 22.13 or later.

```sh
cd dashboard
npm ci
npm run dev -- --host 127.0.0.1 --port 3011
```

Open http://localhost:3011. Run `npm run build` from the dashboard directory to check the production build.

## Project contents

- `dashboard/`: interactive capacity scenarios and model building block demos.
- `long_only_capacity_tool.py`: Python capacity model.
- `buckets_data_live.csv`: live bucket input data in USD.
- `output/pdf/Long_Only_Capacity_Methodology.pdf`: updated methodology paper.
- `output/pdf/Long_Only_Capacity_Methodology.tex`: editable methodology source.
- `archive/` and `output/`: saved reports and model outputs.

Dependencies, local Git metadata, caches, and temporary working files are excluded from the repository. The dashboard retains its own existing local Git repository; this upload includes its source files as ordinary files.
