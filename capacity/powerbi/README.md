# Capacity Lab for Power BI

This folder contains a portable Power BI version of the Capacity Lab model. The generated CSV tables reproduce the dashboard's current defaults and contain an AUM grid from $0.1bn to $15.0bn in $0.1bn increments.

## Build the report

1. Open Power BI Desktop and choose **Get data > Text/CSV**.
2. Import every file in `data/`. Use the first row as headers and keep the numeric columns as decimal or whole numbers.
3. In `Migration`, sort `Participation_bucket` by `Bucket_order`. In `Execution Outcomes`, sort `Execution_outcome` by `Outcome_order`.
4. Add the measures from `CapacityLab.dax` to the `Scenarios` table.
5. Import `CapacityLab-theme.json` from **View > Themes > Browse for themes**.
6. Save the result as `CapacityLab.pbix` or as a Power BI Project (`.pbip`) for source control.

Power BI Desktop's numeric range parameters are limited to 1,000 values. The supplied AUM grid stays below this limit and can be used directly as a single-select slicer.

## Suggested pages

### Overview

- Single-select slicers: `Scenarios[Model]`, `Scenarios[AUM_USD_bn]`.
- Use **Format > Edit interactions** so the AUM slicer filters the cards and scenario table but does not reduce either AUM line chart to one point.
- Cards: `Net IR`, `IR Capacity`, `Alpha Capture`, `Average Days`.
- Line chart: axis `AUM_USD_bn`; values `Net_IR`. Add a constant line at 0.40.
- Line chart: axis `AUM_USD_bn`; values `Implemented_alpha_pct`, `Net_alpha_pct`.
- Table: AUM, impact, annual drag, alpha capture, net alpha, net IR, retained alpha, average days and three-plus-days share.

### Liquidity migration

- Slicers: `Migration[Model]`, `Migration[View]`, `Migration[AUM_USD_bn]`.
- Clustered column chart: axis `Participation_bucket`; value `Share_pct`; legend `AUM_USD_bn`.
- Execution chart: axis `Execution_outcome`; value `Parent_orders_pct`; legend `AUM_USD_bn`.
- Input tables from `Buckets` and `ADV Quantiles`.

### Demo building blocks

- Count migration: filter `Migration[View]` to `Parent orders`; compare `ADV calibrated` with `Burr count calibrated`.
- Impact: scatter or line chart using `Buckets[Expected_impact_bp]` and `Buckets[Realised_impact_bp]` against participation buckets.
- Alpha decay: line chart with `Day` on the x-axis, `Remaining_alpha_pct` on the y-axis, and `AUM_USD_bn` plus `Half_life_days` as legends or slicers.

## Refreshing the model data

From `dashboard/`, run:

```bash
node --experimental-strip-types scripts/export-powerbi.mjs
```

Refresh the Power BI report after regeneration. The export uses `bucket-data.json`, `universe-adv-data.json`, and the same ADV and Burr engines as the web dashboard.

## Model scope

The Power BI version is a scenario-grid implementation. It supports interactive filtering across AUM, model, migration view, half-life examples, and the supplied calibration tables. Changing structural assumptions such as turnover, holdings, participation or impact coefficients requires regenerating the CSV tables and refreshing Power BI.
