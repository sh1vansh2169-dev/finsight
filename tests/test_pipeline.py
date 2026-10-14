"""End-to-end tests against the synthetic dataset and its known ground truth."""

import csv
import json
from decimal import Decimal

import pytest

from moneyos import report, synthetic
from moneyos.categorize import TRANSFER
from moneyos.cli import main
from moneyos.pipeline import run_pipeline


@pytest.fixture(scope="module")
def dataset():
    return synthetic.generate(seed=2026)


@pytest.fixture
def paths(dataset, tmp_path):
    return dataset.write(tmp_path)


def test_generator_is_deterministic(dataset):
    assert synthetic.generate(seed=2026) == dataset
    assert synthetic.generate(seed=7).files != dataset.files


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
    summary = result.summaries["INR"]
    assert summary.totals.income == expected.income
    assert summary.totals.expenses == expected.expenses
    assert summary.totals.net == expected.income - expected.expenses


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
    savings_dupes = [t for t in result.duplicates if t.account == "Savings-0001"]
    card_dupes = [t for t in result.duplicates if t.account != "Savings-0001"]

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


def test_transfers_are_excluded_and_nothing_is_left_uncategorized(paths):
    result = run_pipeline(paths)
    summary = result.summaries["INR"]

    transfers = [t for t in result.transactions if t.category == TRANSFER]
    assert len(transfers) == 6
    assert summary.transfers_out == -sum(t.amount for t in transfers if t.amount < 0)
    assert summary.transfers_in == sum(t.amount for t in transfers if t.amount > 0)
    assert TRANSFER not in summary.expenses_by_category
    assert "Uncategorized" not in summary.expenses_by_category
    assert list(summary.by_month) == ["2026-01", "2026-02", "2026-03"]


def test_import_order_does_not_change_the_result(paths):
    forward = run_pipeline(paths)
    backward = run_pipeline(reversed(paths))

    assert len(backward.transactions) == len(forward.transactions)
    assert len(backward.duplicates) == len(forward.duplicates)
    assert backward.summaries["INR"].totals == forward.summaries["INR"].totals


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
    assert "SUMMARY (INR)" in out


def test_cli_json_and_export(dataset, paths, tmp_path, capsys):
    export_path = tmp_path / "clean.csv"
    assert main(["import", *map(str, paths), "--json", "--export", str(export_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(payload["transactions"]) == dataset.expected.unique_transactions
    assert Decimal(payload["summaries"]["INR"]["income"]) == dataset.expected.income

    with export_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == dataset.expected.unique_transactions
    assert sum(Decimal(r["amount"]) for r in rows) == sum(
        Decimal(t["amount"]) for t in payload["transactions"]
    )


def test_exported_csv_can_be_imported_again(paths, tmp_path):
    result = run_pipeline(paths)
    export_path = tmp_path / "clean.csv"
    report.export_csv(result, export_path)

    again = run_pipeline([export_path])
    assert again.rejected == []
    assert len(again.transactions) == len(result.transactions)
    assert again.summaries["INR"].totals == result.summaries["INR"].totals


def test_cli_sample_command(tmp_path, capsys):
    assert main(["sample", str(tmp_path / "out"), "--seed", "3"]) == 0
    written = capsys.readouterr().out.split("\n")
    assert len([line for line in written if line.endswith(".csv")]) == 3


def test_cli_reports_errors_with_exit_code_2(write_csv, tmp_path, capsys):
    assert main(["import", str(tmp_path / "missing.csv")]) == 2
    assert main(["import", str(write_csv("bad.csv", "A,B\n1,2\n"))]) == 2
    assert capsys.readouterr().err.count("error:") == 2
