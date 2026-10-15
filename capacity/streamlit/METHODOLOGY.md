The **Empirical IR curve** uses all three Model Calibration pillars by default: estimated impact costs, alpha decay and transfer-coefficient decay. Section 14 defines their combination. Sections 1–8 document the legacy execution model, and sections 10–11 define the isolated calibration functions. Legacy and isolated modes remain available for comparison.

The model estimates how larger orders take longer to execute and capture less of a decaying signal. It uses Monte Carlo parent-order resampling by default, with a notional-weighted execution-delay calculation inside each simulated book. There is no migration distribution.

**1. Baseline inputs**

Let $A_0$ be current AUM, $s=A/A_0$, $q_i$ the total positive parent-order notional, $V_i$ its average daily traded value and $x_i=q_i/V_i$. Orders and ADV must use the same currency. Buys and sells enter as positive traded amounts. Each order scales proportionally with AUM; liquidity, portfolio construction, order frequency and turnover stay fixed.

A trade CSV supplies `q` and `adv`, with weights $w_i=q_i/\sum_j q_j$. With bucket inputs, each bucket supplies one editable representative $x_b$ (`p`, a **fraction**, despite its legacy name), traded value $Q_b$ and count $n_b$. We use $w_b=Q_b/\sum_j Q_j$; reported rounded share percentages do not determine weights. Counts determine bucket-membership probabilities in Monte Carlo and the count-weighted multi-day diagnostic; traded values determine the notional of each proxy order. Existing buckets describe total parent orders, as confirmed by the user.

The bucket version approximates the unknown within-bucket distribution. Generally $g(E[D])\ne E[g(D)]$, so representative points do not reproduce a full trade tape. Vary representative points within their bounds to assess this assumption, especially for large orders. For an open-ended tail, supply an explicit finite representative and stress range. No universe ADV distribution is needed once order/ADV ratios and notional weights are available.

**2. Execution time and absolute signal capture**

With a fixed daily participation fraction $p$ and signal half-life $h$ in trading days:

$$D_i(s)=\frac{s x_i}{p},\qquad \lambda=\frac{\log 2}{h}.$$

Uniform execution over $[0,D]$ gives:

$$g(D;h)=\frac{1-e^{-\lambda D}}{\lambda D},\qquad g(0;h)=1.$$

Execution times are continuous trading-day equivalents: an order can finish intraday. There is no minimum one-day floor, horizon cap, grandfathered participation or unfinished-order adjustment. This model assumes every order eventually completes; it does not simulate overlapping orders, cancellation or changing signals.

**3. Relative alpha capture**

$$G(s)=\sum_i w_i g(D_i(s);h),\qquad H(s)=\frac{G(s)}{G(1)}.$$

The dashboard reports **relative alpha capture** as $100H(s)$ and **absolute capture** as $100G(s)$. Relative capture equals 100% at current AUM. In Monte Carlo, apply this normalization within each book and average its results. This is an economic multiplier, not a measured portfolio-construction transfer coefficient. Normalize the weighted aggregate once; do not average per-order capture ratios.

**4. Fundamental Law of Active Management**

The extended Fundamental Law links expected gross information ratio to forecast skill, independent breadth and portfolio-construction efficiency:

$$IR_{\rm gross}\approx IC\sqrt{BR}\,TC_{\rm construction}.$$

Here $IC$ is the information coefficient, $BR$ is the number of independent investment decisions per year and $TC_{\rm construction}$ is the construction transfer coefficient. Parent-order count and number of holdings are not estimates of independent breadth. See [CFA Institute, Analysis of Active Portfolio Management](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/analysis-active-portfolio-management).

In this implementation, observed baseline gross alpha after baseline execution anchors the combined baseline effect:

$$\frac{\alpha_{g,0}}{\sigma_{TE}}\approx IC\sqrt{BR}\,TC_{\rm eff}(1),\qquad TC_{\rm eff}(s)=TC_{\rm eff}(1)H(s).$$

This last relation is a reduced-form economic mapping. Effective TC incorporates implementation capture; neither it nor $H$ is asserted to be a measured forecast/position correlation. Holding forecast skill, independent breadth and construction efficiency fixed as AUM scales gives:

