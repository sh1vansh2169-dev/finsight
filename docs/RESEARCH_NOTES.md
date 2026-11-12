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
   date ranges. **Partly built (Phase 4):** `analytics/coverage.py` derives
   per-account coverage intervals and gaps from imports, and every
   cash-flow series point carries a coverage fraction. Still approximate
   (first-to-last transaction date per file).
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
- 2026-11-11: Coverage indicators available from analytics (Phase 4). No
  forecasting experiments run yet.
- 2026-11-12: **Baseline A done** (ML_EXPERIMENTS.md, E2): on 20 simulated
  people, no transaction-only model beat simple baselines for 7- or 30-day
  spending totals; one-off purchases dominate the error. The simulator
  already records scheduled commitments separately (6–52% of spending,
  median 29%), so Model B (adding recorded upcoming bills) can be tested on
  the same data and protocol. Caution for B: the simulator's commitments are
  perfectly regular by construction, which flatters any model that is told
  about them; a fair test needs late, missing and changed bills too.
