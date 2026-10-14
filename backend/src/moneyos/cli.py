"""Command line entry point: ``moneyos`` or ``python -m moneyos``."""

from __future__ import annotations

import argparse
import glob
import ipaddress
import json
import sys

from moneyos.config import DEFAULT_DATABASE_URLS, DataMode, Settings
from moneyos.domain import report, synthetic
from moneyos.domain.classify import RulesError, load_rules
from moneyos.domain.importer import SchemaError
from moneyos.domain.pipeline import run_pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moneyos", description="MoneyOS personal finance toolkit")
    commands = parser.add_subparsers(dest="command", required=True)

    imp = commands.add_parser("import", help="analyse statement CSV files without saving anything")
    imp.add_argument("files", nargs="+", help="CSV files, oldest first")
    imp.add_argument("--account", help="account name for files without an account column (default: file name)")
    imp.add_argument("--currency", default="INR", help="currency for files without a currency column (default: INR)")
    imp.add_argument("--month-first", action="store_true", help="read 03/04/2026 as March 4 instead of 3 April")
    imp.add_argument("--json", action="store_true", help="print the full result as JSON")
    imp.add_argument("--export", metavar="PATH", help="also write the cleaned transactions to a CSV file")

    sample = commands.add_parser("sample", help="write synthetic statement CSV files")
    sample.add_argument("directory")
    sample.add_argument("--seed", type=int, default=2026)

    seed = commands.add_parser("seed-sample", help="load synthetic data into the separate sample database")
    seed.add_argument("--database", default=DEFAULT_DATABASE_URLS[DataMode.SAMPLE], help="SQLAlchemy URL")
    seed.add_argument("--seed", type=int, default=2026)

    serve = commands.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--sample", action="store_true", help="serve the synthetic sample database")
    return parser


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _expand(patterns: list[str]) -> list[str]:
    """Expand wildcards ourselves: Windows shells pass ``*.csv`` through literally."""
    files = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) if glob.has_magic(pattern) else []
        files.extend(matches or [pattern])
    return files


def _cmd_import(args) -> int:
    try:
        result = run_pipeline(
            _expand(args.files),
            account=args.account,
            default_currency=args.currency,
            day_first=not args.month_first,
        )
    except (SchemaError, RulesError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.export:
        report.export_csv(result, args.export)
    if args.json:
        print(json.dumps(report.to_dict(result), indent=2))
    else:
        print(report.render_text(result))
    return 0


def _cmd_seed_sample(args) -> int:
    from moneyos.db.session import DataModeError, init_db
    from moneyos.services import imports, review

    try:
        factory = init_db(args.database, DataMode.SAMPLE)
    except DataModeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    dataset = synthetic.generate(args.seed)
    try:
        rules = load_rules(Settings.from_env().rules_file)
        with factory() as session:
            files = {**dataset.files, dataset.payapp.name: dataset.payapp.text}
            for name, text in files.items():
                account = {
                    dataset.payapp.name: synthetic.PAYAPP_ACCOUNT,
                    "sample_card_4321_2026_q1.csv": synthetic.CARD_ACCOUNT,
                }.get(name)
                batch = imports.preview_import(
                    session,
                    filename=name,
                    content=text.encode("utf-8"),
                    options=imports.ImportOptions(account=account),
                    rules=rules,
                )
                batch = imports.commit_import(session, batch.id)
                print(
                    f"{name}: {batch.inserted_rows} added, {batch.duplicate_rows} duplicates, "
                    f"{batch.rejected_rows} rejected"
                )
            print(f"Possible duplicates waiting for review: {review.count_open(session)}")
    finally:
        factory.kw["bind"].dispose()
    print(f"\n{synthetic.SAMPLE_MARKER}\nStored in {args.database}. Serve it with: moneyos serve --sample")
    return 0


def _cmd_serve(args) -> int:
    import uvicorn

    from moneyos.api.app import create_app
    from moneyos.db.session import DataModeError

    settings = Settings.from_env(data_mode=DataMode.SAMPLE if args.sample else None)
    if not _is_loopback(args.host) and settings.api_token is None:
        print(
            "error: refusing to listen on a non-loopback address without MONEYOS_API_TOKEN set",
            file=sys.stderr,
        )
        return 2
    try:
        app = create_app(settings)
    except (DataModeError, RulesError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    label = "SAMPLE DATA" if settings.data_mode == DataMode.SAMPLE else "real data"
    print(f"MoneyOS API ({label}) on http://{args.host}:{args.port}  docs: /docs")
    # access_log is off: URLs can carry filter values such as merchant names.
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    # Statement text can contain characters the Windows console cannot encode.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    if args.command == "sample":
        for path in synthetic.generate(args.seed).write(args.directory):
            print(path)
        return 0
    if args.command == "import":
        return _cmd_import(args)
    if args.command == "seed-sample":
        return _cmd_seed_sample(args)
    return _cmd_serve(args)

