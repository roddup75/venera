# Capacity Lab: objectives, approaches and calibration

## 1. Objective of the exercise

Estimate how net performance changes as assets under management (AUM) grow, and identify the AUM at which net information ratio (IR) reaches a chosen minimum. This supports capacity planning by making assumptions explicit; capacity is not treated as a fixed property of the strategy.

The dashboard reports net IR, annual net alpha, and minimum-IR and zero-IR AUM thresholds. IR is net alpha divided by tracking error. Use consistent return horizons and risk conventions when comparing results.

**Two AUM references have different jobs.** Current AUM anchors the supplied trading observations. USD 0.5bn starts the calibrated net-IR curve. The sampler preview defaults to current AUM; the empirical curve starts at USD 0.5bn.

## 2. Two complementary approaches

### 2.1 Empirical approach

The **Empirical IR curve** combines observed trading and liquidity inputs with three calibrated pillars: impact costs, alpha decay and transfer-coefficient (TC) decay. It asks what happens if orders grow and the chosen execution and implementation assumptions hold.

Trading observations inform impact costs. Alpha-decay and TC points are user estimates, not parameters automatically inferred from trade history. Model Calibration makes them visible and editable.

### 2.2 Backtest approach

The **Backtest IR curve** fits a decreasing power curve to AUM–IR observations from optimised historical backtests. Use comparable periods, risk conventions and cost definitions. The sidebar permits adjustments to the fitted curve. Replace illustrative dashboard observations before interpreting the comparison as historical evidence.

**Read the approaches together.** Summary compares current IR and capacity thresholds. Differences indicate assumptions worth reviewing. The curves remain separate: they are not averaged, and the backtest fit does not calibrate the empirical pillars.

## 3. Empirical approach: inputs, pillars and calibration

### 3.1 Inputs

Confirm that the observations in **Inputs & strategy** correspond to current AUM.

| Input | Purpose and units |
|---|---|
| Current AUM | Size at which observed orders apply; USD billions |
| ADV buckets | Parent-order size divided by average daily traded value, grouped by liquidity |
| Order counts and value | Counts determine sampling probabilities; traded value determines portfolio cost weights |
| Estimated bucket impact | Positive basis points per traded dollar |
| One-way annual turnover | Buys plus sells / AUM is twice this turnover fraction |
| Tracking error | Fixed annual active-return risk, entered in percent |
| Calibration triples | Three points each for alpha decay and TC |
| Minimum net IR | Threshold used to indicate capacity |

Alternatively, upload actual parent orders with positive `q` and `adv` in the same currency. The CSV supplies order sizes and liquidity; estimated bucket costs still calibrate the impact curve.

### 3.2 Three model pillars

#### Impact costs: larger orders are more expensive to trade

The ADV bucket sampler automatically fits a nonnegative power cost curve to estimated bucket impacts. Each bucket has equal fitting weight; aggregate portfolio costs use traded-notional weights. There are no per-bucket sliders or manual impact-fit controls.

Orders scale with AUM while ADV stays fixed. Current-AUM preview reproduces the input order-size scale; other preview values are scenarios. The frequency chart compares the same book at current AUM, ×2 and ×3, including an overflow bucket.

Outputs include impact per traded dollar, sampled-order cost in USD and annual portfolio drag. Annual drag in bp equals weighted impact multiplied by twice one-way turnover. For 13.90% turnover, the multiplier is 0.278. Annualisation is separate from pricing the displayed orders directly.

#### Alpha decay: execution congestion reduces performance

Provide three **(AUM, % trades taking more than one day, net IR)** points. Two linked power curves connect AUM to multi-day percentage, then multi-day percentage to IR. Curvatures fit automatically.

| AUM (USD bn) | Trades >1 day | Net IR |
|---:|---:|---:|
| 0.50 | 0.00% | 0.60 |
| 3.00 | 2.00% | 0.57 |
| 6.00 | 10.00% | 0.50 |

These defaults isolate alpha decay with other effects fixed. Multi-day percentage counts orders equally regardless of notional or forecast strength. It does not distinguish two-day from ten-day orders.

#### Transfer coefficient: implementation efficiency declines

Provide three **(TC, AUM, annual alpha)** points. Two linked power curves connect AUM to TC, then TC to annual alpha. Here alpha means annual net alpha with other effects fixed.

| TC | AUM (USD bn) | Annual alpha |
|---:|---:|---:|
| 60.00% | 0.50 | 1.00% |
| 40.00% | 3.00 | 0.60% |
| 25.00% | 6.00 | 0.30% |

