"""Command line entry point: ``moneyos`` or ``python -m moneyos``."""

from __future__ import annotations

import argparse
import glob
import ipaddress
import json
import sys
from pathlib import Path

from sqlalchemy import select

from moneyos.config import DEFAULT_DATABASE_URLS, DataMode, Settings
from moneyos.db.tenancy import system_session, user_session
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
    rep.add_argument("--email", help="whose data to report on (default: the only account)")

    user = commands.add_parser("user", help="manage accounts")
    user.add_argument("action", choices=["create", "set-password", "list"])
    user.add_argument("email", nargs="?")
    user.add_argument("--sample", action="store_true", help="the synthetic sample database")
    user.add_argument("--password-stdin", action="store_true", help="read the password from standard input")

    ml = commands.add_parser("ml", help="run a machine-learning experiment")
    ml.add_argument("experiment", choices=["categorization", "forecasting", "anomaly", "clustering"])
    ml.add_argument("--out", help="results folder (default: data/experiments/<experiment>)")
    ml.add_argument("--save-model", default="data/models", help="where to save the selected model ('' to skip)")

    serve = commands.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--sample", action="store_true", help="serve the synthetic sample database")
    serve.add_argument("--allow-network", action="store_true",
                       help="listen on a non-local address (plain HTTP: put it behind TLS first)")
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
        user_id, message = _sample_account(factory)
        rules = load_rules(Settings.from_env().rules_file)
        with user_session(factory, user_id) as session:
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
            confirmed = _seed_sample_commitments(session)
            if confirmed:
                print(f"Commitments confirmed from detected recurring payments: {', '.join(confirmed)}")
    finally:
        factory.kw["bind"].dispose()
    print(f"\n{synthetic.SAMPLE_MARKER}\nStored in {args.database}. Serve it with: moneyos serve --sample")
    print(message)
    return 0


SAMPLE_EMAIL = "sample@moneyos.local"


def _sample_account(factory) -> tuple[int, str]:
    """The account that owns the sample data: the only one if there is one, else a new one."""
    import secrets

    from moneyos.db.tables import User
    from moneyos.services import auth

    with system_session(factory) as session:
        users = list(session.scalars(select(User).order_by(User.id)))
        if len(users) == 1:
            user = users[0]
            if user.password_hash is None:
                return user.id, (f"Sign in as {user.email} after setting a password: "
                                 f"moneyos user set-password {user.email} --sample")
            return user.id, f"Sign in as {user.email}."
        existing = next((u for u in users if u.email == SAMPLE_EMAIL), None)
        if existing:
            return existing.id, f"Sign in as {SAMPLE_EMAIL}."
        password = secrets.token_urlsafe(12)
        user = auth.create_user(session, SAMPLE_EMAIL, password)
        return user.id, (f"Sign in as {SAMPLE_EMAIL} with password {password}\n"
                         "(shown once; change it with: moneyos user set-password sample@moneyos.local --sample)")


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
        user_id = _pick_user(factory, args.email)
        with user_session(factory, user_id) as session:
            path = write_report(
                session, Path(args.out), currency=args.currency, sample=settings.data_mode == DataMode.SAMPLE
            )
    except (InvalidRequestError, LookupError) as error:
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


def _seed_sample_commitments(session) -> list[str]:
    """Confirm the sample's obvious recurring payments, as a user would."""
    from moneyos.services import commitments, planning

    as_of = planning.default_as_of(session)
    existing = {c.merchant_key for c in commitments.list_commitments(session)}
    confirmed = []
    for key in ("acme corp salary", "rent greenview apts", "city power electricity bill", "fibernet broadband",
                "streamflix subscription"):
        if key not in existing and any(s.key == key for s in commitments.detected(session, "INR", as_of)):
            commitments.confirm_detected(session, key, "INR", as_of)
            confirmed.append(key)
    return confirmed


def _pick_user(factory, email: str | None) -> int:
    from moneyos.db.tables import User

    with system_session(factory) as session:
        if email:
            user = session.scalar(select(User).where(User.email == email.strip().lower()))
            if user is None:
                raise LookupError(f"no account for {email}")
            return user.id
        users = list(session.scalars(select(User)))
        if len(users) != 1:
            raise LookupError("there is more than one account (or none); choose one with --email")
        return users[0].id


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        # Windows shells may prefix piped text with a byte-order mark and end it with \r\n.
        return sys.stdin.readline().lstrip("﻿").rstrip("\r\n")
    import getpass

    first = getpass.getpass("New password: ")
    if getpass.getpass("Again: ") != first:
        raise ValueError("the passwords do not match")
    return first


def _cmd_user(args) -> int:
    from moneyos.db.session import DataModeError, init_db
    from moneyos.db.tables import User
    from moneyos.services import auth
    from moneyos.services.errors import ConflictError, InvalidRequestError

    settings = Settings.from_env(data_mode=DataMode.SAMPLE if args.sample else None)
    try:
        factory = init_db(settings.database_url, settings.data_mode)
    except DataModeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        with system_session(factory) as session:
            if args.action == "list":
                for u in session.scalars(select(User).order_by(User.id)):
                    print(f"{u.email}{'' if u.password_hash else '  (no password set)'}")
                return 0
            if not args.email:
                print("error: an email is required", file=sys.stderr)
                return 2
            password = _read_password(args.password_stdin)
            if args.action == "create":
                auth.create_user(session, args.email, password)
                print(f"Created {args.email.strip().lower()}")
            else:
                auth.set_password(session, args.email, password)
                print(f"Password set for {args.email.strip().lower()}; existing sign-ins were ended")
        return 0
    except (InvalidRequestError, ConflictError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        factory.kw["bind"].dispose()


def _cmd_serve(args) -> int:
    import uvicorn

    from moneyos.api.app import create_app
    from moneyos.db.session import DataModeError

    settings = Settings.from_env(data_mode=DataMode.SAMPLE if args.sample else None)
    if not _is_loopback(args.host) and not args.allow_network:
        print(
            "error: refusing to listen on a non-local address. MoneyOS speaks plain HTTP, so passwords would "
            "cross the network unencrypted. Put it behind a TLS proxy, then pass --allow-network.",
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
    if args.command == "user":
        return _cmd_user(args)
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

