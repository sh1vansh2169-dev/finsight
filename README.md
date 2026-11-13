# MoneyOS

A personal finance ledger that is honest about what it knows. MoneyOS imports
bank and card statements, cleans and de-duplicates them, keeps a unified
ledger with provenance for every value, and reports recorded totals. It is
the foundation for later analytics, forecasting and ML work.

> **Status: v0.8, early development.** Not production-ready and not
> security-reviewed. Use synthetic data unless you understand
> [SECURITY.md](docs/SECURITY.md).

## What works today

All of this is covered by automated tests (809 backend tests, many of them property-based checks over random cases, and 25 web-app tests, all passing at the last run; see
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
| Category suggestions (ML) | TF-IDF + Logistic Regression suggests categories for transactions the rules missed, with confidence and alternatives; bulk apply only above high confidence, marked as model-inferred. Trained on synthetic data so far |
| Recurring payments and commitments | Detects rent, bills, subscriptions and salary (cadence, typical amount, next date, confidence, reasons); you confirm them as commitments or add your own; upcoming payments and how much to keep aside |
| What-if simulator | Next 7–90 days from commitments plus estimated everyday spending, with a range; scenarios for a purchase, a new bill, a category cut, a delayed repayment or skipping a commitment; money owed to you never counted as yours; no balance unless you give one |
| Recommendations | Rule-based, neutral, with their evidence: rising categories, budgets, subscriptions, money owed, the reserve for commitments, data to tidy |
| Unusual payments | Payments unusually large for you, per category, with a plain reason and a dismiss action. Never called fraud |
| ML experiments | `moneyos ml categorization / forecasting / anomaly / clustering`: reproducible, against baselines, logged in ML_EXPERIMENTS.md |
| Ledger | Unified schema, integer minor units, transaction types (expense, income, transfer, refund, lent, borrowed, repayments, reversal, unknown), provenance of every classification |
| Manual entry & corrections | Cash/manual transactions; user corrections of type and category with an audit trail |
| Summaries | Recorded inflow/outflow/net, income, spending after refunds (refunds reduce spending in their category), unclassified money, transfers, by month and category, data-quality warnings |
| API | FastAPI backend with OpenAPI docs at `/docs` |
| Accounts and privacy | Sign-up, sign-in and sign-out; passwords hashed with scrypt; revocable sessions stored only as hashes; lockout after repeated failures; every user sees only their own data, enforced in the database layer; delete your account and all your data |
| Data separation | Sample and real data live in separate, stamped databases that refuse to be mixed |
| Web app (first screens) | React + TypeScript + Tailwind, served by the backend: sign-in; Home (month figures, daily chart with uncovered days as gaps, 30-day outlook, budgets, Money Majra, recent transactions); Transactions (search, filters, category and type corrections, two-step statement import); Money Majra (add people and groups, shared expenses split equally or by exact amounts, percentages or shares, loans, repayments with a repeat-payment check, cancel an entry with a reason); Insights (read-only); Profile (theme, sign out, delete account). Light and dark themes; phone and desktop layouts |

## Not built yet

See the [roadmap](#roadmap). In particular: the web app cannot yet
review duplicates, manage budgets or commitments, or run the what-if simulator (all of these work
through the API at `/docs`), no forecasting model in the app (none beat simple
baselines; the what-if simulator uses the historical average), no payment-app integrations, no
LLM assistant. **Every ML result so far is on synthetic data**; see
[ML_EXPERIMENTS.md](docs/ML_EXPERIMENTS.md).

## Quick start (Windows PowerShell, from the repo root)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
.\.venv\Scripts\python.exe -m pytest backend          # run the tests
.\.venv\Scripts\moneyos.exe seed-sample               # load synthetic data into data/sample/
.\.venv\Scripts\moneyos.exe serve --sample            # http://127.0.0.1:8000/docs
# sign in with the account printed by seed-sample (see docs/DEVELOPMENT.md, Accounts)
```

The web app (needs Node.js 22.22 or later), in a second terminal:

```powershell
cd frontend
npm install
npm test                # run the web-app tests
npm run build           # then open http://127.0.0.1:8000
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
frontend/       React + TypeScript + Tailwind web app (src/pages, src/components, src/api, src/test)
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
| 6 | ML and forecasting: categorisation, forecasting, anomaly detection, clustering, each against baselines | **Done on synthetic data** (experiments E1–E4). Shipped: category suggestions, unusual-payment flags. Not shipped: forecasting (no model beat the baselines), clustering. Next: research Models B–D |
| 7 | Recurring payment detection, commitments, what-if simulator, rule-based recommendations | **Done** (API; screens are Phase 8). Research Models B–D are the next experiment |
| 8 | Web app: React + TypeScript + Tailwind; user accounts, login, per-user data isolation | **In progress**: accounts and isolation done (8a); web app first screens and Money Majra forms done (8b, steps 1–2); duplicate review, budgets, commitments and the simulator next |
| 9 | More sources: Excel and supported PDF statements; authorised integrations research (Account Aggregator) | Not started; research first |
| 10 | LLM assistant with tool calling, answers grounded in backend calculations | Not started |
| 11 | PostgreSQL + Docker deployment, security review, release | Not started |

The FinSight specification was merged into this plan on 2026-11-11; see
[docs/FINSIGHT_SPEC.md](docs/FINSIGHT_SPEC.md) for what was adopted, when, and
what was kept from MoneyOS.

All data in this repository is synthetic. Never commit real statements.
