"""End-to-end tests of the file pipeline against synthetic ground truth."""

import csv
import json
from decimal import Decimal

import pytest

from moneyos.cli import main
from moneyos.domain import report, synthetic
from moneyos.domain.models import TxnType
from moneyos.domain.pipeline import run_pipeline


@pytest.fixture
def paths(dataset, tmp_path):
    return dataset.write(tmp_path)


def test_generator_is_deterministic(dataset):
    assert synthetic.generate(seed=2026) == dataset
    assert synthetic.generate(seed=7).files != dataset.files


def test_sample_files_are_marked_as_synthetic(paths):
    marker = (paths[0].parent / "README.txt").read_text(encoding="utf-8")
    assert synthetic.SAMPLE_MARKER in marker
    assert all(p.name.startswith("sample_") for p in paths)


@pytest.mark.parametrize("seed", [2026, 1, 7, 99, 12345])
def test_pipeline_recovers_ground_truth(seed, tmp_path):
    data = synthetic.generate(seed=seed)
    result = run_pipeline(data.write(tmp_path))
    expected = data.expected

    assert len(result.transactions) == expected.unique_transactions
    assert len(result.duplicates) == expected.duplicates
    assert len(result.suspected_duplicates) == expected.suspected_duplicates
    assert len(result.rejected) == expected.rejected
    assert sum(f.blank_rows for f in result.files) == expected.blank_rows

    assert list(result.summaries) == ["INR"]
    s = result.summaries["INR"]
    assert s.income == expected.income
    assert s.expenses == expected.expenses
    assert s.refunds == expected.refunds
    assert s.unclassified_inflow == expected.unclassified_inflow
    assert s.unclassified_outflow == expected.unclassified_outflow
    assert s.transfers_in == expected.transfers_in
    assert s.transfers_out == expected.transfers_out
    assert s.net_cash_flow == expected.net_cash_flow


def test_every_source_row_is_accounted_for(dataset, paths):
    result = run_pipeline(paths)
    data_rows = sum(len(text.splitlines()) - 1 for text in dataset.files.values())
    outcomes = (
        len(result.transactions)
        + len(result.duplicates)
        + len(result.rejected)
        + sum(f.blank_rows for f in result.files)
    )
    assert outcomes == data_rows


def test_duplicates_come_from_the_overlap_and_the_repeated_reference(paths):
    result = run_pipeline(paths)
    savings_dupes = [t for t in result.duplicates if t.account == "Sample Savings 0001"]
    card_dupes = [t for t in result.duplicates if t.account != "Sample Savings 0001"]

    assert savings_dupes and all(
        t.source_file == paths[1].name and t.date.month == 2 and t.date.day <= 15
        for t in savings_dupes
    )
    assert len(card_dupes) == 1 and card_dupes[0].reference

    (suspect,) = result.suspected_duplicates
    assert (suspect.description, suspect.amount) == ("CHAI POINT CAFE", Decimal("-120.00"))
    kept_chai = [
        t for t in result.transactions
        if t.amount == Decimal("-120.00") and t.description == "CHAI POINT CAFE"
    ]
    assert len(kept_chai) == 2


def test_unclassifiable_transactions_stay_unknown(paths):
    result = run_pipeline(paths)
    unknown = [t for t in result.transactions if t.txn_type == TxnType.UNKNOWN]
    # Both come from the second savings file, which writes descriptions in lower case.
    assert sorted(t.description.upper() for t in unknown) == ["NEFT CR 88231 ANON", "UPI/P2P/FRIEND-7731"]
    assert result.summaries["INR"].quality.unknown_type == 2


def test_transfers_are_excluded(paths):
    result = run_pipeline(paths)
    s = result.summaries["INR"]
    transfers = [t for t in result.transactions if t.txn_type == TxnType.TRANSFER]
    assert len(transfers) == 6
    assert TxnType.TRANSFER not in s.by_type
    assert "Uncategorized" not in s.expenses_by_category
    assert list(s.by_month) == ["2026-01", "2026-02", "2026-03"]


