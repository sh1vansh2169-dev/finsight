# Architecture

## Layers

```
            HTTP (FastAPI)            CLI (argparse)
                 │                        │
        api/  ───┤                        │
                 ▼                        │
        services/  imports, ledger, review, analytics, budgets, dashboard, report
                 │                        │
        db/  ◄───┤                        │
                 ▼                        ▼
        domain/     importer → cleaning → classify → dedupe → matching → summary, budgets
        analytics/  frame → coverage → aggregate, stats, quality, charts   (Pandas / NumPy / Matplotlib)
```

Dependencies only point downwards. `domain/` and `analytics/` import
nothing from `db`, `services` or `api`, so the financial and analytical
logic can be tested in milliseconds and reused by notebooks, the CLI, the
API and later the forecasting code.

| Layer | Responsibility | Key files |
| --- | --- | --- |
| `domain` | Parse, validate, classify, de-duplicate, match, summarise | `importer.py`, `cleaning.py`, `classify.py`, `dedupe.py`, `matching.py`, `summary.py`, `models.py`, `money.py` |
| `db` | Schema, migrations, engine, data-mode guard | `tables.py`, `session.py`, `migrations/` |
| `analytics` | Descriptive analytics in Pandas: coverage, time series, statistics, data quality, charts | `frame.py`, `coverage.py`, `aggregate.py`, `stats.py`, `quality.py`, `charts.py` |
| `ml` | Experiments and models: categorisation, forecasting, anomaly detection, clustering; synthetic data generators | `categorizer.py`, `forecasting.py`, `anomaly.py`, `clustering.py`, `experiments.py`, `corpus.py`, `spending_sim.py` |
| `services` | Workflows that combine domain logic with storage | `imports.py`, `ledger.py`, `review.py`, `analytics.py`, `budgets.py`, `dashboard.py`, `majra.py`, `report.py`, `mapping.py` |
| `api` | Validation (Pydantic), auth, HTTP status mapping, serving the web app | `app.py`, `routes.py`, `schemas.py`, `deps.py`, `auth.py`, `webapp.py` |
| `frontend` | React web app: screens, API hooks, display formatting | `src/App.tsx`, `src/pages/`, `src/components/`, `src/api/`, `src/lib/format.ts` |

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

**Limit.** A file without an account column defaults its account to the
file name, so two exports of the same account under different names are not
de-duplicated against each other unless the account is specified.

### Near-duplicates go to a review queue, never auto-merged
**Problem.** The same payment often reaches MoneyOS twice with different
details: a payment app's export and the bank statement of the linked
account ("Spice Route" on the 9th vs "UPI/SPICE ROUTE RESTAURANT/4471" on
the 10th), or a cash entry later seen on a statement. Exact rules cannot
see these, and guessing wrong silently deletes real money.
**Choice.** `domain/matching.py` proposes pairs. A pair must pass hard
gates (same currency, amount and direction; dates at most 3 days apart;
neither payment failed; no conflicting bank references on one account).
It is then scored 0–100: 30% date closeness, 55% description similarity
(token containment or fuzzy match after dropping rail words like "UPI"),
15% same account. Pairs scoring 60 or more are stored in
`match_candidates` with plain-language reasons. The user decides:
*same payment* (choose which record to keep; the other gets
`duplicate_of_id` and drops out of listings and totals) or *different
payments* (never proposed again). Every decision is audited and can be
undone.
**Alternatives.** Auto-merging above a threshold (rejected: one wrong merge
hides real spending, and the scores are not calibrated). A learned
classifier (premature: there are no labelled decisions yet; the review
queue is what will create them).
**Limits.** The weights are hand-chosen. The evaluation so far uses
synthetic data designed alongside the matcher (see ML_EXPERIMENTS.md, E0), so it shows
the code behaves as intended, not that the weights suit real data. Amounts
must match exactly, so a fee-inclusive copy will not be proposed. Summaries
warn while pairs are open, because totals may double-count until then.