$$IR_{\rm net}(s)=\frac{\alpha_{g,0}}{\sigma_{TE}}H(s)-\frac{C_0s^\gamma}{100\sigma_{TE}}.$$

The model does not estimate $IC$, $BR$ or construction TC separately from liquidity buckets. It does not multiply observed gross alpha by these factors again. The execution-capture assumption is an additional model choice, not a result implied by the Fundamental Law alone.

**5. Net alpha, annual costs and IR**

Baseline gross alpha $\alpha_{g,0}$ is annual alpha **after baseline execution delay and before the modeled annual costs**. An ideal frictionless backtest alpha cannot be used interchangeably without adjusting the baseline.

$$\alpha_{\rm net}(s)=\alpha_{g,0}H(s)-\frac{C_0s^\gamma}{100},\qquad IR_{\rm net}(s)=\frac{\alpha_{\rm net}(s)}{\sigma_{TE}}.$$

Alpha and tracking error above are in percentage points; $C_0$ is total annual portfolio cost in basis points. At $s=1$, net alpha is baseline gross alpha minus $C_0/100$. At the default $\gamma=0$, annual cost **in portfolio bp** stays constant; dollar costs grow with AUM. This is a simplifying assumption, not an empirical impact law. Positive $\gamma$ is an optional cost stress, not a fitted impact exponent. Participation sensitivities hold the selected cost rule fixed and do not claim to estimate the cost of changing execution speed.

Legacy saved strategies receive an initial annual-cost input from:

$$C_0=2\left(\frac{T_{\rm one\ way,\%}}{100}\right)\frac{\sum_b Q_bc_b}{\sum_b Q_b}.$$

Here $c_b$ is cost in bp per traded dollar and one-way turnover is defined so that buys plus sells / AUM is twice one-way turnover. This conversion avoids ambiguity about the two traded sides. After conversion, annual cost is an explicit input; changing bucket data or trade CSVs does not automatically recalibrate it. Include each modeled cost once. Tracking error remains fixed.

**6. Monte Carlo simulation**

Monte Carlo is the default calculation mode, with **2,000 samples** and **random seed 2026**. Both are editable sidebar parameters and are saved with the strategy. Samples mean independently resampled books, not individual trades. Deterministic mode remains an optional reference.

For an actual trade CSV with $N$ rows, sample $N$ complete $(q_i,V_i)$ pairs with replacement, uniformly by order. Preserve each sampled order's notional and order/ADV ratio, then normalize its notional weight. This preserves the observed relationship between size and liquidity within each pair.

For aggregate buckets, use $N=\operatorname{round}(\sum_b n_b)$ proxy orders per book and sample bucket membership with probabilities $P_b=n_b/\sum_j n_j$. A proxy order in bucket $b$ has notional $\bar q_b=Q_b/n_b$ and the editable representative ratio $x_b$. Thus a book's sampled bucket counts $m_{rb}$ generate notional weights:

$$ (m_{r1},\ldots,m_{rB})\sim\operatorname{Multinomial}(N;P_1,\ldots,P_B),\qquad w_{rb}=\frac{m_{rb}\bar q_b}{\sum_j m_{rj}\bar q_j}.$$

A bucket with positive count requires positive traded value, and conversely. Buckets with both zero are permitted. This aggregate bootstrap varies trade composition conditional on representative order sizes; it does not reconstruct the unknown within-bucket size/ADV distribution or draw fresh universe ADV values. Individual books need not exactly match observed bucket shares or total dollars. Annual cost and baseline gross alpha remain fixed scenario inputs.

For each book $r$, calculate $G_r(s)$, normalize $H_r(s)=G_r(s)/G_r(1)$ and apply the net-alpha and IR equations. Reuse the same sampled book at every AUM checkpoint. Default curves, diagnostics and scenario tables show simulation means. The mean multiplier is:

$$\bar H(s)=\frac{1}{M}\sum_{r=1}^{M}\frac{G_r(s)}{G_r(1)}.$$

Average these normalized book results; do not replace this with a ratio of mean captures. Each book has $H_r(1)=1$, so the baseline relative-capture and net-alpha bands collapse by construction. Absolute baseline capture can vary, but baseline-alpha uncertainty is not simulated.

