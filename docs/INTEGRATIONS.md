# Integrations research (Phase 9)

Question: can FinSight fetch a user's transactions automatically instead of
asking them to download statements? Researched 2026-11-13. This is a
research note, not legal advice; check the primary sources before relying on it.

## What FinSight does today

Statement files the user downloads from their own bank, card or payment
app: CSV, Excel (.xlsx) and text-based PDF. The user stays in control of
what is imported, every file goes through the same preview-then-commit
step, and FinSight never holds a bank login. See
[ARCHITECTURE.md](ARCHITECTURE.md#statement-formats).

The statement inbox removes the upload step: point your browser's or
phone-sync tool's download folder at it and statements appear in
FinSight for review by themselves. Your UPI payments are also in your bank
statement, whichever app made them.

On Android, bank and UPI alert SMS can be imported from an SMS backup
file, with no access to the phone or any account (see ARCHITECTURE.md).

Bank statement and alert emails can be fetched from Gmail with the
user's own read-only Google sign-in (see DEVELOPMENT.md). This uses
Google's official API and consent screen, not the bank's systems.

## India's Account Aggregator (AA) framework

The authorised way to share financial data between institutions in India.
An Account Aggregator is an RBI-licensed NBFC that moves encrypted data from
a **Financial Information Provider** (FIP: banks and other holders of your
data) to a **Financial Information User** (FIU: the party that wants it),
only with the customer's explicit, revocable consent.

**Can FinSight be an FIU? No.** The RBI directions define a financial
information user as an entity *registered with and regulated by a financial
sector regulator* (the RBI, SEBI, IRDAI or PFRDA). A personal, open-source
app run by an individual is none of these. Being an FIU means becoming (or
partnering with) a regulated institution, with the compliance that brings.

**Could the user's own AA app help?** AA apps let a customer see and manage
consents, and the directions allow an AA to present information to the
customer. Whether a given AA app lets you *export* that data in a usable
file is up to each AA; it is not a standard feature we can build on. If one
does, FinSight can import that file like any other statement.

**Status of details I could not confirm from primary sources** (from
secondary sources only, so treat as unverified):

- Reports that the RBI recognised Sahamati as the AA ecosystem's
  self-regulatory organisation in June 2026.
- Reports that ReBIT published new interoperability API specifications in
  October 2026 with an adoption deadline of 1 December 2026.
- Newer RBI Account Aggregator Directions (2025) are listed on the RBI site;
  I did not confirm whether they replace the 2016 Master Direction. The FIU
  definition reads the same in both.

## What FinSight will not do

These follow from the project rules in [SECURITY.md](SECURITY.md#rules-for-integrations-phase-9):

- **No screen scraping and no stored bank or payment-app credentials.**
  Logging in as the user to a bank or a UPI app breaks those services'
  terms, puts the user's credentials at risk, and is exactly the "collect
  credentials for other payment apps" the project forbids.
- **No unofficial APIs** of payment apps.
- **No statement passwords.** Password-protected PDFs are refused; the user
  removes the password or downloads CSV/Excel instead.
- **Never initiates payments.**

## Decision

Keep file import as the way data enters FinSight. Revisit automatic fetching
only if FinSight is ever run by a regulated entity, or if a provider offers an
official, consent-based export to individuals.

## Sources

- RBI, Master Direction: Non-Banking Financial Company - Account Aggregator
  (Reserve Bank) Directions, 2016: https://www.rbi.org.in/scripts/BS_ViewMasDirections.aspx?id=10598
- RBI Master Directions listing (includes the 2025 AA Directions): https://www.rbi.org.in/scripts/BS_ViewMasDirections.aspx?id=12936
- Department of Financial Services, Account Aggregator framework: https://financialservices.gov.in/account-aggregator-framework
- Sahamati (industry body): https://sahamati.org.in/rebit-aa-client-standards/
- Secondary, unverified for the dated claims above: https://ecorpit.com/account-aggregator-integration-fintech-builders-2026/