### Refunds reduce spending
**Rule (from the FinSight spec).** A refund is not income: it reduces
spending. `spending = purchases (expenses) - refunds`, per period and per
category, everywhere spending is shown: summaries, the cash-flow series,
category statistics, charts and budgets.
**How.** A refund reduces spending in its own category (rules usually give
"SHOPKART REFUND" the same category as "SHOPKART ONLINE STORE"). Gross
purchases and refunds stay available separately, so money in and money
out still reconcile exactly.
**Limit.** Refunds are not yet linked to the purchase they reverse. A refund
arriving the month after the purchase reduces the later month, and a
category with only refunds in a period shows negative spending rather
than hiding it. Linking refunds to their purchases is the same matching
problem as duplicate review and is planned alongside transfer and reversal
pairing.

### Money Majra: who owes whom
**Problem.** Shared costs and informal loans (a trip split three ways, ₹500
lent to a friend) never appear correctly in bank data: the bank sees one
payment, not who owes what.
**Model.** People (exactly one is you, enforced by a unique index), groups
(a `direct` group per person and currency holds one-to-one lending),
and entries: shared *expenses* with per-person shares, *loans*, and
*payments* (repayments and settlements). Entries are voided, never
deleted, so history and the audit trail stay intact.
**Calculations** (`domain/majra.py`, pure and deterministic):
- *Splits* (equal, exact amounts, percentages, weights) use the largest-
  remainder method on whole paise: shares always add up to the amount, no
  share is off by a whole paisa from its exact value, and the leftover
  paisa goes to the participant listed first.
- *Balances*: positive means the person is owed. They sum to exactly zero
  in every group; this is checked on every calculation.
- *Settlement with the fewest payments.* The minimum is (people with a
  non-zero balance) − (the largest number of groups that each sum to zero),
  which is NP-hard in general. For up to 16 such people it is computed
  exactly with a dynamic programme over subsets (`dp[S] = max dp[S − i] +
  [S sums to zero]`) and each zero-sum group is settled with size − 1
  payments. Larger groups get a greedy plan (≤ n − 1 payments), flagged as
  not proven minimal. Tests compare the result against brute-force
  enumeration of all partitions on 150 random groups.
**Consistency rules.** A payment must go from someone who owes to someone
who is owed and may not exceed either side's balance (overpaying would
silently become a new loan). An identical payment on the same day is
refused unless explicitly confirmed. A bank transaction can back at most
one entry, and linking one sets its ledger type to lent, borrowed or
repayment (as a user correction, audited).
**Not guaranteed money.** What others owe you is shown separately as
"expected back" and is never added to ledger totals or treated as
available money.
**Limits.** No currency conversion: each group has one currency. A shared
expense you paid stays in your spending at the full amount; your
"real" share is visible only in Money Majra.

### Accounts and per-user isolation
**Problem.** Once more than one person can sign in, a single forgotten
`WHERE user_id = ...` in any query would leak someone's finances.
**Choice.** Isolation is enforced below the features (`db/tenancy.py`).
Every user-owned table has a `user_id`. Each database session states whose
data it serves; a SQLAlchemy `do_orm_execute` hook adds
`with_loader_criteria(user_id = ...)` to every ORM query (including lazy
relationship loads), and a `before_flush` hook stamps new rows and refuses
to save another user's row. A session that names no user cannot read user
data at all; sign-in and admin commands use explicit "system" sessions.
Services contain no user filters, and new features inherit isolation
automatically.
**A bug worth remembering.** The first version passed the user id to the
filter through a Python `lambda`. SQLAlchemy caches lambda criteria and does
not track default arguments, so the first user's id was reused for every
later query: each user would have seen the first user's data. Tests that
used one user at a time passed; it showed up only when two users queried
in the same process. A regression test now alternates users deliberately.
**Sessions** are opaque random tokens stored as SHA-256 hashes (revocable,
no signing keys to manage) rather than JWTs; passwords use scrypt. See
SECURITY.md.
**Existing data** is kept: the migration to v0.8 creates an `owner@localhost`
account without a password and assigns every existing row to it.

### The web app

React 19 + TypeScript (strict) + Tailwind 4, built with Vite and served by
the backend from `frontend/dist`, so the app and the API share one origin:
no CORS, and the session cookie never leaves the site.

