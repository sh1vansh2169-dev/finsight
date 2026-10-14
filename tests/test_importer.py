from datetime import date
from decimal import Decimal

import pytest

from moneyos.importer import SchemaError, import_csv, map_columns
from moneyos.models import UNCATEGORIZED


def test_signed_amount_layout(write_csv):
    path = write_csv(
        "bank.csv",
        "Date,Description,Amount\n"
        "05/01/2026,  ACME  CORP SALARY ,\"85,000.00\"\n"
        "06/01/2026,FRESHMART GROCERIES,-450.25\n",
    )
    result = import_csv(path)

    assert result.rejected == []
    salary, groceries = result.transactions
    assert salary.date == date(2026, 1, 5)
    assert salary.description == "ACME CORP SALARY"
    assert salary.raw_description == "ACME  CORP SALARY"
    assert salary.amount == Decimal("85000.00")
    assert groceries.amount == Decimal("-450.25")
    assert (salary.source_file, salary.source_row) == ("bank.csv", 2)
    assert groceries.source_row == 3


def test_defaults_for_missing_optional_columns(write_csv):
    path = write_csv("my_account.csv", "Date,Description,Amount\n05/01/2026,X,-1\n")
    (txn,) = import_csv(path).transactions
    assert txn.account == "my_account"
    assert txn.currency == "INR"
    assert txn.category == UNCATEGORIZED
    assert txn.reference is None

    (txn,) = import_csv(path, account="Joint", default_currency="usd").transactions
    assert (txn.account, txn.currency) == ("Joint", "USD")


def test_debit_credit_layout(write_csv):
    path = write_csv(
        "bank.csv",
        "Txn Date,Narration,Withdrawal,Deposit,Account\n"
        "2026-01-05,rent,₹22000.00,,Savings-0001\n"
        "2026-01-06,salary,,₹85000.00,Savings-0001\n"
        "2026-01-07,zero filled,120.00,0.00,Savings-0001\n",
    )
    result = import_csv(path)

    assert [t.amount for t in result.transactions] == [
        Decimal("-22000.00"),
        Decimal("85000.00"),
        Decimal("-120.00"),
    ]
    assert {t.account for t in result.transactions} == {"Savings-0001"}


def test_amount_with_type_column(write_csv):
    path = write_csv(
        "card.csv",
        "Posting Date,Merchant,Amount,Type,Ref No\n"
        "05 Jan 2026,SHOPKART,\"1,299.00\",DR,CC1\n"
        "06 Jan 2026,REFUND,499.00,CR,CC2\n"
        "07 Jan 2026,NO REF,10.00,DR,N/A\n",
    )
    first, second, third = import_csv(path).transactions

    assert (first.amount, first.reference) == (Decimal("-1299.00"), "CC1")
    assert second.amount == Decimal("499.00")
    assert third.reference is None


def test_category_and_currency_columns_are_used(write_csv):
    path = write_csv(
        "bank.csv",
        "Date,Description,Amount,Currency,Category\n05/01/2026,X,-1,usd,Hobbies\n",
    )
    (txn,) = import_csv(path).transactions
    assert (txn.currency, txn.category) == ("USD", "Hobbies")


def test_bad_rows_are_rejected_with_reason_and_row_number(write_csv):
    path = write_csv(
        "bank.csv",
        "Date,Description,Debit,Credit\n"
        "05/01/2026,GOOD,10.00,\n"        # line 2
        "31/02/2026,BAD DATE,10.00,\n"    # line 3
        "05/01/2026,BAD AMOUNT,abc,\n"    # line 4
        "05/01/2026,,10.00,\n"            # line 5
        "05/01/2026,NO AMOUNT,,\n"        # line 6
        "05/01/2026,BOTH,10.00,5.00\n"    # line 7
        "05/01/2026,ZERO,0.00,\n"         # line 8
        ",,,\n"                           # line 9, blank
        "06/01/2026,GOOD AGAIN,,20.00\n",  # line 10
    )
    result = import_csv(path)

    assert [t.description for t in result.transactions] == ["GOOD", "GOOD AGAIN"]
    assert result.blank_rows == 1
    assert [(r.source_row, r.reason) for r in result.rejected] == [
        (3, "invalid date: '31/02/2026'"),
        (4, "unparseable amount: 'abc'"),
        (5, "missing description"),
        (6, "missing amount"),
        (7, "both debit and credit are filled in"),
        (8, "zero amount"),
    ]
    assert result.rejected[1].raw["Description"] == "BAD AMOUNT"


def test_month_first_option(write_csv):
    path = write_csv("bank.csv", "Date,Description,Amount\n03/04/2026,X,-1\n")
    assert import_csv(path).transactions[0].date == date(2026, 4, 3)
    assert import_csv(path, day_first=False).transactions[0].date == date(2026, 3, 4)


def test_utf8_bom_and_quoted_commas(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes(
        "﻿Date,Description,Amount\n05/01/2026,\"CAFÉ, THE\",-5\n".encode("utf-8")
    )
    (txn,) = import_csv(path).transactions
    assert txn.description == "CAFÉ, THE"


def test_missing_required_columns(write_csv):
    with pytest.raises(SchemaError, match="date"):
        import_csv(write_csv("a.csv", "When,Description,Amount\n"))
    with pytest.raises(SchemaError, match="amount"):
        import_csv(write_csv("b.csv", "Date,Description,Balance\n"))
    with pytest.raises(SchemaError, match="no header"):
        import_csv(write_csv("c.csv", ""))


def test_map_columns_is_case_and_punctuation_insensitive():
    mapping = map_columns(["TXN_DATE", " Particulars ", "Amount (INR)", "Chq/Ref No."])
    assert mapping == {
        "date": "TXN_DATE",
        "description": " Particulars ",
        "amount": "Amount (INR)",
        "reference": "Chq/Ref No.",
    }
