# ML experiments

Experiments E0–E4 are logged below. **All of them use synthetic data.** This file records each
experiment as it is actually executed: the data, the split, the baseline,
the results (including failures), and the decision taken.

## Rules for every experiment

1. State the problem and the decision the model would change.
2. Fix the dataset version and the random seed; record both here.
3. Use chronological splits for anything time-based. Fit no preprocessing
   (TF-IDF vocabularies, scalers) on validation or test data.
4. Always compare against a simple baseline.
5. Report the metric values from the actual run, with the command used.
   Never estimate or round up.
6. Synthetic results show that the code works, not that the model works on
   real behaviour. Label them as synthetic.

## Planned experiments

| # | Problem | Baseline(s) | Candidates | Metrics | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Transaction categorisation | Keyword rules (`default_rules.toml`), majority class | TF-IDF + Logistic Regression, Random Forest, XGBoost | Per-class precision/recall/F1, macro-F1, confusion matrix, coverage at a confidence threshold | **E1 done (synthetic).** Re-run on real corrections (`category_basis = user`) when they exist |
| 2 | Spending / cash-flow forecasting | Historical mean, last period, moving average | Exponential smoothing, SARIMA, Linear Regression, Random Forest, XGBoost | MAE, RMSE, MAPE per horizon; interval coverage | **E2 done (synthetic)**: no model beat the baselines. Next: research Models B–D |
| 3 | Anomaly detection | z-score / IQR per category, personal median | Isolation Forest, LOF | Precision/recall on injected anomalies; false-positive rate per month | **E3 done (synthetic)**: personal z-scores won |
| 4 | Missing-data impact | Complete data | Data with records removed under MCAR / MAR / MNAR mechanisms | Change in forecast MAE/RMSE by missingness level | Not started |
| 5 | Duplicate-pair scoring | Hand-weighted matcher (E0 below) | Logistic regression on the same features, trained on user review decisions | Precision/recall at the review threshold; review items per true duplicate | Not started. Needs real review decisions |
| 6 | Spending clustering | — | K-Means, hierarchical | ARI against known types; silhouette | **E4 done (synthetic research check)**: no app feature |

## Leakage risks to guard against

- Duplicate or near-duplicate descriptions in both train and test sets:
  split by merchant or by time, not by random row.
- Rules that were written after looking at the test set.
- Forecast features computed with centred windows or full-period
  statistics.

## Log

### E0: Heuristic duplicate-candidate matcher (not ML), 2026-10-14

**Question.** Does `domain/matching.py` (gates + hand-weighted score,
threshold 60) propose every payment that appears in both a payment-app
export and the bank statement, without proposing unrelated payments?

**Data.** Synthetic only. For each seed, the three statement files plus
`sample_payapp_2026_q1.csv`. About half of the bank's grocery, restaurant,
cafe, cab and metro payments are mirrored in the app export with the app's
merchant naming and the same date or one day earlier. The export also
contains three app-only payments and two failed ones. One app-only payment
is a deliberate decoy: ₹999.00 on the same day as the bank's ₹999.00
broadband bill, different merchant. Identical repeated bank entries (the two
₹120 chai purchases on 7 Feb) were not mirrored.

**Command.** The evaluation script that produced this table was a one-off;
the same checks run as `tests/domain/test_matching.py::test_synthetic_cross_source_matching`.

| Seed | True pairs | Proposed | True proposed | Other proposed | Recall | Precision | Lowest true score | Highest non-identical other score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026 | 13 | 14 | 13 | 1 | 1.00 | 0.929 | 87 | 54 |
| 1 | 11 | 12 | 11 | 1 | 1.00 | 0.917 | 87 | 54 |
| 7 | 16 | 17 | 16 | 1 | 1.00 | 0.941 | 87 | 54 |
| 99 | 11 | 12 | 11 | 1 | 1.00 | 0.917 | 87 | 54 |
| 12345 | 15 | 16 | 15 | 1 | 1.00 | 0.938 | 87 | 54 |

