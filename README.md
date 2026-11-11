# MoneyOS

A personal finance ledger that is honest about what it knows. MoneyOS imports
bank and card statements, cleans and de-duplicates them, keeps a unified
ledger with provenance for every value, and reports recorded totals. It is
the foundation for later analytics, forecasting and ML work.

> **Status: v0.5, early development.** Not production-ready and not
> security-reviewed. Use synthetic data unless you understand
> [SECURITY.md](docs/SECURITY.md).

## What works today

All of this is covered by automated tests (732 passing at the last run, most of them property-based checks over random cases; see
[DEVELOPMENT.md](docs/DEVELOPMENT.md) to run them yourself).

| Area | Implemented |
| --- | --- |
| CSV import | Column mapping for common layouts (signed amount, debit/credit columns, amount + DR/CR), date/amount/currency/status normalisation, per-row validation with reasons |
| Import workflow | Preview → commit or discard, import history, file-hash warning on re-import |
| Duplicates | Exact match by bank reference; occurrence-aware matching otherwise; re-checked at commit time |
| Duplicate review | Explainable near-duplicate detection across sources (e.g. payment-app export vs bank statement) with a review queue: confirm, reject, undo, all audited. Nothing is merged automatically |
| Schema migrations | Alembic, applied on startup; v0.2 databases upgrade in place |
| Analytics (Pandas) | Daily / weekly / monthly cash flow with statement coverage (unknown periods are null, not zero), spending statistics, weekday patterns, month-over-month change, data-quality report |
| Budgets | Monthly limit per category; use, remaining, neutral status, pace estimate |
| Dashboard data | One call for the Home screen: month summary, trends, recent transactions, budgets, warnings, and a list of sections not built yet |
| Reports | `moneyos report`: Markdown report with charts, including what it cannot tell you |
| Money Majra | People and groups; shared expenses (equal, exact, percentage or weighted splits, exact to the paisa); loans; partial repayments; balances that always sum to zero; a settlement plan with the fewest payments; protection against overpaying, repeated payments and double-linked bank payments; void with history; link to bank transactions |
| Ledger | Unified schema, integer minor units, transaction types (expense, income, transfer, refund, lent, borrowed, repayments, reversal, unknown), provenance of every classification |
| Manual entry & corrections | Cash/manual transactions; user corrections of type and category with an audit trail |
| Summaries | Recorded inflow/outflow/net, income, spending after refunds (refunds reduce spending in their category), unclassified money, transfers, by month and category, data-quality warnings |
| API | FastAPI backend with OpenAPI docs at `/docs` |
| Data separation | Sample and real data live in separate, stamped databases that refuse to be mixed |

## Not built yet

See the [roadmap](#roadmap). In particular: no web app or any screens
(the dashboard exists as API data only), no ML models, no
forecasts, no
payment-app integrations, no LLM assistant. **No ML model has been trained
yet.**

## Quick start (Windows PowerShell, from the repo root)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
.\.venv\Scripts\python.exe -m pytest backend          # run the tests
.\.venv\Scripts\moneyos.exe seed-sample               # load synthetic data into data/sample/
.\.venv\Scripts\moneyos.exe serve --sample            # http://127.0.0.1:8000/docs
```

Other commands:

```powershell
.\.venv\Scripts\moneyos.exe import data\synthetic\*.csv   # analyse files, save nothing
.\.venv\Scripts\moneyos.exe serve                         # real data in data/moneyos.db
```

## Repository layout

```
backend/        Python package (FastAPI, SQLAlchemy) and its tests
  src/moneyos/
    domain/     pure financial logic: parsing, classification, dedupe, summaries
    db/         database schema and session setup
    services/   domain logic applied to the database (imports, ledger)
    api/        HTTP layer
  tests/
data/synthetic/ generated sample statements (the only data that is committed)
docs/           architecture, data dictionary, security, research and ML notes
frontend/       (planned) React + TypeScript web app
```

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md): how the system fits together and why
- [DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md): every table, field and enum
- [DEVELOPMENT.md](docs/DEVELOPMENT.md): setup, commands, workflow
- [SECURITY.md](docs/SECURITY.md): threat model and current limitations
- [ML_EXPERIMENTS.md](docs/ML_EXPERIMENTS.md): experiment log (no ML yet; one heuristic baseline)
- [UI_UX.md](docs/UI_UX.md): design requirements for the Phase 8 app
- [FINSIGHT_SPEC.md](docs/FINSIGHT_SPEC.md): the FinSight spec and how it was merged
- [RESEARCH_NOTES.md](docs/RESEARCH_NOTES.md): the research question and plan

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation and data schema | **Done** |
| 2 | CSV import and manual entry | **Done** (CSV formats beyond the supported layouts: planned) |
| 3 | Normalisation, deduplication, ledger | **Done**: exact dedupe, near-duplicate review queue, audit trail. Open: transfer pairing between your own accounts, reversal pairing |
| 4 | Dashboard and descriptive analytics (Pandas) | **Done** (data and API; the screens themselves are Phase 8) |
| 5 | Money Majra: lending, borrowing, shared expenses, repayments, settlements | **Done** (API; screens are Phase 8) |
| 6 | ML and forecasting: categorisation (rules vs TF-IDF + Logistic Regression, Random Forest, XGBoost); forecasting (baselines vs exponential smoothing, SARIMA, Random Forest, XGBoost); anomaly detection (z-score vs Isolation Forest, LOF); spending clustering as research | Not started |
| 7 | Recurring payment detection, commitments, financial digital twin (what-if), rule-based recommendations | Not started |
| 8 | Web app: React + TypeScript + Tailwind; user accounts, login (JWT), per-user data isolation | Not started |
| 9 | More sources: Excel and supported PDF statements; authorised integrations research (Account Aggregator) | Not started; research first |
| 10 | LLM assistant with tool calling, answers grounded in backend calculations | Not started |
| 11 | PostgreSQL + Docker deployment, security review, release | Not started |

The FinSight specification was merged into this plan on 2026-11-11; see
[docs/FINSIGHT_SPEC.md](docs/FINSIGHT_SPEC.md) for what was adopted, when, and
what was kept from MoneyOS.

All data in this repository is synthetic. Never commit real statements.
