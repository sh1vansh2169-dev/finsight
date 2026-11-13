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

## Statement inbox (optional)

```powershell
.\.venv\Scripts\moneyos.exe serve --watch "$env:USERPROFILE\Downloads\FinSight"
```

Save statements into that folder, or into a subfolder named after the
account (`FinSight\HDFC Savings\march.pdf`). Within a few seconds each
appears under Transactions as waiting for review; it is never added on
its own. Read files move to `done\`, unreadable ones to `could not read\`
with a `.txt` note. With more than one account, set `MONEYOS_WATCH_USER`
to the email whose ledger the inbox fills. The same can be set with
`MONEYOS_WATCH_DIR`.

## SMS alerts (Android)

1. On the phone, install *SMS Backup & Restore* and back up messages to a
   file (choosing only your banks' conversations keeps it small and private).
2. Copy the `.xml` file into the statement inbox (or upload it in
   Transactions → Import statement). Up to 50 MB.
3. Review the alerts it found, then add them.

The backup holds all your messages. FinSight keeps only money alerts, but
the file itself stays wherever you put it (`done\` after the inbox reads
it): delete it once imported if you do not want a copy of your messages
on the computer.

## Gmail (optional)

One-time setup in Google Cloud (free; your own project and key):

1. Go to https://console.cloud.google.com and create a project (any name).
2. *APIs & Services → Library*: enable **Gmail API**.
3. *APIs & Services → OAuth consent screen* (Google Auth Platform): user type
   **External**, app name "FinSight", your email as support and developer
   contact. Under *Audience / Test users*, add your own Gmail address. Leave
   the app in **Testing**: only test users can sign in.
4. *Credentials → Create credentials → OAuth client ID*, application type
   **Desktop app**. Download the JSON file into `data\` (never committed),
   for example `data\gmail-client.json`.

Then:

```powershell
.\.venv\Scripts\moneyos.exe gmail connect --client data\gmail-client.json   # approve read-only access
.\.venv\Scripts\moneyos.exe gmail fetch --inbox "$env:USERPROFILE\Downloads\FinSight"
.\.venv\Scripts\moneyos.exe serve --watch "$env:USERPROFILE\Downloads\FinSight" --gmail     # or: every 30 minutes
.\.venv\Scripts\moneyos.exe gmail disconnect                                  # forget it on this computer
```

Google may say the app is "not verified": that is expected for your own
app in Testing mode. In Testing mode Google expires the sign-in after
about 7 days; run `gmail connect` again when fetching says so. The searches
can be changed with `MONEYOS_GMAIL_STATEMENTS` and `MONEYOS_GMAIL_ALERTS`
(Gmail search syntax). Password-protected e-statements go to
`could not read\` as usual; alert emails do not have that problem.

## The assistant (optional)

1. Install Ollama from https://ollama.com and start it.
2. Pull a model that supports tool calling: `ollama pull qwen2.5:7b`
   (the default; set `MONEYOS_ASSISTANT_MODEL` to use another).
3. Start FinSight and open Insights → Ask.

Tests never need a model: they use a scripted stand-in and a stand-in
Ollama HTTP server (`tests/test_assistant.py`).

## Configuration

See [.env.example](../.env.example). Set variables in the shell, e.g.
`$env:MONEYOS_ALLOW_SIGNUP = "true"`. FinSight does not read `.env` files itself.
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
