# Methodology implementation audit

**Historical snapshot:** this audit describes the 14 October execution-delay implementation, not the current default three-pillar model. As of 15 October, the default impact pillar samples compatible stock ADVs conditional on historical bucket counts and bucket-specific ticket sizes; see METHODOLOGY.md and universe_sampler.py for current behavior.

Reviewed 14 October 2026. Reference: **An Execution-Adjusted Transfer Coefficient Model for Equity Strategy Capacity**, Version 0.1, five pages, supplied as `capacity_methodology.pdf`.

**Result: the current dashboard implements the core execution-delay equations and the empirical order-bootstrap route, but does not implement every feature in this reference.** The aggregate-data route is a representative-order approximation. Restoring Monte Carlo did not restore the original synthetic-book construction and calibration machinery.

This audit changes no model, input data, or methodology source. All 21 existing tests pass; that verifies the implemented subset rather than full reference coverage.

## Evidence

- [Reference PDF](/Users/martosdupleich/Downloads/capacity_methodology.pdf)
- [Model and Monte Carlo implementation](/Users/martosdupleich/Documents/python/returns00/capacity/streamlit/capacity_model.py)
- [Dashboard controls, charts and exports](/Users/martosdupleich/Documents/python/returns00/capacity/streamlit/app.py)
- [Live bucket inputs](/Users/martosdupleich/Documents/python/returns00/capacity/streamlit/data/bucket-data.json)
- [Strategy persistence](/Users/martosdupleich/Documents/python/returns00/capacity/streamlit/strategy_store.py)

PDF page references below count physical pages, including the title page.

## Core model coverage

| Reference feature | Status | Implementation and difference |
|---|---|---|
| Total parent-order size / ADV, rather than daily participation; proportional scaling with AUM (§1, p1) | Implemented | CSV `q/adv` or editable representative ratios; scaled ratios are `s*x`. |
| Fixed liquidity, construction recipe, order count and forecast assumptions (§1) | Implemented assumptions | No liquidity-regime or changing-portfolio simulation. Each bootstrap book reuses its composition across AUM. |
| Six specified bucket boundaries, including an unbounded >100% tail (§1) | Different preset / partial | Live buckets split 10–50% into 10–25% and 25–50% and stop at 100%. Bounds and rows are editable. Actual CSV orders can exceed 100%, but literal infinite bucket bounds fail validation. |
| Continuous execution time `D=s*x/p`, including intraday completion (§3, p2) | Implemented | No one-day floor or truncation. |
| Exponential half-life and uniform-fill capture integral, including `g(0)=1` (§3) | Implemented | Numerically stable `expm1` calculation, with the zero-duration limit handled. |
| Weighted capture and normalization `H=G(s)/G(1)` (§4, p3) | Implemented | Aggregate notional weighting; normalization occurs independently in every simulated book, then book results are averaged. |
| Alpha-opportunity weights, with notional weights as fallback (§4) | Partial | Only notional weights are supported; a CSV alpha-contribution column would be discarded. |
| Trade-specific half-lives `h_i` (§4 equation 3) | Missing | One common half-life is used. |
| Absolute construction TC and `TC_eff=TC_construction*H` (§1/§4) | Partial | `H` is calculated; the TC relationship is documented. There is no construction-TC input or absolute effective-TC output. These are unnecessary for net alpha when observed baseline gross alpha is the anchor. |
| Fundamental Law interpretation (§10, p5) | Documented | The current dashboard adds an explicit `IR≈IC*sqrt(BR)*TC` explanation. It does not independently estimate IC, breadth or TC; the reference also uses baseline alpha rather than requiring those independent inputs. |
| Baseline gross alpha already includes baseline delay; fixed-TE net IR (§6) | Implemented | The baseline is not penalized a second time; alpha/TE percentage-point units and cost-bp conversion are explicit. |
| Signed forecast contributions and evolving signal schedules (§4 caveat) | Not implemented alternative | Only positive order notionals and nonnegative notional weights are supported. No forecast updates or signed alpha accounting. |
| Discrete daily execution alternative (§3 caveat) | Not implemented alternative | The continuous schedule is the selected baseline. |

