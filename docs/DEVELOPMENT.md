# Development guide

## Requirements

| Tool | Version used | Needed for |
| --- | --- | --- |
| Python | 3.14.8 (3.12+ supported by `pyproject.toml`) | Backend |
| Git | 2.56 | Version control |
| Node.js | 24 | React web app, Phase 8 |

## Setup (Windows PowerShell, from the repo root)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
```

The install is editable: source changes apply without reinstalling.

## Everyday commands

```powershell
.\.venv\Scripts\python.exe -m pytest backend               # all tests
.\.venv\Scripts\python.exe -m pytest backend -k dedupe     # a subset
.\.venv\Scripts\moneyos.exe sample data\synthetic          # regenerate sample CSVs
.\.venv\Scripts\moneyos.exe import data\synthetic\*.csv    # analyse files without saving
.\.venv\Scripts\moneyos.exe seed-sample                    # load samples into data\sample\moneyos-sample.db
.\.venv\Scripts\moneyos.exe serve --sample                 # API on the sample database
.\.venv\Scripts\moneyos.exe serve                          # API on the real database (data\moneyos.db)
.\.venv\Scripts\moneyos.exe report --sample                # Markdown report + charts in data\reports\latest
```

The report is reproducible: the same database gives the same tables and
charts (only the "Generated" date changes). Reports go under `data/`, which
is git-ignored, because a report on real data contains real data.

Open http://127.0.0.1:8000/docs for interactive API documentation. To try
an import there: `POST /api/v1/imports/preview` with a CSV, check the rows,
then `POST /api/v1/imports/{id}/commit`.

Run commands from the repo root: default database paths are relative to
the current directory.

## Database schema changes

The app migrates its database automatically on startup. To change the
schema:

1. Edit the models in `backend/src/moneyos/db/tables.py`.
2. Generate a migration against a scratch database that is at the latest
   revision, then read and correct it (autogenerate is a draft, not truth):
   ```powershell
   $env:MONEYOS_DATABASE_URL = "sqlite:///data/scratch.db"
   .\.venv\Scripts\alembic.exe -c backend\alembic.ini upgrade head
   .\.venv\Scripts\alembic.exe -c backend\alembic.ini revision --autogenerate -m "describe the change"
   ```
3. Rename the new file in `db/migrations/versions/` to the next number
   (`0003_...py`) and set `revision` to match.
4. Run the tests. `test_migrations_match_the_models` fails if the models and
   migrations disagree.

## Configuration

See [.env.example](../.env.example). Set variables in the shell, e.g.
`$env:MONEYOS_API_TOKEN = "..."`. MoneyOS does not read `.env` files itself.

## Conventions

- **Money:** `Decimal` in code, integer minor units in the database, strings
  in JSON. Never `float`.
- **Dates:** `date` for transaction dates; timezone-aware UTC `datetime`
  for timestamps.
- **Layering:** `domain` and `analytics` must not import from `db`, `services` or `api`.
- **Unknown is not zero:** in analytics, a period without statement coverage
  is NaN/null, never 0.
- **Tests:** every financial calculation gets a unit test and, where
  possible, an invariant test. Warnings fail the test run.
- **Data:** only synthetic data in the repo. Generated samples are named
  `sample_*` and carry a README marker.
- **Commits:** small and focused, with messages saying why as well as what.