The "other" proposal in every seed is the identical chai pair: two real
payments that no algorithm can tell apart, so asking the user is correct.
The decoy scored 54, below the threshold. Failed app payments were never
proposed.

**Interpretation.** The code does what it was designed to do. This is weak
evidence about real-world performance: the data was generated with the
matcher's assumptions in mind (exact amounts, app names contained in bank
descriptions, at most one day of lag), so the wide gap between 87 and 54 is
expected. Real exports will have fees, partial refunds, merchant names that
share no words, and longer settlement delays.

**Decision.** Keep threshold 60 and human review for everything. Collect
review decisions as labels; revisit the weights (experiment 5) once there
are real decisions to learn from.

### E1: Transaction categorisation, 2026-11-12

**Question.** Do TF-IDF text models categorise transaction descriptions
better than keyword rules, especially for merchants never seen before?

**Data.** Synthetic labelled corpus (`ml/corpus.py`), 3 seeds × ~5,600
descriptions, 400 invented merchants each across 10 categories. Names are a
bland word plus, usually, a category descriptor ("Kitchen", "Medicos");
15% have no descriptor; some descriptors are shared between categories
("Mart"). Rendered through UPI, POS, NEFT/ACH and payment-app templates with
truncation and typos.

**Protocol.** Pre-registered settings (word 1–2-grams + character 3–5-grams
TF-IDF; Logistic Regression C = 5; Random Forest 300 trees; XGBoost 200 trees,
depth 6; confidence threshold 0.6). Two evaluations: *unseen merchants*
(stratified group 5-fold by merchant, 3 seeds; the decision metric) and
*seen merchants* (stratified 5-fold, 1 seed; optimistic). Text features are
fitted inside each training fold. Baselines: majority class; the app's
current keyword rules; and "vocabulary rules" built from the generator's own
descriptor lists, a reference that knows the answer words and is not a fair
competitor.

**Command.** `moneyos ml categorization` (report and confusion matrix in
`data/experiments/categorization/`).

Unseen merchants (mean ± SD over 15 folds):

| Model | Macro-F1 | Accuracy | Coverage at ≥ 0.6 | Accuracy when shown | Fit (s) |
| --- | --- | --- | --- | --- | --- |
| majority class | 0.023 ± 0.001 | 0.131 ± 0.008 | 100% | 0.131 | 0.0 |
| app's current rules | 0.138 ± 0.046 | 0.087 ± 0.035 | 10.3% | 0.841 | 0.0 |
| vocabulary rules (reference) | 0.828 ± 0.035 | 0.737 ± 0.036 | 74.8% | 0.985 | 0.0 |
| TF-IDF + Logistic Regression (**selected**) | 0.730 ± 0.042 | 0.739 ± 0.038 | 74.3% | 0.871 | 1.6 |
| TF-IDF + Random Forest | 0.743 ± 0.044 | 0.750 ± 0.041 | 75.1% | 0.882 | 3.9 |
| TF-IDF + XGBoost | 0.730 ± 0.044 | 0.739 ± 0.040 | 80.5% | 0.867 | 45.9 |

Seen merchants (mean ± SD over 5 folds): Logistic Regression 0.954 ± 0.005,
Random Forest 0.951 ± 0.004, XGBoost 0.945 ± 0.005, vocabulary rules
0.857 ± 0.011, current rules 0.133 ± 0.015.

**Interpretation.**
- On *new* merchants the text models do not beat a keyword list that
  contains the right words (0.73–0.74 vs 0.83 macro-F1; when the list
  matches it is right 98.5% of the time vs about 87% for the models). Part
  of that is built in (the generator uses exactly those words), but the
  lesson holds: a good vocabulary is hard to beat on unseen merchants.
- On *seen* merchants the models reach 0.95 and clearly beat the
  vocabulary rules (0.86): they learn individual merchants, including those
  whose names say nothing about their category. That is where a model adds
  value in MoneyOS: learning the user's recurring merchants from their
  corrections.
- Against the app's current rules (written for different sample data) every
  model wins easily; that gap mostly measures how narrow those rules are.
- The three models are within one standard deviation of each other; XGBoost
  costs ~30× the training time for no gain.