Divide calibrated alpha by its initial value to obtain **TC-alpha retention**: 100.00%, 60.00% and 30.00% at the default points. This is not the raw TC ratio. The defaults imply nonlinear AUM-to-TC decay and a linear TC-to-alpha link; other triples can change curvature. Initial 1.00% is a normalising reference, not a second absolute alpha anchor.

### 3.3 Calibration workflow

1. Confirm current AUM, trading observations, estimated impacts, tracking error and turnover.
2. Inspect the automatic impact fit and trading-book distribution in Model Calibration. Adjust AUM, sample count, seed or turnover as needed.
3. Edit alpha-decay triples and inspect both links. AUM uses USD 0.5bn increments; multi-day percentages increase and IR decreases.
4. Edit TC triples: AUM increases; TC and annual alpha decrease. Review retention.
5. Review Empirical IR curve and Summary, which update immediately in the combined model. Save through Inputs & strategy.

### 3.4 How the pillars combine

Start with alpha-decay IR, multiply by TC-alpha retention, and deduct **only the increase in impact costs above USD 0.5bn**, expressed in IR units:

$$IR(A)=I_\alpha(A)H_{TC}(A)-\Delta C_{IR}(A).$$

The initial net-IR point already includes baseline costs, so baseline cost is not deducted again. Defaults give IR before incremental costs of 0.57 × 0.60 = 0.342 at USD 3bn and 0.50 × 0.30 = 0.150 at USD 6bn. Net IR at USD 0.5bn remains 0.60. Annual net alpha in percent equals net IR times tracking error in percent.

### 3.5 Reading the results

Empirical IR curve shows net IR and net alpha. Summary compares empirical and backtest capacity and decomposes the empirical decline into alpha-decay, TC and incremental-impact contributions.

Capacity is the first AUM from USD 0.5bn where the central curve reaches the chosen threshold. A threshold not reached within range does not imply unlimited capacity. Predictions beyond calibration points are labelled extrapolation. The combined domain stops at the first zero retained-alpha factor or an earlier pillar-domain limit.

**Deterministic** is the default: a central curve without intervals. **Monte Carlo** adds conditional 5th–95th percentile ranges. Tables display at most two decimals; calculations, stored values and CSV exports retain full precision.

## Appendix. Simulation assumptions and calculation notes

### What Monte Carlo samples

A sample is an alternative trading book and congestion outcome, not an individual trade-alpha forecast. Initial settings are 2,000 samples and seed 2026; the observed order count determines book size.

- **Bucket data: multinomial counts.** Probabilities are observed count shares. Each proxy order uses a bucket representative order/ADV and average notional. There is no continuous within-bucket draw.
- **Actual trades: empirical bootstrap.** Observed complete order-notional/ADV pairs are sampled uniformly with replacement. Equal selection probability does not establish equal alpha contribution.
- **Congestion: binomial counts.** Independently of cost-book sampling, multi-day counts use observed book size and the calibrated multi-day probability. The sampled percentage maps into IR, with simulated alpha retention floored at zero.

The same cost book is reused across AUM and compared with its own USD 0.5bn baseline. TC and parameters stay fixed. More samples improve numerical stability without increasing orders per book or resolving assumption uncertainty. The seed makes draws reproducible.

### Interpretation and limitations

Orders are exchangeable for alpha-decay purposes: no trade-specific alpha forecasts or delay sensitivities are modelled. This is a count-based approximation, not an allocation of equal alpha dollars to every trade. Costs remain notional-weighted.

Congestion draws and cost composition are independent, although difficult trades may carry more or less alpha in reality. Ranges exclude this dependence, parameter uncertainty, clustered orders and changing liquidity. They are conditional pointwise ranges, not simultaneous bands or performance guarantees. The centre uses calibrated congestion and mean bootstrap impact, not the nonlinear simulation mean. Ranges collapse at USD 0.5bn.

The Fundamental Law of Active Management motivates separating skill, independent breadth and implementation efficiency. The dashboard does not estimate skill or breadth, and its TC scenario is not an estimated forecast-to-position correlation.

### Units and fitted relationships

AUM uses USD billions; order/ADV is a fraction internally and a percentage in the interface. Alpha and tracking error use percentage points. For annual portfolio cost $C(A)$ in bp and tracking error $TE$ in percent:

$$\Delta C_{IR}(A)=\frac{C(A)-C(0.5)}{100TE}.$$
