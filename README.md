# MoneyOS

Personal finance toolkit. Version 0.1 is the import pipeline: read bank and
card CSV exports, clean them, remove duplicates, and produce summaries.

All data in this repository is synthetic. Real statements belong outside the
repo or under `data/`, which is git-ignored except for `data/synthetic/`.

## Quick start (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m moneyos sample data\synthetic
.\.venv\Scripts\python.exe -m moneyos import (Get-ChildItem data\synthetic\*.csv).FullName
```

`import` options: `--account NAME`, `--currency CODE`, `--month-first`,
`--json`, `--export clean.csv`.

## Architecture

The core has no third-party dependencies (standard library only). Money is
`decimal.Decimal` everywhere; floats are never used.

```
CSV files -> importer -> cleaning -> categorize -> dedupe -> summary -> report / CLI
```

| Module | Responsibility |
| --- | --- |
| `models.py` | `Transaction` (signed amount: positive = money in) and `RejectedRow` |
| `cleaning.py` | Parse amounts and dates, normalise descriptions. Ambiguous values are rejected, not guessed |
| `importer.py` | Map each bank's column names and debit/credit layout onto `Transaction`; collect rejected rows with reasons |
| `categorize.py` | Keyword rules, first match wins |
| `dedupe.py` | Remove re-imported rows across overlapping files; flag identical rows within one file |
| `summary.py` | Income, expenses, net, by month, by category, largest expenses, per currency |
| `pipeline.py` | Runs the stages in order and returns one `PipelineResult` |
| `report.py`, `cli.py` | Text report, JSON, cleaned CSV export |
| `synthetic.py` | Seeded synthetic statements plus the expected outcome, used by the end-to-end tests |

### Behaviour worth knowing

- **Duplicates.** A row with a bank reference is identified by account +
  reference. Otherwise by account, date, amount, currency and normalised
  description, plus its occurrence number within the file. So two identical
  coffees in one export are both kept (and listed for review), while the
  same two coffees in a later overlapping export are both dropped.
- **Account names matter for de-duplication.** If a file has no account
  column, the account defaults to the file name. Two exports of the same
  account under different file names will not be de-duplicated against each
  other unless you pass `--account`.
- **Dates.** `03/04/2026` is read as 3 April unless `--month-first` is
  given. There is no per-row fallback to the other order.
- **Transfers** are excluded from income and expenses and reported separately.
- **Refunds** count as income; they do not reduce the category's spend.
- **Currencies** are summarised separately and never added together.

### Known limits

- Decimal-comma amounts (`1.234,56`) are rejected.
- No fuzzy matching: a pending and a posted copy of one transaction with
  different dates or descriptions is only caught when both carry the same
  reference.
- A file where some rows have references and a later export of the same rows
  has none will not be matched.
- Categorisation is a small hard-coded keyword list.
- Nothing is stored; every run starts from the CSV files.

## Roadmap

1. **Import pipeline (this version).** CSV import, cleaning, duplicate
   detection, summaries, CLI, tests.
2. **Storage.** SQLite via the standard library `sqlite3`: accounts,
   transactions, import batches. `deduplicate(existing=...)` already accepts
   previously stored transactions, so re-imports become incremental.
3. **Rules and review.** User-editable category rules in a config file,
   a review step for suspected duplicates and rejected rows, refund and
   transfer pairing across accounts, pending/posted fuzzy matching.
4. **Budgets and reporting.** Monthly budgets per category, recurring
   payment detection, trends.
5. **Interface.** A local API (FastAPI) and web UI (Node is installed), or
   a simpler Streamlit dashboard. Decide once phases 2-4 settle the data
   model.
6. **More formats.** OFX/QIF, Excel, PDF statements.

## Tooling gaps on this machine

- **git is not installed**, so the project is not under version control.
  Install Git for Windows, then run `git init` here.
- Python 3.14 had only `pip`; `pytest` is installed in `.venv`. `ruff`
  exists only in the Anaconda install and is not wired up yet.
- No Docker (not needed so far).
