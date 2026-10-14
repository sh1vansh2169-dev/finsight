# ML experiments

**No experiments have been run. No metrics exist.** This file records each
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

## Leakage risks to guard against

- Duplicate or near-duplicate descriptions in both train and test sets:
  split by merchant or by time, not by random row.
- Rules that were written after looking at the test set.
- Forecast features computed with centred windows or full-period
  statistics.

## Log

_Empty._