Charts and CSV exports report pointwise 5th and 95th percentiles for relative capture, net alpha and net IR. These are **conditional trade-resampling ranges**, not full confidence intervals for future alpha or simultaneous curve bands. Forecast uncertainty, half-life/cost parameter uncertainty, within-bucket structure and liquidity-regime changes are excluded. More samples reduce Monte Carlo numerical error; they do not remove those uncertainties or mechanically tighten the underlying resampling distribution. IID order resampling also omits rebalance clustering; timestamped trades would be needed for a block bootstrap.

Capacity thresholds use the mean simulated curve from USD 500m, solved by bisection within the chart horizon. Current AUM remains the order-size and alpha calibration anchor. No probability of capacity breach is inferred from this mean crossing. Sensitivity comparisons use the same seed and book count for each alternative, with each book renormalized to that alternative's baseline. Seed, sample count, mode and percentile columns are included in the capacity export.

**7. Capacity and diagnostics**

Capacity is the first AUM **at or above USD 500m** where net IR reaches the selected minimum. Crossings use a numerical bisection through the selected chart horizon. If the USD 500m starting point is already below the threshold, the crossing lies at or below the calculation floor. A crossing below current AUM is permitted; current AUM is the calibration anchor, not the lower search bound. If no crossing occurs in range, the dashboard reports greater than the horizon. Scenarios at ×1, ×1.5, ×2, ×2.5 and ×3 remain available even if outside the plotted range.

Average execution time is notional-weighted. Multi-day notional is $\sum_i w_i\mathbf{1}[D_i>1]$; count-weighted multi-day share uses order counts. Retained alpha means net alpha divided by baseline gross alpha and is undefined when baseline gross alpha is zero.

**8. Sensitivity and independent backtest comparison**

Half-life and participation scenarios are recalculated and normalized to their own baseline. They describe alternative assumptions, not statistical confidence intervals. Bucket representative points and costs should also be stressed where data is uncertain.

The historical optimised-backtest comparison remains separate: $IR(A)=a-bA^\gamma$. Its observations determine the fitted parameters, and sidebar edits change only the active scenario. Its parameters do not enter the execution model. Its zero-IR and minimum-IR AUM values are solved analytically; both models search or report threshold crossings from the USD 500m calculation floor. Historical backtest observations below this floor remain available for fitting, but predictions and chart ranges start at the floor.

The model is a reduced-form alpha-capture proxy. It omits forecast uncertainty, market drift, adverse selection, changing liquidity, concurrent-order constraints, signal updates and changes in portfolio risk. Historical trading analysis is needed to estimate signal half-life and baseline annual costs.


**9. Model Calibration and the AUM grid**

All scenario curves, exports and capacity searches start at USD 500m. Scenario tables include that starting point alongside the current-AUM multiples. The current AUM still anchors observed order sizes and baseline gross alpha, so relative capture can exceed 100% below current AUM. Normalization and the baseline's collapsed resampling interval remain at current AUM, not automatically at USD 500m.

The Model Calibration tab contains three subtabs. **ADV bucket sampler** exposes one exact seeded bootstrap book, comparing its baseline count/notional shares with observed shares; it uses representative proxy orders for aggregate buckets or actual q/ADV pairs for trade data. The displayed bucket labels refer to baseline membership, not migration as AUM changes. The selected demo AUM defaults to current AUM, matching the supplied bucket observations.

**Alpha decay** fits three calibration triples and displays AUM → multi-day parent orders, multi-day parent orders → net IR, and the resulting AUM → net IR. Curvatures are inferred automatically; editing the triples changes their shape. In the combined empirical model, edits update the main curve and Summary immediately. The Apply button remains available in isolated comparison modes. Save through Inputs & strategy to persist the inputs.

**Transfer coefficient decay** fits three (TC, AUM, annual alpha) triples, displays both links and their composition, and transfers the chosen calibration to Capacity Lab. It is independent of the alpha-decay calibration. ADV sampler execution controls do not change either set of triples.

**10. Three-point alpha-decay calibration**

