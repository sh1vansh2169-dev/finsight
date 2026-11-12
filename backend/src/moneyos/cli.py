"""Command line entry point: ``moneyos`` or ``python -m moneyos``."""

from __future__ import annotations

import argparse
import glob
import ipaddress
import json
import sys
from pathlib import Path

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

    rep = commands.add_parser("report", help="write a Markdown analytics report with charts")
    rep.add_argument("--out", default="data/reports/latest", help="output folder (default: data/reports/latest)")
    rep.add_argument("--sample", action="store_true", help="report on the synthetic sample database")
    rep.add_argument("--currency", help="needed when the ledger has more than one currency")

    ml = commands.add_parser("ml", help="run a machine-learning experiment")
    ml.add_argument("experiment", choices=["categorization", "forecasting", "anomaly", "clustering"])
    ml.add_argument("--out", help="results folder (default: data/experiments/<experiment>)")
    ml.add_argument("--save-model", default="data/models", help="where to save the selected model ('' to skip)")

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
            if _seed_sample_majra(session):
                print("Money Majra: sample trip with Sam and Ria, and a loan to a friend linked to a bank payment")
    finally:
        factory.kw["bind"].dispose()
    print(f"\n{synthetic.SAMPLE_MARKER}\nStored in {args.database}. Serve it with: moneyos serve --sample")
    return 0


def _cmd_report(args) -> int:
    from moneyos.db.session import DataModeError, init_db
    from moneyos.services.errors import InvalidRequestError
    from moneyos.services.report import write_report

    settings = Settings.from_env(data_mode=DataMode.SAMPLE if args.sample else None)
    try:
        factory = init_db(settings.database_url, settings.data_mode)
    except DataModeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        with factory() as session:
            path = write_report(
                session, Path(args.out), currency=args.currency, sample=settings.data_mode == DataMode.SAMPLE
            )
    except InvalidRequestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        factory.kw["bind"].dispose()
    print(f"Report written to {path}")
    return 0


def _seed_sample_majra(session) -> bool:
    """Synthetic Money Majra data. Skipped if the sample already has some."""
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import func, select

    from moneyos.db.tables import MajraPerson, TransactionRecord
    from moneyos.domain.majra import SplitMethod
    from moneyos.services import majra

    if session.scalar(select(func.count()).select_from(MajraPerson)) > 1:
        return False
    you = majra.me(session)
    sam, ria, friend = (majra.add_person(session, n) for n in ("Sam", "Ria", "Friend 7731"))
    trip = majra.create_group(session, "Goa trip (sample)", "INR", [sam.id, ria.id])
    everyone = [(you.id, None), (sam.id, None), (ria.id, None)]
    majra.add_expense(session, trip.id, description="Beach shack dinner", occurred_on=date(2026, 3, 6),
                      amount=Decimal("2400"), paid_by_id=you.id, method=SplitMethod.EQUAL, participants=everyone)
    majra.add_expense(session, trip.id, description="Scooter rental", occurred_on=date(2026, 3, 7),
                      amount=Decimal("1500"), paid_by_id=sam.id, method=SplitMethod.SHARES,
                      participants=[(you.id, Decimal(2)), (sam.id, Decimal(2)), (ria.id, Decimal(1))])
    majra.add_payment(session, trip.id, payer_id=ria.id, receiver_id=you.id, amount=Decimal("500"),
                      occurred_on=date(2026, 3, 12), description="Ria paid back part of dinner")
    # The synthetic statement has an unexplained UPI payment of 1,500 on 9 March:
    # record it as a loan and link it, which turns it from "unknown" into "lent".
    upi = session.scalar(
        select(TransactionRecord).where(
            func.lower(TransactionRecord.description) == "upi/p2p/friend-7731",
            TransactionRecord.amount_minor == 150000,
        )
    )
    majra.add_loan(session, person_id=friend.id, lent=True, amount=Decimal("1500"), currency="INR",
                   occurred_on=date(2026, 3, 9), description="Lent to a friend",
                   transaction_id=upi.id if upi else None)
    return True


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
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "ml":
        from moneyos.ml import experiments

        out = Path(args.out or f"data/experiments/{args.experiment}")
        if args.experiment == "categorization":
            results = experiments.run_categorization(
                out, save_model_to=Path(args.save_model) if args.save_model else None
            )
            print(f"Selected {results['selected']}; results in {out / 'report.md'}")
        elif args.experiment == "clustering":
            experiments.run_clustering(out)
            print(f"Results in {out / 'report.md'}")
        elif args.experiment == "anomaly":
            results = experiments.run_anomaly(out)
            print(f"Chosen {results['chosen']}; results in {out / 'report.md'}")
        else:
            results = experiments.run_forecasting(out)
            chosen = {h: r["chosen_on_calibration"] for h, r in results["horizons"].items()}
            print(f"Chosen per horizon: {chosen}; results in {out / 'report.md'}")
        return 0
    return _cmd_serve(args)

