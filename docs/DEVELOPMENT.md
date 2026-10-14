# Development guide

## Requirements

| Tool | Version used | Needed for |
| --- | --- | --- |
| Python | 3.14.8 (3.12+ supported by `pyproject.toml`) | Backend |
| Git | 2.56 | Version control |
| Flutter | 3.47.7 (downloaded, not yet on PATH) | Mobile app, Phase 8 |
| Android Studio / SDK | not installed | Mobile app, Phase 8 |

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
```

Open http://127.0.0.1:8000/docs for interactive API documentation. To try
an import there: `POST /api/v1/imports/preview` with a CSV, check the rows,
then `POST /api/v1/imports/{id}/commit`.

Run commands from the repo root: default database paths are relative to
the current directory.

## Configuration

See [.env.example](../.env.example). Set variables in the shell, e.g.
`$env:MONEYOS_API_TOKEN = "..."`. MoneyOS does not read `.env` files itself.

## Conventions

- **Money:** `Decimal` in code, integer minor units in the database, strings
  in JSON. Never `float`.
- **Dates:** `date` for transaction dates; timezone-aware UTC `datetime`
  for timestamps.
- **Layering:** `domain` must not import from `db`, `services` or `api`.
- **Tests:** every financial calculation gets a unit test and, where
  possible, an invariant test. Warnings fail the test run.
- **Data:** only synthetic data in the repo. Generated samples are named
  `sample_*` and carry a README marker.
- **Commits:** small and focused, with messages saying why as well as what.
