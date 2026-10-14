from datetime import date
from decimal import Decimal

import pytest

from moneyos.models import Transaction


@pytest.fixture
def make_txn():
    def _make(day="2026-01-15", description="FRESHMART GROCERIES", amount="-100.00", **overrides):
        fields = {
            "date": date.fromisoformat(day),
            "description": description,
            "amount": Decimal(amount),
            "currency": "INR",
            "account": "Savings-0001",
        }
        fields.update(overrides)
        return Transaction(**fields)

    return _make


@pytest.fixture
def write_csv(tmp_path):
    def _write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write
