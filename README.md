# MoneyOS

A personal finance ledger that is honest about what it knows. MoneyOS imports
bank and card statements, cleans and de-duplicates them, keeps a unified
ledger with provenance for every value, and reports recorded totals. It is
the foundation for later analytics, forecasting and ML work.

> **Status: v0.2, early development.** Not production-ready and not
> security-reviewed. Use synthetic data unless you understand
> [SECURITY.md](docs/SECURITY.md).

## What works today

All of this is covered by automated tests (173 passing at the last run; see
[DEVELOPMENT.md](docs/DEVELOPMENT.md) to run them yourself).

| Area | Implemented |
| --- | --- |
| CSV import | Column mapping for common layouts (signed amount, debit/credit columns, amount + DR/CR), date/amount/currency/status normalisation, per-row validation with reasons |
| Import workflow | Preview → commit or discard, import history, file-hash warning on re-import |
| Duplicates | Exact match by bank reference; occurrence-aware matching otherwise; re-checked at commit time |
| Ledger | Unified schema, integer minor units, transaction types (expense, income, transfer, refund, lent, borrowed, repayments, reversal, unknown), provenance of every classification |
| Manual entry & corrections | Cash/manual transactions; user corrections of type and category with an audit trail |
| Summaries | Recorded inflow/outflow/net, income, expenses, refunds, unclassified money, transfers, by month and category, data-quality warnings |
| API | FastAPI backend with OpenAPI docs at `/docs` |
| Data separation | Sample and real data live in separate, stamped databases that refuse to be mixed |

## Not built yet

See the [roadmap](#roadmap). In particular: no mobile app, no dashboard UI,
no Money Majra, no analytics notebooks, no ML models, no forecasts, no
payment-app integrations, no LLM assistant. **No ML results exist yet.**

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
mobile/         (planned) Flutter app
```

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md): how the system fits together and why
- [DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md): every table, field and enum
- [DEVELOPMENT.md](docs/DEVELOPMENT.md): setup, commands, workflow
- [SECURITY.md](docs/SECURITY.md): threat model and current limitations
- [ML_EXPERIMENTS.md](docs/ML_EXPERIMENTS.md): experiment log (empty so far)
- [RESEARCH_NOTES.md](docs/RESEARCH_NOTES.md): the research question and plan

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation and data schema | **Done** |
| 2 | CSV import and manual entry | **Done** (CSV formats beyond the supported layouts: planned) |
| 3 | Normalisation, deduplication, ledger | **Partly done**: exact/occurrence dedupe done; explainable fuzzy candidate matching with review queue not started |
| 4 | Dashboard and descriptive analytics (Pandas) | Not started |
| 5 | Money Majra (shared expenses, lending) | Not started; transaction types already exist |
| 6 | Forecasting baselines and ML experiments | Not started |
| 7 | Financial digital twin | Not started |
| 8 | Mobile app (Flutter) and API integration | Blocked on local setup: Flutter is downloaded, but not on PATH and has no Android SDK |
| 9 | Authorised source integrations | Not started; research first |
| 10 | Optional LLM assistant | Not started |
| 11 | Hardening, security review, release | Not started |

All data in this repository is synthetic. Never commit real statements.
