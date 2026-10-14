from datetime import date
from decimal import Decimal

import pytest

from moneyos.domain.models import Transaction


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


@pytest.fixture(scope="session")
def rules():
    from moneyos.domain.classify import load_rules

    return load_rules()


@pytest.fixture
def database_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture
def session(database_url):
    from moneyos.config import DataMode
    from moneyos.db.session import init_db

    factory = init_db(database_url, DataMode.REAL)
    with factory() as s:
        yield s
    factory.kw["bind"].dispose()


@pytest.fixture(scope="session")
def dataset():
    from moneyos.domain import synthetic

    return synthetic.generate(seed=2026)