- **Server state lives in TanStack Query.** Each API call is a hook in
  `src/api/hooks.ts`; after any change to the ledger, everything derived
  from it (transactions, dashboard, recommendations...) is refetched.
  Signing in or out clears the whole cache, so one person's data is never
  shown to the next. A 401 anywhere sets the user to signed-out, which
  sends the app to the sign-in page.
- **Money stays a string.** Amounts are passed to `Intl.NumberFormat` as
  decimal strings, so nothing is rounded through a float on the way to the
  screen. The one exception is the chart, which needs numbers to draw bar
  heights; it never does arithmetic that is shown as a figure. Where the
  app must add amounts itself (checking that a split adds up before
  saving), it converts the typed text to whole paise as a `BigInt`
  (`toMinor` in `src/lib/format.ts`), so 0.10 + 0.20 is exactly 0.30.
- **Unknown is drawn as a gap.** Days no statement covers are `null` and
  appear as missing bars with a note, never as zero spending.
- **Cookie sessions with a CSRF header** (see SECURITY.md): the token is
  in an `httpOnly` cookie the page cannot read, and changes need the
  `X-MoneyOS-CSRF` header, which `src/api/client.ts` adds.
- **Serving.** `api/webapp.py` registers a catch-all route last: files
  inside the build folder are served as they are; any other path gets
  `index.html` so the router can handle it. `/api`, `/docs` and `/health`
  are never shadowed. Every response carries the CSP and other headers.
- **Screens load on demand.** Each route is a lazy import, so the first
  visit downloads only the shell (about 116 kB compressed) and each screen
  arrives when first opened; the chart library comes with Home only.
- **Model output is worded as a question.** Category suggestions read
  "Looks like Health?", confidence is never shown as 100% or 0%, and
  alternatives the model gives under 5% are hidden.
- **Design tokens** (colours for light and dark, radius) are CSS variables
  in `src/index.css`, exposed to Tailwind with `@theme inline`. Text
  colours were checked for at least 4.5:1 contrast and form borders for
  3:1 in both themes.

### Commitments and the what-if simulator
**Recurring detection** (`analytics/recurring.py`) groups payments by a
cleaned merchant name and accepts a series when at least 75% of the gaps
fit one cadence (weekly, monthly, quarterly, yearly) within a tolerance;
several payments on one day mean a habit, not a schedule. Amounts that move
by more than 10% are marked as varying. Each detection has a 0–100
confidence and plain reasons, and is only a suggestion.
**Commitments** are what the user confirms (from a detection) or adds by
hand, including one-off future payments. Confirmed facts (commitments) are
kept apart from detected guesses (recurring suggestions).
**The simulator** (`domain/simulator.py`, pure and deterministic) projects
the next 7–90 days: commitments on their dates, everyday spending at the
historical average (E2 found nothing better), and scenario changes
(purchase, new recurring payment, category cut, delayed repayment, skipped
commitment). The range uses the high end of varying bills and the 10th/90th
percentiles of the user's own past spending over the same length of time.
**Rules that keep it honest.**
- *No double counting*: payments belonging to a confirmed commitment are
  removed from the everyday-spending history (tested to the rupee).
- *Owed money is not money you have*: what others owe appears only as "if
  repaid"; what you owe only as "if you repay".
- *No invented balance*: a balance is projected only from one the user
  enters.
- *Unknown is not zero*: everyday history uses only days a statement covers.
- Assumptions are returned with every projection.
**Recommendations** (`domain/recommend.py`) are a handful of transparent
rules with their evidence: a category rising at least 30% and ₹500 above its
recent average (two or more earlier months), budgets near or over, two or
more small fixed subscriptions, money owed for 30+ days, the reserve for
upcoming commitments, and data that needs attention. Wording is neutral; a
test rejects judgemental words.

### Machine learning (`ml/`)
**Principle.** A model is used only where it beats a simple baseline in an
experiment that was actually run; every run is reproducible with
`moneyos ml <experiment>` and logged in ML_EXPERIMENTS.md, including the
results that disappoint.
**Discipline applied in every experiment.**
- *Synthetic data, labelled as such.* There are no real labelled
  transactions yet. Generators (`ml/corpus.py`, `ml/spending_sim.py`,
  `ml/anomaly.py`) encode stated assumptions; results show whether a method
  captures those patterns, not real-world accuracy.
