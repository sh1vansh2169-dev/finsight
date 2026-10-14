# Architecture

## Layers

```
            HTTP (FastAPI)            CLI (argparse)
                 │                        │
        api/  ───┤                        │
                 ▼                        │
        services/  imports, ledger        │
                 │                        │
        db/  ◄───┤                        │
                 ▼                        ▼
        domain/  importer → cleaning → classify → dedupe → summary
```

Dependencies only point downwards. `domain/` imports nothing from the other
layers and has no database or web code, so the financial logic can be
tested in milliseconds and reused by notebooks, the CLI, the API and later
the forecasting code.

| Layer | Responsibility | Key files |
| --- | --- | --- |
| `domain` | Parse, validate, classify, de-duplicate, summarise | `importer.py`, `cleaning.py`, `classify.py`, `dedupe.py`, `summary.py`, `models.py`, `money.py` |
| `db` | Schema, engine, data-mode guard | `tables.py`, `session.py` |
| `services` | Workflows that combine domain logic with storage | `imports.py`, `ledger.py`, `mapping.py` |
| `api` | Validation (Pydantic), auth, HTTP status mapping | `app.py`, `routes.py`, `schemas.py`, `deps.py` |

## Key decisions

### Money is never a float
**Problem.** `0.1 + 0.2 != 0.3` in binary floating point. Sums of thousands
of transactions drift.
**Choice.** `Decimal` in Python, integer minor units (paise, cents) in the
database, decimal strings in JSON.
**Alternatives.** A `Numeric` column. SQLite has no decimal type, and
SQLAlchemy would pass the value through a float, so it was rejected.
**Limit.** Amounts are parsed to two decimal places, so three-decimal
currencies (KWD, BHD) are not supported. Zero-decimal currencies (JPY)
reject fractional amounts.

### Separating facts from guesses (`Basis`)
Every inferred field carries a basis: `source` (the file said so), `user`,
`rule`, `model` (reserved for ML), or `none`. Rules only fill fields whose
basis is `none`, so they never overwrite a user's correction or a value
the bank stated. This is how the ledger distinguishes confirmed facts,
inferred classifications and missing information.

### Unknown stays unknown
Money in is not assumed to be income, and money out is not assumed to be an
expense. A debit becomes an `expense` only when a category rule matches it.
Everything else is `unknown`, and summaries report it as *unclassified
inflow/outflow* with a warning. Bare words like "transfer" are deliberately
not rules: a UPI "transfer" to a friend may be a loan.

### Duplicate detection
1. A row with a bank reference is identified by `(account, reference)`.
2. Otherwise by `(account, date, amount, currency, normalised description)`
   plus its occurrence number in the file. Two identical coffees in one file
   are both kept and flagged for review; the same two coffees in a later
   overlapping export are both dropped; a third would be kept.

**Why not fuzzy matching yet.** Matching on approximate dates or
descriptions needs a review queue and confidence thresholds, or it will
silently delete real transactions. That is Phase 3 follow-up work.
**Limit.** A file without an account column defaults its account to the
file name, so two exports of the same account under different names are not
de-duplicated against each other unless the account is specified.

### Two-step imports
`preview` parses, validates, classifies and checks duplicates, then stages
every row with its outcome (`new`, `suspected`, `duplicate`, `rejected`).
`commit` re-runs duplicate detection against the ledger *as it is at commit
time*, inside one database transaction, because another import may have
been committed after the preview. Rejected rows keep their raw cells for the
error report; nothing is silently dropped.

### Sample and real data never mix
Each database is stamped (`app_meta.data_mode`) the first time it is opened.
A sample database cannot be opened in real mode or the reverse, and a
database that has data but no stamp is refused. Sample and real data
therefore live in different files by construction, not by convention.

### Summaries are recorded totals, not balances
Every summary response says so. Failed transactions are excluded; pending
and source-reversed ones are counted with a warning; transfers between your
own accounts are reported separately and excluded from net cash flow.
Different currencies are never added together.

### Database migrations
The schema is portable (no SQLite-only types), so it can move to
PostgreSQL. Tables are currently created with `create_all`, which only adds
missing tables. **Alembic must be introduced before the first schema change
that has to preserve existing data.**

### Synchronous SQLAlchemy in FastAPI
Route handlers are plain `def` functions, so FastAPI runs them in a thread
pool. For a single-user local app this is simpler than async drivers, with
no meaningful cost.

## Testing strategy

| Level | What | Where |
| --- | --- | --- |
| Unit | Parsing, classification, dedupe, summaries, invariants (parts sum to totals) | `tests/domain/` |
| Ground truth | A seeded synthetic generator computes expected totals from its own ledger; the pipeline must reproduce them across five seeds | `test_pipeline.py`, `test_services.py`, `test_api.py` |
| Integration | Real SQLite file: preview/commit, concurrency-style re-checks, constraints, audit trail, data-mode guard | `test_services.py` |
| HTTP | Status codes, JSON money format, validation, auth | `test_api.py` |

Warnings are errors in the test run (`filterwarnings = error`), which caught
a dependency deprecation and two leaked database connections during
development. The tests were also checked by deliberately breaking key logic
(mutation testing by hand). Each break was caught.

## Concepts worth learning from this code

- **Decimal arithmetic and minor units**, and why floats are wrong for money.
- **Idempotency**: importing the same file twice must change nothing.
- **Provenance and lineage**: every number traceable to a file and row.
- **Invariants as tests**: "categories sum to expenses", "net equals the sum
  of included signed amounts".
- **Staging tables**: preview/commit is the same pattern data warehouses use.
- **Layered architecture**: pure core, thin I/O shells.
