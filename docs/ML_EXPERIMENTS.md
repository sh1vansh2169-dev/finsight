# ML experiments

**No ML model has been trained yet.** One heuristic (non-ML) evaluation is
logged below as a future baseline. This file records each
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
| 1 | Transaction categorisation | Keyword rules (`default_rules.toml`), majority class | TF-IDF + Logistic Regression | Per-class precision/recall/F1, macro-F1, confusion matrix, coverage at a confidence threshold | Not started. Needs a labelled set; user corrections (`category_basis = user`) are the intended source |
| 2 | Spending / cash-flow forecasting | Historical mean, last period, moving average | Exponential smoothing, Random Forest on lag/calendar features | MAE, RMSE per horizon; interval coverage where available | Not started. Needs analytics pipeline (Phase 4) |
| 3 | Anomaly detection | z-score / IQR per category, personal median | Isolation Forest | Precision/recall on injected anomalies; false-positive rate per month | Not started |
| 4 | Missing-data impact | Complete data | Data with records removed under MCAR / MAR / MNAR mechanisms | Change in forecast MAE/RMSE by missingness level | Not started |
| 5 | Duplicate-pair scoring | Hand-weighted matcher (E0 below) | Logistic regression on the same features, trained on user review decisions | Precision/recall at the review threshold; review items per true duplicate | Not started. Needs real review decisions |

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