Inputs are ordered triples $(A_i,b_i,I_i)$: AUM in USD billions, count-weighted percentage of parent orders taking strictly more than one day (percentage points, not fractions), and net IR. Defaults are $(0.5,0,0.60)$, $(3,2,0.57)$, $(6,10,0.50)$. AUM uses USD 0.5bn increments. The first AUM and percentage are fixed at 0.5 and zero; subsequent AUM and percentages must strictly increase, percentages cannot exceed 100, and IR must strictly decrease.

$$k=\frac{\log(b_2/b_1)}{\log((A_2-A_0)/(A_1-A_0))},\qquad b(A)=b_1\left(\frac{A-A_0}{A_1-A_0}\right)^k.$$

$$\eta=\frac{\log((I_0-I_2)/(I_0-I_1))}{\log(b_2/b_1)},\qquad I(b)=I_0-(I_0-I_1)\left(\frac{b}{b_1}\right)^\eta.$$

Default curvatures are $k=2.041249$ and $\eta=0.748070$. Both links reproduce all three supplied points exactly. These are scenario assumptions, not estimates from historical orders. Multi-day trade percentage is a congestion proxy and does not distinguish two-day from ten-day execution.

The initial net IR includes fixed other effects. Only its alpha-decay change is modelled. Tracking error is held fixed and net alpha (percent per year) equals $I(b(A))$ times tracking error (percent). Baseline gross alpha, execution half-life, participation, annual costs and cost elasticity do not enter this mode. No additional cost subtraction or TC/decay multiplier is applied. The separate backtest comparison is retained.

The calibrated interval is USD 0.5bn through the last supplied AUM (default USD 6bn). Beyond it, charts and exports explicitly label extrapolation. The model stops at $A_{100}=A_0+(A_1-A_0)(100/b_1)^{1/k}$; it does not cap percentages and continue deteriorating IR after 100%. Chart horizons and scenario tables respect this domain. Capacity uses the analytic inverse of the composed curve, bounded by the active horizon; it follows the calibrated central curve even in Monte Carlo mode.

Monte Carlo is available by default, with the shared sample-count and seed controls. At each AUM, $K\sim\mathrm{Binomial}(N,b(A)/100)$, where $N$ is the observed parent-order count (actual CSV rows, or rounded aggregate count). Each draw is mapped through $I(100K/N)$. Pointwise 5th–95th percentiles are exported for net IR and net alpha. The central curve remains the exact calibration, not the mean of this nonlinear transformation. This is a synthetic independent-order congestion-count model, distinct from the execution model's ADV-book bootstrap. It excludes calibration uncertainty and order dependence; it is not a simultaneous curve confidence band. At the zero-congestion anchor, the range collapses. More simulation draws improve numerical precision, not assumed model certainty.

Model selection and all triples are saved with the strategy. Strategies without a model selection default to the combined empirical model. Explicit saved model choices remain available.

**11. Three-point transfer-coefficient calibration**

Input order is $(T_i,A_i,a_i)$: absolute TC in percent, AUM in USD billions, annual net alpha in percent. Other effects remain fixed; costs and the separate alpha-decay model are not applied again. Defaults are $(60,0.5,1.0)$, $(40,3,0.6)$ and $(25,6,0.3)$. AUM starts at USD 0.5bn and increases in 0.5bn increments. TC decreases strictly within 0–100%, and alpha decreases strictly.

$$k_T=\frac{\log((T_0-T_2)/(T_0-T_1))}{\log((A_2-A_0)/(A_1-A_0))},\quad T(A)=T_0-(T_0-T_1)\left(\frac{A-A_0}{A_1-A_0}\right)^{k_T}.$$

$$\eta_T=\frac{\log((a_0-a_2)/(a_0-a_1))}{\log((T_0-T_2)/(T_0-T_1))},\quad a(T)=a_0-(a_0-a_1)\left(\frac{T_0-T}{T_0-T_1}\right)^{\eta_T}.$$

Both links fit the supplied triples exactly. The defaults imply a nonlinear AUM-to-TC link, but $\eta_T=1$: the TC-to-alpha link is linear, $a(T)=0.02T-0.20$, using percentage-point units. This fixed offset is implied by the estimated net-alpha points; the curve is not a pure proportional FLAM gross-alpha relationship through zero. No IC or independent breadth estimate is inferred from these inputs. Other triples may produce a nonlinear TC-to-alpha link.