def test_import_order_does_not_change_the_result(paths):
    forward = run_pipeline(paths)
    backward = run_pipeline(reversed(paths))

    assert len(backward.transactions) == len(forward.transactions)
    assert len(backward.duplicates) == len(forward.duplicates)
    assert backward.summaries["INR"].net_cash_flow == forward.summaries["INR"].net_cash_flow
    assert backward.summaries["INR"].by_type == forward.summaries["INR"].by_type


def test_reimporting_against_existing_adds_nothing(paths):
    first = run_pipeline(paths)
    second = run_pipeline(paths, existing=first.transactions)
    assert second.transactions == []
    assert second.summaries == {}


def test_cli_text_report(paths, capsys):
    assert main(["import", *map(str, paths)]) == 0
    out = capsys.readouterr().out
    assert "duplicates removed" in out
    assert "REJECTED ROWS" in out
    assert "not a bank balance" in out
    assert "Data quality" in out


def test_cli_expands_wildcards(dataset, paths, capsys):
    assert main(["import", str(paths[0].parent / "sample_*.csv"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # The three statements plus the payment-app export, which no exact rule
    # can de-duplicate against the bank (different accounts, no shared IDs).
    assert len(payload["files"]) == 4
    app = dataset.payapp
    app_rows = len(app.mirrored) + app.app_only + app.failed
    assert len(payload["transactions"]) == dataset.expected.unique_transactions + app_rows
    # A pattern matching nothing is passed through and reported as missing.
    assert main(["import", str(paths[0].parent / "nothing_*.csv")]) == 2


def test_cli_json_and_export(dataset, paths, tmp_path, capsys):
    export_path = tmp_path / "clean.csv"
    assert main(["import", *map(str, paths), "--json", "--export", str(export_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(payload["transactions"]) == dataset.expected.unique_transactions
    assert Decimal(payload["summaries"]["INR"]["income"]) == dataset.expected.income

    with export_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == dataset.expected.unique_transactions


def test_exported_csv_can_be_imported_again(paths, tmp_path):
    result = run_pipeline(paths)
    export_path = tmp_path / "clean.csv"
    report.export_csv(result, export_path)

    again = run_pipeline([export_path])
    assert again.rejected == []
    assert len(again.transactions) == len(result.transactions)
    before, after = result.summaries["INR"], again.summaries["INR"]
    assert after.by_type == before.by_type
    assert after.net_cash_flow == before.net_cash_flow


def test_cli_sample_command(tmp_path, capsys):
    assert main(["sample", str(tmp_path / "out"), "--seed", "3"]) == 0
    written = capsys.readouterr().out.split("\n")
    assert len([line for line in written if line.endswith(".csv")]) == 3


def test_cli_reports_errors_with_exit_code_2(write_csv, tmp_path, capsys):
    assert main(["import", str(tmp_path / "missing.csv")]) == 2
    assert main(["import", str(write_csv("bad.csv", "A,B\n1,2\n"))]) == 2
    assert capsys.readouterr().err.count("error:") == 2


def test_export_neutralises_spreadsheet_formulas(write_csv, tmp_path):
    source = write_csv(
        "evil.csv",
        "Date,Description,Amount\n"
        '05/01/2026,"=HYPERLINK(""http://x"",""click"")",-10.00\n'
        "06/01/2026,@SUM(A1),-5.00\n"
        "07/01/2026,Normal shop,-1.00\n",
    )
    out = tmp_path / "out.csv"
    report.export_csv(run_pipeline([source]), out)
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["description"] for r in rows] == ['\'=HYPERLINK("http://x","click")', "'@SUM(A1)", "Normal shop"]
    assert [r["amount"] for r in rows] == ["-10.00", "-5.00", "-1.00"]  # amounts untouched
