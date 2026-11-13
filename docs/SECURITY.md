# Security and privacy

**FinSight has not had a security review. Do not expose it to a network or
store real financial data in it on a shared machine.**

## What is in place

| Control | Detail |
| --- | --- |
| Accounts | Every `/api/v1` route except sign-up and sign-in requires a signed-in user. `/health` stays open and returns no personal data |
| Passwords | scrypt (n = 2¹⁴, r = 8, p = 1) with a random 16-byte salt per user, compared in constant time. At least 10 characters; no leading/trailing spaces, control or invisible characters |
| Sessions | A random 256-bit token is returned once; only its SHA-256 hash is stored, so a copy of the database cannot sign anyone in. Sessions expire after 7 days, end on sign-out, and all end when the password is changed |
| Sign-in failures | The same message for an unknown email and a wrong password. After 5 failures in 15 minutes the email is locked for that window (in memory; resets on restart) |
| Sign-up | The first account can always be created; later ones only with `MONEYOS_ALLOW_SIGNUP=true` |
| Per-user isolation | Enforced in the database layer, not in each feature: every ORM query on user-owned data is automatically restricted to the session's user, new rows are stamped with that user, writing another user's row raises an error, and a session that names no user cannot read user data at all (`db/tenancy.py`). Another user's record is reported as "not found", never "forbidden" |
| Web-app sessions | The web app signs in with `use_cookie: true`: the session token goes into an `httpOnly`, `SameSite=Strict` cookie limited to `/api` (and `Secure` over HTTPS), so page scripts can never read it and the response body carries no token. API clients keep using `Authorization: Bearer` |
| Cross-site requests | When a request is authenticated by the cookie, every method other than GET/HEAD/OPTIONS must also send `X-MoneyOS-CSRF: 1`. Another site cannot add that header to a cross-site request without a CORS preflight, which the server never approves (no CORS is configured). This backs up `SameSite=Strict` |
| Web-app headers | Pages are served with a Content-Security-Policy allowing only the app's own scripts, styles, images and API (`default-src 'self'`, no inline scripts, `frame-ancestors 'none'`), plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY`. Static files are served only from inside the build folder (path traversal is tested) |
| Open redirects | After sign-in the app follows `?next=` only to a path on the same site |
| Assistant | Read-only tools only (nothing can be written, paid or sent); runs in the user's own session; talks only to a model on this computer unless `MONEYOS_ASSISTANT_ALLOW_REMOTE=true`; questions limited to 500 characters and 10 earlier turns; every money figure in an answer checked against the tool results |
| Account deletion | `POST /api/v1/auth/delete-account` with the password and `confirm: true` permanently deletes the account and every record it owns |
| Local-only by default | `moneyos serve` binds to `127.0.0.1` and refuses other addresses unless `--allow-network` is given (see TLS below) |
| Input validation | Pydantic models with length, pattern and precision limits; unknown fields rejected; CSV values validated per row |
| Upload limits | 5 MB per file; only the base name of the uploaded file name is kept. Excel and PDF: at most 20,000 rows and 100 pages, 50 MB unpacked for an .xlsx, XML parsed with `defusedxml`. The file type is read from the content, never from the name |
| SMS backups | Parsed with `defusedxml`; up to 50 MB. Only transaction alerts are kept (sender, timestamp and the alert text, for traceability); OTPs and all other messages are discarded while reading and never stored |
| Gmail | Read-only scope (`gmail.readonly`); OAuth with PKCE and a state check; the sign-in reply is received only on `127.0.0.1`. Uses the user's own Google Cloud client. The refresh token is stored in `data/gmail/token.json` (git-ignored); `moneyos gmail disconnect` deletes it, and access can be revoked at https://myaccount.google.com/permissions. Attachment names are sanitised before saving |
| Statement passwords | Password-protected PDFs are refused; FinSight never asks for or stores a statement password |
| Safe database access | SQLAlchemy ORM and bound parameters only; no SQL built from user input |
| No secrets in code | Configuration via environment variables; `.env` files are git-ignored; `.env.example` holds no values |
| Logging | Access logs are off (query strings can contain merchant names). The application logs no transaction content, passwords or tokens |
| Errors | Error responses carry a short message, never a stack trace |
| Data minimisation | Only the uploaded rows are kept (the file itself is not stored). Original cells are kept per row for traceability (a FinSight requirement); discarding a preview deletes its staged rows |
| Sample/real separation | Databases are stamped with their data mode and refuse to be mixed |
| CSV formula injection | Exported text cells starting with `=`, `+`, `-`, `@`, tab or CR are prefixed with `'`; amounts are left untouched |
| No silent merges | Possible duplicates are never removed automatically; each merge is a user decision, audited and reversible |
| Repository hygiene | `data/*`, databases and trained models are git-ignored except the synthetic samples |

## Upgrading a database from before accounts

A database created before v0.8 keeps its data: the upgrade creates an
account `owner@localhost` **with no password** (it cannot sign in) and makes
it the owner of every existing record. Set its password locally:

```powershell
.\.venv\Scripts\moneyos.exe user set-password owner@localhost
```

Only someone with access to your machine can do this.

## Known limitations

- **No TLS.** The server speaks plain HTTP, so passwords and tokens would
  cross a network unencrypted. `--allow-network` exists only for use behind
  a TLS-terminating proxy.
- **No encryption at rest.** The SQLite file is readable by anyone with
  access to your user account. Use full-disk encryption (BitLocker).
- **Lockouts are per process and in memory.** Restarting the server clears
  them, and several server processes would not share them.
- **Styles allow `'unsafe-inline'`** in the CSP (the chart library sets inline
  styles). Scripts do not.
- **The web app has no automatic sign-out on inactivity**; sessions last 7
  days unless you sign out.
- **No email verification or password reset by email.** Passwords are reset
  with the `moneyos user set-password` command on the machine.
- **Previews linger.** Previewed but never committed or discarded batches
  keep their staged rows.
- **Dependency scans are manual.** On 2026-11-13 `npm audit` found nothing and
  `pip-audit` found one issue, in `certifi` (pulled in by test and tooling
  packages), fixed by upgrading it. Run both before each release (see
  DEVELOPMENT.md); they only know about already-reported vulnerabilities.
- **The assistant can be misled.** Text in transaction descriptions
  reaches the model, and a description written to manipulate it could make
  an answer wrong (the tools are read-only, so it cannot do more). Figures it
  invents are flagged by the grounding check, but wording is not checked.
- **The Gmail token is a plain file.** Anyone who can read your user
  folder can use it to read your mail until it expires or is revoked. Google
  grants read access to the whole mailbox; FinSight only searches for bank
  emails, but that is its choice, not a limit Google enforces.
- **PDF parsing is complex.** `pdfminer` (via `pdfplumber`) parses
  untrusted PDFs in the server process. The limits above bound the work,
  but a parser bug could still be triggered by a crafted file; the server
  only listens locally by default.
- **PostgreSQL is untested.** The schema and migrations are written to be
  portable, but have only been run on SQLite.

## Rules for integrations (Phase 9)

Never collect credentials for other payment apps, scrape behind logins,
bypass access controls, or initiate payments. Every integration needs
documented official support, explicit user consent, and a fallback to CSV.

## Reporting

This is a personal project; open an issue on the repository without
including any financial data.