Net IR is annual net alpha divided by fixed tracking error, with both return quantities expressed in percent. Beyond the final AUM (default USD 6bn), projections are labelled extrapolation. Predictions stop at zero TC:

$$A_{T=0}=A_0+(A_1-A_0)\left(\frac{T_0}{T_0-T_1}\right)^{1/k_T}.$$

Capacity crossings use the analytical inverse of the central curve, bounded by the chart horizon. This model is deterministic: no probability distribution or estimation uncertainty for TC is identified by three estimated triples, so no Monte Carlo band is invented. Execution and alpha-decay models retain their existing simulation options. The chosen model and all TC triples are saved with the strategy and included in exports.

**12. Dashboard organisation and methodology download**

Summary remains first, followed by Empirical IR curve, Backtest IR curve, Model Calibration, Inputs & strategy, and Methodology. Inputs & strategy combines the editable parent-order inputs and the strategy-saving form. The Methodology tab contains only a download of this methodology as a PDF. The LaTeX source remains editable separately.

**13. Impact-cost estimation in ADV bucket sampler**

The sampler restores the legacy impact curve $c(x)=a+b x^\gamma$, where $x$ is total parent-order/ADV as a fraction and $c$ is positive basis points per traded dollar. Estimated bucket costs are the fitting target and are stored as positive cost magnitudes. The fit uses the active baseline representative ratios and costs, with equal weight for each bucket, nonnegative $a,b$ and $0.05\leq\gamma\leq3$. It minimizes squared cost residuals. With the default estimated data, it recovers approximately $a=0$, $b=28.0279$, $\gamma=0.385843$.

The observed aggregate cost weights each bucket by its actual traded value, not its trade count or rounded share. Default estimated impact is approximately 8.6932 bp per traded dollar. Fit weights and aggregation weights serve different purposes. The preview follows changes in current AUM until the user selects a custom scenario. Scenario preview values scale order sizes without re-anchoring the input buckets; the empirical net-IR anchor remains USD 0.5bn. The fit updates automatically when baseline bucket inputs change. There are no per-bucket sliders, manual impact-parameter overrides or execution hyperparameters in the sampler. Its controls are selected AUM, Monte Carlo sample count, random seed and one-way annual turnover. Book selection and detailed diagnostics are available in an expandable inspection section; fitted parameters and CSV exports are in a separate details section.

For a sampled book, evaluate the active curve at each scaled order ratio $x_i(A)=x_i(A_0)A/A_0$. Its weighted impact is $\bar c_r(A)=\sum_i w_{ri}c(x_i(A))$; total sampled-order impact dollars equal $\sum_i q_{ri}(A)c(x_i(A))/10{,}000$. Annual portfolio drag in bp is $2\tau\bar c_r(A)$, where $\tau$ is one-way annual turnover as a fraction. The default 13.9% implies a factor of 0.278. This annualization is distinct from directly pricing the displayed sampled orders; it does not assume their summed notional equals a full year's turnover.

The AUM chart reuses the same seeded bootstrap books as the sampler. It shows mean annual impact drag and pointwise 5th–95th percentile order-composition ranges. Impact parameters, ADV and turnover are held fixed. The bands do not measure fitting uncertainty. Forecasts outside the observed representative order/ADV range are extrapolations. No migration, impact cap or dependence on daily participation is introduced by this cost curve.

The impact fit, sampled-order cost table and cost curve are independently exportable. They drive the impact pillar of the combined empirical model. Legacy execution costs and isolated alpha/TC comparisons remain separate.

The sampler also shows a grouped vertical bar chart of trade frequencies across current AUM, twice current AUM and three times current AUM. It reuses one exact seeded sampled book and scales each baseline order/ADV ratio by 1, 2 and 3, then reclassifies the orders. Each stage preserves total parent-order count. Buckets include their lower boundary and exclude their upper boundary; an explicit overflow category covers orders at or above the final upper boundary. These scenarios use the Capacity Lab current AUM independently of Sampler AUM or the impact chart horizon. Representative ratios determine moves in aggregate bucket mode; complete ratios are retained in actual-trade mode. ADV buckets are on the x-axis and percentage frequency is on the y-axis. Frequencies are count-weighted, and the distributions are available as a CSV export.

