# Research notes

## Provisional question

> Can incorporating recorded personal financial obligations and
> transaction-source completeness improve short-term cash-flow forecasting
> compared with transaction-only baselines?

This is a hypothesis to investigate. **No claim of novelty is made.** A
structured literature review and prior-art search must come before any
such claim.

## Planned comparison

| Model | Inputs |
| --- | --- |
| A (baseline) | Historical transactions only |
| B | A + recorded upcoming bills |
| C | B + outstanding liabilities |
| D | C + uncertain expected repayments + source-coverage indicators |

Targets and horizons are to be fixed before the first run (for example
total outflow over the next 7 and 30 days). Evaluation: rolling-origin
(walk-forward) backtests, MAE and RMSE per horizon, behaviour under
simulated missing records, budget-overrun warning precision and recall,
and variation across simulated profiles.

## Prerequisites (not yet built)

1. Obligations data: bills and recurring commitments (Phase 7), loans and
   repayments (Money Majra, Phase 5). Transaction types for lending already
   exist in the ledger.
2. Source-coverage indicators: which accounts were imported for which
   date ranges. Import batches already record the file and its rows, but
   not the coverage period. This needs adding.
3. A synthetic profile generator with known obligations and controllable
   missingness, extending `domain/synthetic.py`.

## Threats to validity

- Synthetic profiles encode the author's assumptions. Improvements found
  only on synthetic data may not transfer to real behaviour.
- With one real user, results are a case study, not a generalisable finding.
- Obligations recorded by the user may be incomplete in the same periods
  where transactions are missing.

## Literature review

_Not started._ Areas to search: personal cash-flow forecasting;
intermittent and lumpy demand forecasting; forecasting with known future
covariates; missing-data mechanisms in time series; account aggregation
data quality.

## Log

- 2026-10-14: Question recorded. No experiments run.
