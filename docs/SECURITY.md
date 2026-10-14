# Security and privacy

**MoneyOS has not had a security review. Do not expose it to a network or
store real financial data in it on a shared machine.**

## What is in place

| Control | Detail |
| --- | --- |
| Local-only by default | `moneyos serve` binds to `127.0.0.1`. It refuses any other host unless `MONEYOS_API_TOKEN` is set |
| Optional bearer token | When `MONEYOS_API_TOKEN` is set, every `/api/v1` route requires it (constant-time comparison). `/health` stays open and returns no personal data |
| Input validation | Pydantic models with length, pattern and precision limits; unknown fields rejected; CSV values validated per row |
| Upload limits | 5 MB per file; only the base name of the uploaded file name is kept |
| Safe database access | SQLAlchemy ORM and bound parameters only; no SQL built from strings |
| No secrets in code | Configuration via environment variables; `.env` files are git-ignored; `.env.example` holds no values |
| Logging | Access logs are off (query strings can contain merchant names). The application logs no transaction content |
| Errors | Error responses carry a short message, never a stack trace |
| Data minimisation | Raw CSV cells are stored only for rejected rows; discarding a preview deletes its staged rows |
| Sample/real separation | Databases are stamped with their data mode and refuse to be mixed |
| Repository hygiene | `data/*` and database files are git-ignored except the synthetic samples |

## Known limitations

- **No user accounts.** A single token protects the whole API. There is no
  per-user data isolation, so a multi-user deployment is not possible yet.
- **No encryption at rest.** The SQLite file is readable by anyone with
  access to your user account. Use full-disk encryption (BitLocker).
- **No TLS.** The server speaks plain HTTP. Over a network, put it behind a
  TLS-terminating proxy, or don't do it.
- **CSV formula injection.** `export_csv` writes descriptions as-is. A
  description starting with `=` could execute in Excel. Planned fix: prefix
  such cells.
- **Previews linger.** Previewed but never committed or discarded batches
  keep their staged rows.
- **Dependency vulnerabilities** are not yet scanned (`pip-audit` planned).

## Rules for integrations (Phase 9)

Never collect credentials for other payment apps, scrape behind logins,
bypass access controls, or initiate payments. Every integration needs
documented official support, explicit user consent, and a fallback to CSV.
See the integration checklist in the project brief.

## Reporting

This is a personal project; open an issue on the repository without
including any financial data.