- *No leakage.* Text features are fitted inside each training fold
  (scikit-learn `Pipeline`); the categoriser is also evaluated on merchants
  never seen in training (grouped K-fold). Forecasts and anomaly scores use
  only data up to their own date; forecasting sets are chronological with
  purging so no target window crosses a boundary. Tests check each of these.
- *Pre-registered choices.* Hyperparameters, thresholds and the rule for
  picking a winner are written down before the full run, and not changed
  after seeing results.
- *Uncertainty.* Spread across folds and seeds, bootstrap intervals, and
  forecast intervals whose coverage is checked on held-out data.
**What runs in the app.**
- Category *suggestions* for transactions the rules left uncategorised
  (`/api/v1/ml/category-suggestions`), with confidence and alternatives.
  Applying them in bulk requires high confidence and records basis `model`,
  so they stay visibly inferred; the source file, the user and the rules
  always take precedence. Models are versioned files with a JSON model
  card (training data fingerprint, labels, settings, scores).
- Unusual-payment flags (`/api/v1/ml/unusual`): personal robust z-score per
  category, with plain reasons, a minimum history, and a dismiss action.
  Never described as fraud.
- No forecasting model is served; the simulator uses the historical-average
  baseline that E2 could not beat.

### Analytics: unknown is not zero
**Problem.** A day with no transactions means "nothing spent" only if a
statement for that day was imported. Otherwise it means "we don't know".
Treating unknown as zero drags averages down and invents trends.
**Choice.** Each account's *coverage* is estimated from its imports (first
to last transaction date of every committed file, overlaps merged).
Every period in a cash-flow series carries `coverage`, the share of
statement-backed accounts covering it. Periods with coverage 0 have
missing values (NaN in Pandas, `null` in JSON, a grey band in charts),
never 0. Partly covered periods keep their observed totals and are
labelled with their coverage. Weekday averages divide by covered days only.
**Money in Pandas** is held as signed int64 minor units, so sums are exact;
it becomes float64 only where NaN is needed (exact for any realistic
amount, below 2^53 paise) and Decimal on output.
**Cross-validation.** The Pandas monthly series and the older pure-Python
summary are separate implementations of the same definitions; tests require
them to agree to the paisa on several synthetic seeds.
**Limits.** Coverage is approximated by first/last transaction date, so it
slightly understates real statement periods. Accounts with only manual
entries (cash) have no coverage and are reported as such: missing *records*
cannot be detected from the data alone. Coverage is computed across all
accounts, not per currency.

### Budgets
A monthly limit per category and currency. The state (`on_track` under 80%,
`close` from 80%, `over` above the limit) is decided on exact amounts; the
percentage is rounded only for display. A pace projection (spending so far
scaled to the month) is offered only from day 7 of the current month and is
labelled an estimate. Messages use neutral wording ("over the limit"), never
judgement.

### Dashboard
`GET /api/v1/dashboard` returns one month (default: the month of the newest
transaction): recorded summary, daily and trailing-monthly series with
coverage, recent transactions, budget use and warnings. Sections that depend
on unbuilt phases (receivables and liabilities, forecasts, commitments) are
listed in `not_yet_available` so a client can say so instead of showing a
zero.

### Database migrations
The schema is managed by Alembic (`db/migrations/`). On startup, `init_db`
checks the data mode first (so a wrong-mode database is never touched) and
then upgrades to the latest revision. A database created by v0.2, before
migrations existed, is recognised (tables present, no `alembic_version`),
stamped as the baseline revision `0001`, and upgraded with its data intact.
A test compares the migrated schema with the models and fails on any
drift. SQLite needs "batch" migrations (table rebuilds) for most column
changes; the environment enables them.

### Two-step imports
`preview` parses, validates, classifies and checks duplicates, then stages
every row with its outcome (`new`, `suspected`, `duplicate`, `rejected`).
`commit` re-runs duplicate detection against the ledger *as it is at commit
time*, inside one database transaction, because another import may have
been committed after the preview. Rejected rows keep their raw cells for the
error report; nothing is silently dropped.

### Statement formats

