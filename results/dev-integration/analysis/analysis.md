> EXPLORATORY ANALYSIS - underpowered design (D-024). Effects are reported with 95% cluster-bootstrap CIs and family-level permutation p-values as descriptive statistics only; no claim of statistical significance is made.

Records: 5; code commits: e4ba76665446c075a83cfd413acd19f489fe0ba2

| Arm | Runs | Failed | Correct | Top-3 | Grounded | Evidence prec. | Evidence cov. | Unsupported claims | Median wall s | Median prompt tok | Median output tok | Median CPU s | Peak RSS MB | Median B used | Median repeats |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A2 | 1 | 0 | 100.0% | 100.0% | 100.0% | 100.0% | 66.7% | 0.0% | 443 | 11185 | 285 | 1202 | 9301 | 944 | 10.00 |
| A3 | 1 | 0 | 100.0% | 100.0% | 100.0% | 100.0% | 66.7% | 0.0% | 650 | 15905 | 335 | 1754 | 8979 | 1034 | 13.00 |
| E1 | 1 | 0 | 100.0% | 100.0% | 100.0% | 100.0% | 66.7% | 0.0% | 0.19 | 0.00 | 0.00 | – | – | 213 | 1.00 |
| E1f | 1 | 0 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 0.17 | 0.00 | 0.00 | – | – | 55.00 | 0.00 |
| E2b | 1 | 0 | 100.0% | 100.0% | 100.0% | 85.7% | 66.7% | 0.0% | 468 | 1948 | 419 | 1307 | 8263 | 1584 | 1.00 |
| E3 | 1 | 0 | 100.0% | 100.0% | 100.0% | 100.0% | 66.7% | 0.0% | 650 | 15905 | 335 | 1754 | 8979 | 1034 | 13.00 |

| Comparison (A − B) | Cases | Means | Effect | 95% CI | Perm. p | McNemar (A only/B only) |
|---|---|---|---|---|---|---|
| PRIMARY correct: E3 − E2b | 1 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 | 0/0, p=1.000 |
| secondary correct:E3-E1 | 1 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | 0/0, p=1.000 |
| secondary correct:E2b-E1 | 1 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | 0/0, p=1.000 |
| secondary correct:E3-A2 | 1 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | 0/0, p=1.000 |
| secondary correct:E3-A3 | 1 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | 0/0, p=1.000 |
| secondary unsupported_claim_rate:E3-E2b | 1 (1 fam.) | 0.00 vs 0.00 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | – |
| secondary unsupported_claim_rate:A3-E3 | 1 (1 fam.) | 0.00 vs 0.00 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | – |
| secondary grounded:E3-E2b | 1 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | – |
| secondary evidence_coverage:E3-E2b | 1 (1 fam.) | 0.67 vs 0.67 | +0.000 | [+0.000, +0.000] | 1.000 (Holm 1.000) | – |

| Stratum (E3 − E2b, correct) | Cases | Means | Effect | 95% CI | Perm. p | McNemar |
|---|---|---|---|---|---|---|
| distractor | 1 (1 fam.) | 1.00 vs 1.00 | +0.000 | [+0.000, +0.000] | 1.000 | 0/0, p=1.000 |
