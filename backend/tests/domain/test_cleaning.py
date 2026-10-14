from datetime import date
from decimal import Decimal

import pytest

from moneyos.domain.cleaning import (
    CleaningError,
    clean_description,
    normalize_key,
    parse_amount,
    parse_date,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("100", "100.00"),
        ("100.5", "100.50"),
        ("-42.10", "-42.10"),
        ("+42.10", "42.10"),
        ("  1,234.56 ", "1234.56"),
        ("1,23,456.78", "123456.78"),  # Indian grouping
        ("1,234,567.89", "1234567.89"),
        ("₹22,000.00", "22000.00"),
        ("$ 19.99", "19.99"),
        ("Rs. 500", "500.00"),
        ("INR 500.00", "500.00"),
        ("-₹250.00", "-250.00"),
        ("₹-250.00", "-250.00"),
        ("(250.00)", "-250.00"),
        ("250.00-", "-250.00"),
        ("−250.00", "-250.00"),  # unicode minus
        ("500.00 DR", "-500.00"),
        ("500.00 Cr", "500.00"),
        ("-500.00 CR", "500.00"),
        (".75", "0.75"),
        ("10.005", "10.01"),  # half-up rounding
    ],
)
def test_parse_amount_accepts(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize(
    "text",
    ["", "   ", None, "abc", "12,50", "1.234,56", "1,2,3", "12.34.56", "--5", "5 apples"],
)
def test_parse_amount_rejects(text):
    with pytest.raises(CleaningError):
        parse_amount(text)


def test_parse_amount_returns_exact_decimal():
    # 0.1 + 0.2 is the classic float trap; Decimal must stay exact.
    assert parse_amount("0.10") + parse_amount("0.20") == Decimal("0.30")


@pytest.mark.parametrize(
    "text",
    [
        "2026-03-04",
        "2026/03/04",
        "2026-3-4",
        "2026-03-04T13:45:00",
        "2026-03-04 13:45",
        "04/03/2026",
        "04-03-2026",
        "04.03.2026",
        "04/03/26",
        "04/03/2026 09:15:00",
        "04 Mar 2026",
        "04-Mar-2026",
        "4 March 2026",
        "Mar 4, 2026",
    ],
)
def test_parse_date_day_first_formats(text):
    assert parse_date(text) == date(2026, 3, 4)


def test_parse_date_month_first():
    assert parse_date("03/04/2026", day_first=False) == date(2026, 3, 4)
    assert parse_date("03/04/2026", day_first=True) == date(2026, 4, 3)


def test_parse_date_does_not_fall_back_to_other_order():
    # 25 cannot be a month. Guessing month-first here would mean one file
    # gets read both ways.
    with pytest.raises(CleaningError):
        parse_date("03/25/2026", day_first=True)


@pytest.mark.parametrize("text", ["", None, "31/02/2026", "2026-02-30", "yesterday", "2026-13-01"])
def test_parse_date_rejects(text):
    with pytest.raises(CleaningError):
        parse_date(text)


def test_clean_description_collapses_whitespace_and_keeps_case():
    assert clean_description("  FreshMart \t  Groceries\n") == "FreshMart Groceries"
    assert clean_description(None) == ""


def test_normalize_key_ignores_case_spacing_and_punctuation():
    assert normalize_key("FRESHMART  Groceries #12") == normalize_key("freshmart groceries-12")
    assert normalize_key("FRESHMART") != normalize_key("FRESHMARKET")