- Main confusion: Groceries → Shopping (12%), from the shared "Mart".

**Decision.** By the pre-registered rule (Random Forest best by 0.013, Logistic
Regression within one SD, so the simpler model), **TF-IDF + Logistic
Regression** is saved as `categorizer-20261112-243dbab6` (trained on all three
synthetic corpora) and serves *suggestions* only for transactions the rules
left uncategorised; bulk apply needs ≥ 0.9 confidence by default and records
basis `model`. Follow-ups: (1) broaden the keyword rules, which this
experiment shows are worth more than expected; (2) evaluate the
rules-then-model combination directly; (3) retrain with real corrections
(`category_basis = user`) once they exist, re-running this protocol.

### E2: Spending forecasting, transactions only, 2026-11-12

**Question.** Do exponential smoothing, SARIMA, or feature-based Linear
Regression / Random Forest / XGBoost forecast total spending over the next 7
or 30 days better than simple baselines (historical mean, last period,
90-day moving average, same window last month)?

**Data.** Synthetic: 20 simulated people × 730 days (`ml/spending_sim.py`):
scheduled commitments (rent, a varying utility bill, subscriptions),
everyday purchases shaped by weekday, payday, festive months and a slow
trend, and rare unpredictable one-off purchases.

**Protocol.** Origins every 7 days. Chronological sets with purging (train
targets end before day 450; calibration origins from day 450 with targets
ending before day 570; test origins from day 570). Forecasts use data up to
their origin only. SARIMA parameters estimated on the training period and
rolled forward; exponential smoothing refitted at each origin; feature
models trained once per horizon on training origins, pooled across people,
with spending features relative to each person's 90-day level. The method
is chosen on calibration MAE and reported on test. 80% intervals: forecast
plus the 10th/90th percentiles of that method's calibration errors.

**Command.** `moneyos ml forecasting`.

Next 7 days (test):

| Method | MAE | RMSE | MAPE | MAE vs best baseline | 80% interval coverage |
| --- | --- | --- | --- | --- | --- |
| same window last month (best baseline) | 5,837 | 9,494 | 52.3% | — | 75% |
| Random Forest (**chosen on calibration**) | 5,953 | 8,702 | 58.5% | +2.0% | 73% |
| XGBoost | 6,087 | 8,692 | 58.9% | +4.3% | 73% |
| Linear Regression | 6,545 | 9,416 | 56.3% | +12.1% | 76% |
| SARIMA | 7,003 | 9,936 | 58.0% | +20.0% | 85% |
| historical mean | 7,207 | 9,985 | 61.8% | +23.5% | 82% |
| exponential smoothing | 7,356 | 10,040 | 65.0% | +26.0% | 82% |

Next 30 days (test):

| Method | MAE | RMSE | MAPE | MAE vs best baseline | 80% interval coverage |
| --- | --- | --- | --- | --- | --- |
| Linear Regression | 10,481 | 14,254 | 16.5% | −0.8% | 68% |
| historical mean (best baseline) | 10,562 | 14,733 | 15.8% | — | 74% |
| exponential smoothing (**chosen on calibration**) | 10,592 | 14,649 | 16.4% | +0.3% | 70% |
| SARIMA | 11,080 | 15,535 | 16.0% | +4.9% | 71% |
| Random Forest | 11,464 | 15,161 | 17.9% | +8.5% | 65% |
| XGBoost | 11,873 | 15,612 | 18.8% | +12.4% | 67% |

(Amounts in rupees, pooled over 20 people; full tables including the
remaining baselines in `data/experiments/forecasting/report.md`.)

**Interpretation.** A negative result. No method meaningfully beats a
simple baseline: the methods chosen on calibration were 2.0% (7 days) and
0.3% (30 days) *worse* than the best baseline on test. Rare one-off
purchases dominate the error and are unpredictable by design. MAE gaps of a
few percent are within the noise of this setup. The 30-day intervals
under-cover (65–74% against a target of 80%): the calibration period
(roughly March–July) contains no festive months while the test period
does, so calibration errors understate test errors. A seasonal calibration
window, or intervals from a full year of errors, is needed.

