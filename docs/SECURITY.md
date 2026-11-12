# Security and privacy

**MoneyOS has not had a security review. Do not expose it to a network or
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
| Account deletion | `POST /api/v1/auth/delete-account` with the password and `confirm: true` permanently deletes the account and every record it owns |
| Local-only by default | `moneyos serve` binds to `127.0.0.1` and refuses other addresses unless `--allow-network` is given (see TLS below) |
| Input validation | Pydantic models with length, pattern and precision limits; unknown fields rejected; CSV values validated per row |
| Upload limits | 5 MB per file; only the base name of the uploaded file name is kept |
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
- **Tokens in the browser.** The web app (Phase 8) will need to store the
  session token; this needs care against cross-site scripting.
- **No email verification or password reset by email.** Passwords are reset
  with the `moneyos user set-password` command on the machine.
- **Previews linger.** Previewed but never committed or discarded batches
  keep their staged rows.
- **Dependency vulnerabilities** are not yet scanned (`pip-audit` planned).
- **PostgreSQL is untested.** The schema and migrations are written to be
  portable, but have only been run on SQLite.

## Rules for integrations (Phase 9)

Never collect credentials for other payment apps, scrape behind logins,
bypass access controls, or initiate payments. Every integration needs
documented official support, explicit user consent, and a fallback to CSV.

## Reporting

This is a personal project; open an issue on the repository without
including any financial data.