**14. Combined three-pillar empirical IR curve**

The user-selected combination multiplies retention factors. Let $I_\alpha(A)$ be the alpha-decay calibration, $I_0=I_\alpha(0.5)$ its initial net IR, $a_{TC}(A)$ the TC calibration's annual alpha, and $a_{TC,0}=a_{TC}(0.5)$. Define:

$$H_\alpha(A)=I_\alpha(A)/I_0,\qquad H_{TC}(A)=a_{TC}(A)/a_{TC,0}.$$

$$C(A)=2\tau\,\bar c(A),\qquad IR_{\mathrm{emp}}(A)=I_0H_\alpha(A)H_{TC}(A)-\frac{C(A)-C(0.5)}{100\sigma_{TE}}.$$

$C$ is annual portfolio impact drag in bp, $\tau$ is one-way annual turnover as a fraction, and $\sigma_{TE}$ is tracking error in percentage points. Net alpha in percent is $IR_{\mathrm{emp}}(A)\sigma_{TE}$. The initial net IR already includes baseline costs; only the incremental cost above USD 0.5bn is deducted. The TC alpha curve supplies a relative retention factor, not a second absolute alpha anchor. Legacy gross alpha, half-life, cost elasticity and explicit annual-cost controls do not enter this combined calculation.

Defaults yield IR before incremental impact costs of $0.57\times0.60=0.342$ at USD 3bn and $0.50\times0.30=0.150$ at USD 6bn. The USD 0.5bn anchor is exactly 0.60. Current AUM anchors the observed parent-order sizes used to price impact, while the net-IR anchor stays at USD 0.5bn.

Model Calibration edits immediately update Empirical IR curve and Summary. The sampler sample count, seed and turnover also drive the combined model. Strategy saving persists the active triples, input observations and simulation settings. Exports include pillar retentions, incremental costs, fitted impact parameters, model identity and percentiles. Summary retains the separate historical-backtest comparison and adds an exact decomposition:

$$IR_{\mathrm{emp}}=I_0-\underbrace{(I_0-I_\alpha)}_{\text{alpha loss}}-\underbrace{I_\alpha(1-H_{TC})}_{\text{TC loss}}-\underbrace{\frac{C(A)-C(0.5)}{100\sigma_{TE}}}_{\text{impact loss}}.$$

The domain begins at USD 0.5bn and ends at the first zero of either retained-alpha factor, or an earlier isolated model domain limit. Retention factors remain nonnegative; the combined net IR can become negative through incremental impact costs. Projections beyond either final calibration AUM are labelled extrapolation. Capacity crossings use bisection on the central combined curve within this domain and the chart horizon.

In Monte Carlo mode, the same seeded order book prices $C_r(A)$ and its own $C_r(0.5)$, so each draw subtracts its own baseline cost. Independent binomial congestion counts condition on the fitted multi-day share; their IR conversion is floored at zero retention. TC retention and fitted parameters stay fixed. Pointwise 5th–95th percentiles combine these two conditional sources of uncertainty. The central curve evaluates the calibrated multi-day share and mean bootstrap impact cost, rather than averaging the nonlinear final simulations. At USD 0.5bn every range collapses to the anchor. The bands exclude parameter uncertainty and dependence between congestion counts and impact composition; they are not simultaneous curve confidence bands. Deterministic mode uses observed order weights and disables the combined bands, while sampler book inspection remains stochastic.

**15. Display precision and optional intervals**

The empirical dashboard defaults to Deterministic mode: the calibrated central curve is shown without confidence intervals, using observed order weights. Select Monte Carlo in Capacity Lab to add the conditional 5th–95th percentile intervals described above. Simulation count and seed are set in ADV bucket sampler. The selected mode is saved with the strategy; explicitly saved Monte Carlo settings are preserved when reloaded. Sampler book inspection remains stochastic in either mode.

All displayed numeric tables use at most two decimal places; integer count columns may omit decimals. Order/ADV ratios and notional weights are displayed as percentages to preserve readability for small fractions. Editable bucket ratio columns also use percent units and are converted back to fractions internally. Calculations, stored strategy values and CSV exports retain full precision.