**Decision.** No forecasting model ships. The what-if simulator (Phase 7)
will start from the historical-mean baseline with intervals labelled as
estimates. These are the transaction-only baselines (Model A) for the
research question: scheduled commitments are 6–52% of spending (median 29%) in these
simulations and were never shown to these models, so Model B (adding
recorded upcoming bills) is the natural next experiment.

### E3: Unusual-spending detection, 2026-11-12

**Question.** Which method best flags payments that are unusual *for this
person*: personal z-scores per category (plain and robust), or Isolation
Forest / Local Outlier Factor?

**Data.** Synthetic: 40 simulated people, one year each, 4–6 categories with
their own amount distributions. Injected and labelled: amount spikes
(5–20× normal, ~1% of payments) and payments in a category the person never
uses. Decoys, *not* labelled anomalies: large but legitimate payments
(2–3× normal). Methods score each payment using only earlier payments;
Isolation Forest and LOF are fitted on days 0–179; everything is evaluated
on days 180–364. No category is judged before 8 earlier payments.

**Command.** `moneyos ml anomaly` (report: `data/experiments/anomaly/report.md`).

| Method | Precision | Recall | F1 (bootstrap 95% CI over people) | False alarms / month | Decoys flagged | Spikes found | New categories found |
| --- | --- | --- | --- | --- | --- | --- | --- |
| z-score | 0.840 | 0.929 | 0.882 (0.844–0.918) | 0.14 | 15/81 | 172/181 | 12/17 |
| robust z-score | 0.756 | 0.939 | 0.838 (0.796–0.877) | 0.25 | 20/81 | 174/181 | 12/17 |
| Isolation Forest | 0.764 | 0.672 | 0.715 (0.644–0.779) | 0.17 | 4/81 | 130/181 | 3/17 |
| LOF | 0.683 | 0.763 | 0.721 (0.665–0.774) | 0.29 | 11/81 | 149/181 | 2/17 |

**Interpretation.** Personal statistical baselines beat both ML methods on
F1 with non-overlapping intervals; the ML methods mostly miss "a kind of
spending you never do", which needs per-person category history rather
than a global feature space. The plain z-score had the best point
estimate, but its interval overlaps the robust z-score's.

**Decision.** The pre-registered rule (prefer the simplest, most explainable
method unless another is better with non-overlapping intervals) selects the
**robust z-score**. It was not changed after seeing the results. Its cost:
about 0.1 more false alarms per month than the plain z-score here. Shipped as
`GET /api/v1/ml/unusual` with plain reasons and a dismiss action. Isolation
Forest and LOF are not used.

**Limits.** Injected anomalies are only the two kinds designed here. Real
"unusual" also includes new merchants, odd times and changed habits, none of
which this tests.

### E4: Spending-behaviour clustering (research check), 2026-11-12

**Question.** (1) If people come in distinct spending types, can K-Means /
hierarchical clustering recover them? (2) If they do not, does clustering
warn us?

**Data.** Synthetic, 5 seeds × 200 people. (1) Four well-separated
archetypes (frugal saver, foodie, shopper, traveller). (2) Features varying
smoothly with no types. Features as in the FinSight spec.

**Command.** `moneyos ml clustering`.

| Method | Recovers 4 real types (ARI mean / min) | k picked by silhouette | Best silhouette, real types | Best silhouette, no types |
| --- | --- | --- | --- | --- |
| K-Means | 1.000 / 1.000 | 4 in all 5 seeds | 0.654 | 0.114 |
| Hierarchical (Ward) | 1.000 / 1.000 | 4 in all 5 seeds | 0.654 | 0.085 |

**Interpretation.** Recovery is perfect because the archetypes are well
separated by construction (the easy case). With no real types, clustering
still returns tidy groups; only the low silhouette reveals they mean
nothing.

**Decision.** No clustering feature in the app: MoneyOS has one user, so
there is no population. If multi-user data ever exists, clusters must be
reported with their silhouette and never shown as labels for people.
