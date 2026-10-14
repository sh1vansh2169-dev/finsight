"""Command line entry point: ``python -m moneyos`` or ``moneyos``."""

from __future__ import annotations

import argparse
import json
import sys

from moneyos import report, synthetic
from moneyos.importer import SchemaError
from moneyos.pipeline import run_pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moneyos", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    imp = commands.add_parser("import", help="import statement CSV files and print a summary")
    imp.add_argument("files", nargs="+", help="CSV files, oldest first")
    imp.add_argument("--account", help="account name for files without an account column (default: file name)")
    imp.add_argument("--currency", default="INR", help="currency for files without a currency column (default: INR)")
    imp.add_argument("--month-first", action="store_true", help="read 03/04/2026 as March 4 instead of 3 April")
    imp.add_argument("--json", action="store_true", help="print the full result as JSON")
    imp.add_argument("--export", metavar="PATH", help="also write the cleaned transactions to a CSV file")

    sample = commands.add_parser("sample", help="write synthetic statement files for trying things out")
    sample.add_argument("directory")
    sample.add_argument("--seed", type=int, default=2026)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    # Statement text can contain characters the Windows console cannot encode.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    if args.command == "sample":
        for path in synthetic.generate(args.seed).write(args.directory):
            print(path)
        return 0

    try:
        result = run_pipeline(
            args.files,
            account=args.account,
            default_currency=args.currency,
            day_first=not args.month_first,
        )
    except (SchemaError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.export:
        report.export_csv(result, args.export)
    if args.json:
        print(json.dumps(report.to_dict(result), indent=2))
    else:
        print(report.render_text(result))
    return 0
