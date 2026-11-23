> EXPLORATORY ANALYSIS - underpowered design (D-024). Effects are reported with 95% cluster-bootstrap CIs and family-level permutation p-values as descriptive statistics only; no claim of statistical significance is made.

Records: 90; code commits: b21644cccef0d6004693068bd1fbcd19801cd11e

| Arm | Runs | Failed | Correct | Top-3 | Grounded | Evidence prec. | Evidence cov. | Unsupported claims | Median wall s | Median prompt tok | Median output tok | Median CPU s | Peak RSS MB | Median B used | Median repeats |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A2 | 18 | 0 | 88.9% | 88.9% | 93.3% | 100.0% | 55.6% | 0.0% | 376 | 10412 | 298 | 1055 | 15308 | 994 | 10.00 |
| A3 | 18 | 0 | 88.9% | 88.9% | 93.3% | 100.0% | 56.7% | 2.8% | 682 | 17897 | 366 | 1911 | 15360 | 1072 | 11.50 |
| E1 | 18 | 0 | 100.0% | 100.0% | 100.0% | 84.3% | 63.3% | 0.0% | 0.17 | 0.00 | 0.00 | – | – | 234 | 1.00 |
| E1f | 18 | 0 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 0.17 | 0.00 | 0.00 | – | – | 55.00 | 0.00 |
| E2b | 18 | 0 | 83.3% | 83.3% | 93.3% | 91.6% | 68.9% | 0.9% | 494 | 1948 | 424 | 1402 | 15351 | 1580 | 1.00 |
| E3 | 18 | 0 | 88.9% | 88.9% | 93.3% | 100.0% | 54.4% | 2.8% | 682 | 17897 | 366 | 1911 | 15360 | 1072 | 11.50 |

| Comparison (A − B) | Cases | Means | Effect | 95% CI | Perm. p | McNemar (A only/B only) |
|---|---|---|---|---|---|---|
| PRIMARY correct: E3 − E2b | 18 (6 fam.) | 0.89 vs 0.83 | +0.056 | [-0.167, +0.333] | 1.000 | 2/1, p=1.000 |
| secondary correct:E3-E1 | 18 (6 fam.) | 0.89 vs 1.00 | -0.111 | [-0.333, +0.000] | 0.500 (Holm 1.000) | 0/2, p=0.500 |
| secondary correct:E2b-E1 | 18 (6 fam.) | 0.83 vs 1.00 | -0.167 | [-0.444, +0.000] | 0.500 (Holm 1.000) | 0/3, p=0.250 |
| secondary correct:E3-A2 | 18 (6 fam.) | 0.89 vs 0.89 | +0.000 | [-0.222, +0.222] | 1.000 (Holm 1.000) | 1/1, p=1.000 |
| secondary correct:E3-A3 | 18 (6 fam.) | 0.89 vs 0.89 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | 0/0, p=1.000 |
| secondary unsupported_claim_rate:E3-E2b | 18 (6 fam.) | 0.03 vs 0.01 | +0.019 | [-0.028, +0.102] | 1.000 (Holm 1.000) | – |
| secondary unsupported_claim_rate:A3-E3 | 18 (6 fam.) | 0.03 vs 0.03 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | – |
| secondary grounded:E3-E2b | 15 (5 fam.) | 0.93 vs 0.93 | +0.000 | [-0.267, +0.267] | 1.000 (Holm 1.000) | – |
| secondary evidence_coverage:E3-E2b | 15 (5 fam.) | 0.54 vs 0.69 | -0.144 | [-0.422, +0.133] | 0.438 (Holm 1.000) | – |

| Stratum (E3 − E2b, correct) | Cases | Means | Effect | 95% CI | Perm. p | McNemar |
|---|---|---|---|---|---|---|
| concurrent | 3 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 | 0/0, p=1.000 |
| distractor | 3 (1 fam.) | 1.00 vs 0.67 | +0.333 | [+0.000, +1.000] | 1.000 | 1/0, p=1.000 |
| easy | 3 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 | 0/0, p=1.000 |
| insufficient | 3 (1 fam.) | 0.67 vs 0.33 | +0.333 | [+0.000, +1.000] | 1.000 | 1/0, p=1.000 |
| multi_hop | 3 (1 fam.) | 0.67 vs 1.00 | -0.333 | [-1.000, +0.000] | 1.000 | 0/1, p=1.000 |
| over_budget | 3 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 | 0/0, p=1.000 |