## Book generation and Monte Carlo coverage

| Reference feature | Status | Implementation and difference |
|---|---|---|
| Bootstrap actual complete `(q, ADV)` pairs (§2/§7) | Implemented | Order-level IID bootstrap preserves each observed size/liquidity pair. |
| Configurable simulations, reproducible seed, observed number of orders per book (§7/§9) | Implemented | Monte Carlo is default; 2,000 books, editable count and seed. CSV mode uses the number of rows; aggregate mode uses rounded total bucket counts. |
| Sample bucket membership from observed count shares (§2) | Implemented | Multinomial bucket counts with probabilities proportional to observed counts. |
| Within-bucket log-uniform order-size draws, with a positive first-bin floor (§2) | Missing | Every proxy order in a bucket has the same editable representative ratio. |
| Sample universe ADV and account for the joint size/ADV relationship (§2) | Missing in aggregate mode | No universe-ADV sampler, selection tilt or joint-distribution fit. The actual-trade route retains the empirical pairs. |
| Fitted or stress-tested open-ended tail (§2) | Missing | No tail distribution or tail-fitting parameter. A finite proxy row or actual large orders can be supplied manually. |
| Match both count shares and notional shares and annual turnover (§2) | Partial | Proxy notional is `Q_b/n_b`, so unnormalized dollar totals match observed bucket totals in expectation. Realized bootstrap books vary. There is no calibrated synthetic baseline, turnover target, or dollar-total validation. |
| Calibration diagnostics and rejection of material mismatches (§2 validation) | Missing | Positivity and finite-value checks exist, but not the specified moment checks, turnover reconciliation, traded-name ADV checks or tolerance rejection. |
| Preserve the same book across AUM checkpoints (§7) | Implemented | The same seeded bootstrap draws are reused for normalization, intervals and all AUM values. |
| Mean curves and conditional 5th–95th percentiles (§7) | Implemented | Capture, net alpha and IR ranges are exported. They are explicitly conditional composition-resampling ranges. |
| Block bootstrap by month/quarter with recalibration (§7/§9) | Not implemented extension | CSV validation retains only `q` and `adv`; timestamps are not used. |
| Future trade/liquidity simulation and parameter uncertainty (§7) | Not implemented extension | Half-life, costs, future liquidity and model uncertainty are not randomized. |

## Costs, capacity and outputs