`domain/statements.py` turns every supported file into a header plus rows of
cell text and hands them to `importer.import_records`, the same code path a
CSV takes. So validation, rejection reasons, duplicate checks and the
preview step are identical for every format, and one test imports the same
synthetic statement as CSV, Excel and PDF and requires identical results.

- **Detection by content**: `%PDF-` is a PDF, a zip signature is an .xlsx,
  the old Excel signature is refused with a message, anything else is CSV.
  A file's name is never trusted.
- **Excel**: first sheet, header found in the first 30 rows. Numbers arrive
  from Excel as binary floats; `repr()` gives the shortest decimal that reads
  back as the same float, which is exactly what was typed for any amount
  with up to 15 significant digits, so `0.10` stays `0.10`.
- **PDF, ruled tables**: `pdfplumber` table extraction.
- **PDF, tables without lines** (common in bank statements): words are
  grouped into lines; the header line's phrases define the columns, with
  boundaries halfway between neighbouring headings; each word goes to the
  column containing its centre. A line with only a description is joined
  to the transaction above *only if it sits directly under it*, so a footer
  further down the page becomes a visible rejected row instead of being
  glued onto a description. Lines above each page's repeated header are skipped.
- **Limits** for hostile files: 5 MB upload, 100 PDF pages, 20,000 rows,
  50 MB unpacked for an .xlsx (a "zip bomb" check before parsing), and
  `defusedxml` for the workbook's XML.

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
| Review | Proposals, decisions, undo, supersession, audit, totals before and after review | `test_review.py`, `test_matching.py` |
| Schema | Migrations equal the models; v0.2 databases upgrade with data intact; downgrade/upgrade | `test_migrations.py` |
| Analytics | Pandas series agree with the plain-Python summary; unknown periods stay NaN/null; statistics match Python's `statistics` module; charts render | `tests/analytics/`, `test_analytics_api.py` |
| Web serving and sessions | SPA fallback, API not shadowed, path traversal refused, cookie sessions and the CSRF header, search escaping | `test_webapp.py`, `test_auth.py` |
| Web app | Formatting, the API client (CSRF header, errors), and pages driven through the real router against a fake API: sign-in and redirects, Home, search, corrections, import preview/commit | `frontend/src/test/` |

Warnings are errors in the test run (`filterwarnings = error`), which caught
two dependency deprecations and two leaked database connections during
development. The tests were also checked by deliberately breaking key logic
(mutation testing by hand). One break initially went undetected (the
matcher's list of ignored payment-rail words), and a test was added for it.

## Concepts worth learning from this code

- **Decimal arithmetic and minor units**, and why floats are wrong for money.
- **Idempotency**: importing the same file twice must change nothing.
- **Provenance and lineage**: every number traceable to a file and row.
- **Invariants as tests**: "categories sum to expenses", "net equals the sum
  of included signed amounts".
- **Staging tables**: preview/commit is the same pattern data warehouses use.
- **Record linkage / entity resolution**: blocking (only compare same-amount
  pairs), similarity features, thresholds, and human review. This is a whole
  research field; the matcher here is its simplest useful form.
- **Precision vs recall trade-offs**: a lower threshold finds more true
  duplicates but asks the user about more false ones.
- **Schema migrations**: why `create_all` is not enough once data exists.
- **Missing data vs zero**: NaN propagation in Pandas, and why `mean()`
  skipping NaN is what you want here.
- **Resampling and periods**: daily → ISO-week → calendar-month aggregation
  with `to_period`, and checking that the levels add up.
- **Robust statistics**: why the median describes a "typical" payment better
  than the mean when rent is one huge outlier.
- **Apportionment**: the largest-remainder method, and why rounding each
  share separately never adds up.
- **Dynamic programming over subsets**: an exact answer to an NP-hard
  problem when the input is small, and knowing when to fall back.
- **Evaluating honestly**: grouped vs random splits (does the model work on
  a merchant it has never seen?), chronological splits with purging,
  choosing on validation and reporting on test, bootstrap intervals, and
  why a strong simple baseline is the most important number in a table.
- **Property-based testing**: checking invariants (shares add up, balances
  sum to zero, plans settle everyone) on hundreds of random cases, and
  checking an optimiser against brute force.
- **Layered architecture**: pure core, thin I/O shells.
