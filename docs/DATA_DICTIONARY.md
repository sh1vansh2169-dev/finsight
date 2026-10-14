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
| `created_at`, `updated_at` | UTC datetime | |

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

Staged rows. `payload` (JSON) holds the normalised transaction for valid
rows; `raw` (JSON) holds the original cells for rejected rows only.
`reason` explains rejections and duplicate decisions. Rows are deleted when
a preview is discarded.

## `audit_events`

Append-only. `action` is one of `import_committed`, `import_discarded`,
`transaction_created`, `transaction_corrected`. Corrections store
`details.before` and `details.after`.

## `app_meta`

Key/value. `data_mode` = `real` or `sample` (see ARCHITECTURE.md).

## Supported CSV columns

Header matching ignores case and punctuation. Required: a date, a
description, and either an amount or debit/credit columns.

| Field | Accepted headers |
| --- | --- |
| date | date, transaction date, txn date, posting date, posted date, value date |
| description | description, narration, details, memo, payee, particulars, merchant |
| amount | amount, amount (INR), amount (USD), transaction amount |
| debit / credit | debit, withdrawal, money out, paid out / credit, deposit, money in, paid in |
| direction | type, dr/cr, cr/dr, debit/credit (values DR, CR, debit, credit) |
| status | status, transaction status, txn status |
| others | currency, account, category, reference / ref no / transaction id / UTR |

Amounts may include ₹ $ € £, Rs., INR, Western or Indian digit grouping,
and negatives as `-`, `(x)`, trailing `-`, or `DR`. Decimal commas
(`1.234,56`) are rejected rather than guessed. Numeric dates are day-first
unless `day_first=false`, with no per-row fallback.
