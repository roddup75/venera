# Capacity analysis

Long-only equity strategy capacity model and interactive dashboard, using the live USD liquidity bucket data.

## Run the web dashboard

Requires Node.js 22.13 or later.

```sh
cd dashboard
npm ci
npm run dev -- --host 127.0.0.1 --port 3011
```

Open http://localhost:3011. Stop the server with `Ctrl+C` in the terminal that started it.

Run the production checks from the dashboard directory with:

```sh
npm run build
node --experimental-strip-types --test tests/adv-migration.test.mjs
```

## Run the Power BI dashboard

The portable Power BI package is in `powerbi/`, with a single-file copy at
`CapacityLab-PowerBI.zip`. Power BI Desktop runs on Windows.

1. Extract `CapacityLab-PowerBI.zip`, or copy the `powerbi/` directory to the Windows machine.
2. Open Power BI Desktop and choose **Get data > Text/CSV**.
3. Import every CSV in `powerbi/data/` and promote the first row to headers.
4. Add the measures in `powerbi/CapacityLab.dax` to the `Scenarios` table.
5. Import `powerbi/CapacityLab-theme.json` through **View > Themes > Browse for themes**.
6. Follow `powerbi/README.md` to build the Overview, Liquidity migration and Demo building blocks pages.
7. Save the completed report as `CapacityLab.pbix`, or as a `.pbip` project when source-controlled Power BI project files are preferred.

The Power BI version is generated on an AUM grid from $0.1bn to $15.0bn. To refresh it after changing the model inputs, run:

```sh
cd dashboard
node --experimental-strip-types scripts/export-powerbi.mjs
```

Then refresh the imported tables in Power BI Desktop. Structural changes to turnover, holdings,
participation limits or calibration parameters require this regeneration step; AUM, model and
view selections remain interactive inside the report.

## Project contents

- `dashboard/`: interactive capacity scenarios and model building block demos.
- `powerbi/`: Power BI data tables, DAX measures, theme and report-building instructions.
- `CapacityLab-PowerBI.zip`: portable copy of the Power BI package.
- `long_only_capacity_tool.py`: Python capacity model.
- `buckets_data_live.csv`: live bucket input data in USD.
- `output/pdf/Long_Only_Capacity_Methodology.pdf`: updated methodology paper.
- `output/pdf/Long_Only_Capacity_Methodology.tex`: editable methodology source.
- `archive/` and `output/`: saved reports and model outputs.

Dependencies, local Git metadata, caches, and temporary working files are excluded from the repository. The dashboard retains its own existing local Git repository; this upload includes its source files as ordinary files.

## ADV-calibrated migration

In the dashboard sidebar select **Migration model → ADV-calibrated migration**,
then open **Liquidity migration**. Burr remains the default comparison model.
The ADV engine uses the fixed historical anchor of $3.4bn, 40 assumed holdings,
971 annual parent orders and $944.475m traded value (13.889338% one-way turnover).
The 13.9% scenario default is rounded and therefore produces slightly more trading.

The model interpolates ADV in log dollars between the supplied stock-count
percentiles. For each execution bucket, it creates a grid of ADV and participation
values and exponentially tilts prior weights to reconcile both count and dollars.
A broad log-ticket prior has standard deviation 1.5. Liquidity preference modifies
the ADV prior and triggers refitting. This identifies a plausible joint distribution,
not the actual portfolio or a unique historical order allocation.

Tickets scale as `(A / 3.4bn) * (40 / holdings)`; frequency scales as
`(holdings / 40) * (turnover / historical turnover)`. ADV stress changes available
volume without refitting historical data. These rules conserve `annual value = 2*A*T`.
Execution respects the daily participation cap and reports required days without
truncation. The horizon limits completed notional; uncompleted fractions receive
no captured alpha and incur no execution impact. Alpha and costs are normalized
to the historical portfolio under the selected execution policy. This normalization
means changing that policy also changes the reference; it is not an absolute
historical execution-policy backtest. Stock overlap and concurrent orders cannot
be inferred from these aggregate inputs.

The ADV model uses observed counts and dollar values, not editable rounded share
percentages. Edited expected costs still adjust its impact anchor. The original
Burr demo remains explicitly labeled, while the alpha-decay demo uses the selected
engine. CSV exports identify the engine and include ADV execution-feasibility fields.

Model checks (Node 22.13+):

```sh
cd dashboard
node --experimental-strip-types --test tests/adv-migration.test.mjs
```
