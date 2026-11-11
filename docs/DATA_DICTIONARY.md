# Data dictionary

Source of truth: `backend/src/moneyos/db/tables.py` and
`backend/src/moneyos/domain/models.py`. All timestamps are timezone-aware
UTC. Money is a positive integer in minor units plus a direction.

## Enums

| Enum | Values | Meaning |
| --- | --- | --- |
| `direction` | `debit`, `credit` | Money out / money in |
| `txn_type` | `expense`, `income`, `transfer`, `refund`, `lent`, `borrowed`, `repayment_received`, `repayment_made`, `reversal`, `unknown` | Economic meaning. `transfer` = between your own accounts |
| `status` | `posted`, `pending`, `failed`, `reversed`, `unknown` | As stated by the source; `unknown` when it did not say |
| `basis` | `source`, `user`, `rule`, `model`, `none` | How a field's value was decided |
| import row `outcome` | `new`, `suspected`, `duplicate`, `rejected` | Result of validation and duplicate checks |
| import batch `status` | `previewed`, `committed`, `discarded` | Import lifecycle |

Allowed type/direction pairs: `expense`, `lent`, `repayment_made` are
debits; `income`, `refund`, `borrowed`, `repayment_received` are credits;
`transfer`, `reversal`, `unknown` can be either.

## `transactions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int | Primary key |
| `account_id` | int → `accounts.id` | |
| `occurred_on` | date | Transaction date from the source (no time-of-day yet) |
| `description` | text(500) | Cleaned: whitespace collapsed, Unicode-normalised |
| `raw_description` | text(500) | As it appeared in the source |
| `amount_minor` | bigint | Positive. 12000 = ₹120.00 |
| `direction` | `debit`/`credit` | |
| `currency` | char(3) | ISO 4217 |
| `txn_type`, `type_basis` | enum, basis | |
| `category`, `category_basis` | text(100), basis | `Uncategorized` when unknown |
| `status` | enum | |
| `external_id` | text(100), nullable | Bank reference / transaction ID. Unique per account when present |
| `source` | `csv_import` / `manual` | |
| `import_batch_id` | int → `import_batches.id`, nullable | Provenance |
| `source_file`, `source_row` | nullable | Provenance: file name and 1-based line number |
| `duplicate_of_id` | int → `transactions.id`, nullable | Set when the user confirms this record is the same payment as another. Such records are kept for provenance but hidden from listings (unless `include_duplicates=true`) and always excluded from totals |
| `created_at`, `updated_at` | UTC datetime | |

## `match_candidates`

Pairs the matcher thinks may be the same payment. Only the user resolves them.

| Column | Notes |
| --- | --- |
| `transaction_a_id`, `transaction_b_id` | The pair; `a < b`, unique together |
| `score` | 0–100 from hand-chosen weights. Not a probability |
| `reasons` | JSON list of plain-language reasons shown to the user |
| `status` | `open`, `duplicate` (same payment), `distinct` (different payments, never re-proposed), `superseded` (closed because one record was marked a duplicate in another pair; reopened automatically if that decision is undone) |
| `kept_id` | For `duplicate`: the record that was kept |
| `created_at`, `resolved_at` | UTC |

## `budgets`

| Column | Notes |
| --- | --- |
| `category`, `currency` | Unique together. Category names match `transactions.category` exactly |
| `limit_minor` | Monthly limit in minor units, positive |
| `created_at`, `updated_at` | UTC |

Spending against a budget counts `expense` debits in that category and
currency, excluding failed payments and confirmed duplicates.

## `alembic_version`

Current schema revision, managed by Alembic. `0001` is the v0.2 schema,
`0002` adds duplicate review, `0003` adds budgets.

## Analytics outputs (not stored)

| Field | Meaning |
| --- | --- |
| `coverage` | Share (0–1) of statement-backed accounts whose imported statements cover a period, averaged over its days. Accounts with only manual entries are not counted |
| amounts in a series point | `null` when `coverage` is 0: unknown, not zero |
| `projected_month_total` | Estimate: spending so far scaled to the whole month; only from day 7 of the current month |
| `share` (by category) | Category spending / all spending in the range |

## `accounts`

| Column | Notes |
| --- | --- |
| `name` | Unique. From the file's account column, the import option, or the file name |
| `kind` | `other` for now (bank, card, wallet, cash planned) |
| `currency` | Currency of the first transaction seen |

## `import_batches`

One row per uploaded file. Counts: `total_rows` (data rows, including blank
ones), `blank_rows`, `rejected_rows`, `new_rows`, `suspected_rows`,
`duplicate_rows`, `inserted_rows` (set on commit). `file_sha256` detects
re-uploads of the identical file. `account_override`, `default_currency`
and `day_first` record the options used.

## `import_rows`

Staged rows. `raw` (JSON) holds the original cells of every imported row,
so each ledger entry can be traced back to exactly what the file said and
rows can be reprocessed if the rules improve. `payload` (JSON) holds the
normalised transaction for valid rows.
`reason` explains rejections and duplicate decisions. Rows are deleted when
a preview is discarded.

## `audit_events`

Append-only. Actions: `import_committed`, `import_discarded`,
`transaction_created`, `transaction_corrected` (with `details.before` and
`details.after`), and for duplicate review `match_marked_duplicate`,
`match_marked_distinct`, `match_reopened` (on `match_candidate`) plus
`marked_duplicate` / `unmarked_duplicate` (on the affected `transaction`).

## `app_meta`

Key/value. `data_mode` = `real` or `sample` (see ARCHITECTURE.md).

## Supported CSV columns

Header matching ignores case and punctuation. Required: a date, a
description, and either an amount or debit/credit columns.

| Field | Accepted headers |
| --- | --- |
| date | date, transaction date, txn date, posting date, posted date, value date |
| description | description, narration, details, memo, payee, particulars, merchant, counterparty, paid to / received from |
| amount | amount, amount (INR), amount (USD), transaction amount |
| debit / credit | debit, withdrawal, money out, paid out / credit, deposit, money in, paid in |
| direction | type, dr/cr, cr/dr, debit/credit (values DR, CR, debit, credit) |
| status | status, transaction status, txn status |
| others | currency, account, category, reference / ref no / transaction id / UTR / UPI ref no |

Dates may carry a time of day (`07 Feb 2026, 1:45 PM`, `2026-02-07T13:45`);
the time is currently discarded.

Amounts may include ₹ $ € £, Rs., INR, Western or Indian digit grouping,
and negatives as `-`, `(x)`, trailing `-`, or `DR`. Decimal commas
(`1.234,56`) are rejected rather than guessed. Numeric dates are day-first
unless `day_first=false`, with no per-row fallback.
