# Development guide

## Requirements

| Tool | Version used | Needed for |
| --- | --- | --- |
| Python | 3.14.8 (3.12+ supported by `pyproject.toml`) | Backend |
| Git | 2.56 | Version control |
| Node.js | 22.22 or later (developed on 24) | React web app |

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

Machine-learning experiments (need the `ml` extra, included in `dev`):

```powershell
.\.venv\Scripts\moneyos.exe ml categorization   # E1; saves the chosen model to data\models
.\.venv\Scripts\moneyos.exe ml forecasting      # E2
.\.venv\Scripts\moneyos.exe ml anomaly          # E3
.\.venv\Scripts\moneyos.exe ml clustering       # E4
```

Each writes `results.json` and `report.md` under `data\experiments\<name>`.
Results are deterministic for a given seed and library version; record any
re-run in ML_EXPERIMENTS.md.

The report is reproducible: the same database gives the same tables and
charts (only the "Generated" date changes). Reports go under `data/`, which
is git-ignored, because a report on real data contains real data.

Open http://127.0.0.1:8000/docs for interactive API documentation. To try
an import there: `POST /api/v1/imports/preview` with a CSV, check the rows,
then `POST /api/v1/imports/{id}/commit`.

Run commands from the repo root: default database paths are relative to
the current directory.

## Checking dependencies for known vulnerabilities

```powershell
.\.venv\Scripts\python.exe -m pip_audit       # Python packages
cd frontend; npm audit                          # web app packages
```

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

## Accounts

Every API call needs a signed-in user. The first account can be created
through the API (`POST /api/v1/auth/register`) or locally:

```powershell
.\.venv\Scripts\moneyos.exe user create you@example.com          # asks for the password twice
.\.venv\Scripts\moneyos.exe user set-password you@example.com    # also ends existing sign-ins
.\.venv\Scripts\moneyos.exe user list
```

Add `--sample` to work on the sample database, and `--password-stdin` to
read the password from a pipe (a byte-order mark and CRLF are removed).
In the interactive docs (`/docs`), sign in with `POST /api/v1/auth/login`,
then use the **Authorize** button with the returned token.

## Web app

```powershell
cd frontend
npm install          # once, and after package.json changes
npm test             # Vitest + Testing Library, against a fake API (no server needed)
npm run typecheck    # TypeScript only
npm run build        # typecheck, then build into frontend\dist
npm run dev          # Vite dev server on http://localhost:5173 with hot reload
```

`moneyos serve` serves the built app from `frontend/dist` at http://127.0.0.1:8000,
so after `npm run build` the whole app runs from one address. For development,
run `moneyos serve --sample` and `npm run dev` side by side: Vite forwards `/api`
and `/health` to port 8000. If `frontend/dist` does not exist the server still
runs; only the API is available.

The page tests replace `fetch` with a fake API (`src/test/helpers.tsx`) built
from synthetic fixtures (`src/test/fixtures.ts`), and drive the real router.
jsdom does not see files attached with `user.upload` when checking a
`required` file input, so the import test submits the form directly.

## The assistant (optional)

1. Install Ollama from https://ollama.com and start it.
2. Pull a model that supports tool calling: `ollama pull qwen2.5:7b`
   (the default; set `MONEYOS_ASSISTANT_MODEL` to use another).
3. Start MoneyOS and open Insights → Ask.

Tests never need a model: they use a scripted stand-in and a stand-in
Ollama HTTP server (`tests/test_assistant.py`).

## Configuration

See [.env.example](../.env.example). Set variables in the shell, e.g.
`$env:MONEYOS_ALLOW_SIGNUP = "true"`. MoneyOS does not read `.env` files itself.
`MONEYOS_FRONTEND_DIST` points the server at a different web-app build.

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
