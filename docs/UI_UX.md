# UI/UX requirements

**Status: planned for Phase 8.** Nothing in this document is built yet. The
backend phases (3–7) come first so every screen has real data behind it.
Recorded 2026-10-14 from the project owner's brief.

## Character

Friendly, human-centred, for everyday users: approachable, trustworthy,
calm, easy to understand. Not a complicated banking dashboard and not a
developer analytics tool.

## Visual direction

- Light-first: warm cream or white background.
- Sage green primary accent, restrained blue accents.
- Rounded cards, clear typography, subtle borders, generous spacing.
- Simple icons, restrained animation.
- Optional dark theme.
- Accessible, readable, responsive.

## Navigation

1. Home
2. Transactions
3. Money Majra
4. Insights
5. Profile

## Screens

| Screen | Content | Backend it depends on |
| --- | --- | --- |
| Home | Monthly spending, recorded income, budget progress, recent transactions, one or two useful insights | Summaries (done), budgets (Phase 4) |
| Transactions | Searchable list, category filters, source filters, import controls, simple category corrections, duplicate review | Ledger, imports, corrections (done); duplicate review (Phase 3) |
| Money Majra | Lending, borrowing, shared expenses, repayments, settlements, made easy to understand | Phase 5 |
| Insights | Spending patterns, expenditure forecasts, unusual transactions, budget suggestions, with simple explanations and clear charts | Phases 4, 6 |
| Assistant | Natural-language questions answered from verified app data, with uncertainty shown for predictions | Phase 10 |
| Profile | Settings, theme, data mode, data sources | Partly available |

## UX principles

- Never overwhelm with too many metrics.
- No financial jargon in everyday text.
- Never shame users for their spending.
- Clearly separate actual records from predictions and estimates.
- Explain important alerts in plain words.
- Make errors, missing data and uncertain transaction matches visible.
- Show sample data only when it is clearly labelled as demonstration data.
  (The API's `/health` and `/summary` responses carry `sample_data` for this.)
- Every button does something meaningful; no dead controls.
- Functional, tested screens over decorative mockups.

## Engineering approach

React + TypeScript components styled with Tailwind (decided 2026-11-11,
replacing Flutter) and one consistent design system (colour,
type, spacing and shape tokens). Build incrementally, test at phone,
tablet and desktop sizes, and connect each screen to the real backend as
its module becomes available.

## Backend notes for the UI (collected as phases land)

- Money arrives as decimal strings ("-120.00"); never convert to a JavaScript `Number` for
  arithmetic.
- Every transaction carries `type_basis` / `category_basis`: show inferred
  values (basis `rule`) differently from confirmed ones (`source`, `user`).
- Summaries include `warnings` and a `note` that totals are recorded totals,
  not a bank balance.
- Home screen data: `GET /api/v1/dashboard?month=YYYY-MM`. Amounts in
  `daily`/`monthly` are `null` for periods no statement covers: draw those
  as "unknown" (the report uses a grey band), never as a dip to zero. Show
  `coverage` below 100% as "partly covered". `not_yet_available` lists
  sections to show as "coming later", not as empty.
- Money Majra: `/api/v1/majra/...`. Show balances as "Sam owes you" /
  "You owe Ria" rather than signed numbers. The settlement list is a
  *suggestion* with the fewest payments. Show the `note` that money owed to
  you is expected, not guaranteed. A 409 on a payment means "this looks
  like a repeat": offer "Yes, it's a second payment" (`confirm_duplicate`).
  Voided entries stay visible, struck through.
- Budget `message` text is already neutral and plain-language; `state` is
  `on_track` / `close` / `over`. Pair state colours with an icon and label.
- Duplicate review (`/api/v1/review/duplicates`) returns each pair with a
  score, `confidence` and plain-language `reasons`. The two choices map to
  "Same payment: keep this one" and "Different payments". Show the pending
  count wherever totals appear (`open_duplicate_reviews` on `/summary`), and
  offer undo (`/reopen`).
- Category suggestions (`/api/v1/ml/category-suggestions`): show as "Looks
  like Health?" with one-tap accept (PATCH the transaction) and the two
  alternatives. Never show model output as fact; values with basis `model`
  need the same "inferred" styling as `rule`.
- Unusual payments (`/api/v1/ml/unusual`): show the `reason` text as is,
  with "This was expected" (dismiss). Do not use warning red or the word
  "fraud"; this is information, not an alarm.