| Reference feature | Status | Implementation and difference |
|---|---|---|
| Constant annual impact-bp drag at fixed participation and turnover (§5) | Equivalent baseline | Explicit annual portfolio cost is constant when cost elasticity is zero. Dollar costs therefore grow with AUM. |
| Per-order participation cost `c_i=k_i*p_i^eta` and bucket-specific expected impact (§5/§9) | Missing | Costs are an explicit annual input. Bucket cost columns initialize legacy defaults but do not feed current simulations or automatically reprice a changed participation rate. Composition-driven cost variability is not simulated. |
| Cost elasticity `c(s)=c(1)*s^gamma` (§5) | Implemented at aggregate level | A single elasticity scales the whole annual cost input. |
| Separate other costs `C_other(s)` (§6) | Partial | A constant other cost can be included in total annual cost at gamma=0. Separate fixed other costs alongside scaling impact costs are not supported. |
| Spread, fees, temporary/permanent impact breakdown (§5, where data permit) | Not implemented optional detail | No component-level cost inputs. |
| Net-alpha or IR decision threshold (§6) | Partial | Minimum IR, zero IR, and retained-alpha criteria are available. A direct absolute net-alpha threshold is not exposed, although it can be converted to an IR threshold when TE is fixed. |
| Operational capacity based on multi-day order share (§6) | Missing | Multi-day count and notional shares are displayed, but cannot define the capacity threshold. |
| Scaled-order bucket reassignment and count/notional shares (§7) | Intentionally excluded | Removed under the earlier request to remove migration models. Simple bucket reporting could be restored without restoring those models, but it is currently absent. |
| Half-life, participation and gamma stresses (§7) | Implemented | Half-life/participation comparisons plus editable aggregate cost elasticity. Trade-selection, turnover and correlated-liquidity stresses are absent. |
| Reference AUM grid `1,1.5,2,3,4,5,7,10` (§7) | Different UI | Summary tables use `1,1.5,2,2.5,3`. Charts can extend to larger AUM via the horizon control; the reference checkpoint table is not supplied. |
| CSV curve, percentile-band and baseline-tape outputs; PNG figure (§8/§9) | Functionally partial | Capacity CSV combines means and percentile columns; baseline inputs and sensitivity CSVs are downloadable. Plotly provides PNG chart download. There is no original batch CLI or the exact four named output files. |
| Exact synthetic numerical illustration (§8) | Not shipped | Controls can express its alpha, half-life, participation and annual-cost assumptions, but its synthetic trade tape and generator were removed. The exact plotted curve is not reproduced. |
| Signal-half-life estimation from trade forecasts (§9) | External calibration task | Half-life is a supplied parameter; no estimator is implemented. |
| Variable-participation optimization (§9, next iteration) | Not implemented extension | Participation is fixed and user-selected; no alpha-versus-cost optimizer or execution constraints. |
| Realized holdings, risk exposure and tracking-error feedback (§6, later version) | Not implemented extension | Tracking error is held fixed as in the reference baseline. |

## Confirmed checks and interpretation issues

1. **Core arithmetic agrees with the reference baseline example.** With gross alpha of 300 bp and annual cost of 22.5 bp, the current engine returns 277.5 bp net alpha at baseline, with annual costs unchanged at ×10 when gamma=0. Reproducing the rest of the example curve additionally requires the original synthetic book.
2. **Bucket costs are not active simulation inputs.** Multiplying every bucket's expected cost by ten while keeping the explicit annual cost at 22.5 bp leaves modeled annual drag at 22.5 bp. This follows the simplification and is labelled in the UI, but differs from a bucket-cost-driven implementation.
3. **A bucket-validation gap remains.** A representative ratio of zero is accepted for a bucket with positive traded notional. The reference's positive first-bin floor avoids this impossible finite-ADV proxy order. This should be rejected or explicitly treated as a limiting approximation.
4. **The reference turnover convention is ambiguous.** It calls `T` one-way turnover but uses `T*c` as cost drag and `T*A0` as total traded dollars. The dashboard's legacy conversion defines buys plus sells/AUM as twice one-way turnover and uses `2*T*c`. The explicit annual-cost input avoids the ambiguity. The convention must be agreed before restoring turnover-based calibration; blindly copying the symbol would risk a factor-of-two change.
5. **Passing tests does not establish empirical calibration.** The 21 checks validate implemented equations, bootstrap behavior, persistence and UI execution. They do not establish that the missing synthetic-book calibration or predictive uncertainty methods are present.

## Recommended priorities

If the reference PDF is to become the full specification, prioritize aggregate within-bucket/tail sampling, joint ADV calibration and diagnostics; then connect per-order/bucket execution costs and separate fixed other costs. Add an operational capacity threshold and optional opportunity weights/trade-specific half-lives next. Treat block bootstrapping, predictive liquidity shocks, execution optimization and dynamic risk as separately scoped extensions, as the paper does.

Keep the migration models removed unless requested otherwise. A scaled-bucket reporting table is separable from those models. With actual trade data available, the existing empirical bootstrap route is closer to the paper's preferred path and avoids the unidentified aggregate joint-distribution problem.
