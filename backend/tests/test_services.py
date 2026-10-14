"""Import workflow, ledger and data-mode guard against a real SQLite file."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from moneyos.config import DataMode
from moneyos.db.session import DataModeError, init_db
from moneyos.db.tables import AuditEvent, TransactionRecord
from moneyos.domain import synthetic
from moneyos.domain.importer import SchemaError
from moneyos.domain.models import Basis, Direction, TxnType
from moneyos.services import imports, ledger
from moneyos.services.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PayloadTooLargeError,
)
from moneyos.services.mapping import get_or_create_account

COFFEE = "Date,Description,Amount,Account\n" + "07/02/2026,CHAI POINT CAFE,-120.00,Wallet\n"


def _preview(session, rules, text, name="file.csv", **options):
    return imports.preview_import(
        session,
        filename=name,
        content=text.encode("utf-8"),
        options=imports.ImportOptions(**options),
        rules=rules,
    )


def _import(session, rules, text, name="file.csv", **options):
    batch = _preview(session, rules, text, name, **options)
    return imports.commit_import(session, batch.id)


def _ledger_count(session):
    return session.scalar(select(func.count()).select_from(TransactionRecord))


def _load_sample(session, rules, dataset):
    batches = []
    for name, text in dataset.files.items():
        account = synthetic.CARD_ACCOUNT if "card" in name else None
        batches.append(_import(session, rules, text, name, account=account))
    return batches


# ------------------------------------------------------------------ preview


def test_preview_stages_rows_without_touching_the_ledger(session, rules):
    text = (
        "Date,Description,Amount\n"
        "05/01/2026,FRESHMART GROCERIES,-450.00\n"
        "06/01/2026,BAD,abc\n"
        ",,\n"
        "07/01/2026,ACME CORP SALARY,85000\n"
    )
    batch = _preview(session, rules, text, "C:\\Users\\someone\\jan.csv")

    assert batch.filename == "jan.csv"  # client path stripped
    assert batch.status == "previewed"
    assert (batch.total_rows, batch.new_rows, batch.rejected_rows, batch.blank_rows) == (4, 2, 1, 1)
    assert [(r.source_row, r.outcome) for r in batch.rows] == [(2, "new"), (3, "rejected"), (5, "new")]
    assert batch.rows[1].raw == {"Date": "06/01/2026", "Description": "BAD", "Amount": "abc"}
    assert batch.rows[0].payload["txn_type"] == "expense"
    assert _ledger_count(session) == 0


def test_preview_rejects_unusable_files(session, rules):
    with pytest.raises(SchemaError):
        _preview(session, rules, "When,What\n1,2\n")
    with pytest.raises(PayloadTooLargeError):
        imports.preview_import(
            session,
            filename="big.csv",
            content=b"x" * (5 * 1024 * 1024 + 1),
            options=imports.ImportOptions(),
            rules=rules,
        )
    assert imports.list_batches(session) == []


# ------------------------------------------------------------------- commit


def test_commit_writes_new_rows_with_provenance_and_audit(session, rules):
    batch = _import(session, rules, COFFEE, "wallet.csv")

    assert (batch.status, batch.inserted_rows) == ("committed", 1)
    assert batch.committed_at.tzinfo is not None
    record = session.scalars(select(TransactionRecord)).one()
    assert (record.amount_minor, record.direction, record.currency) == (12000, "debit", "INR")
    assert (record.source, record.import_batch_id, record.source_file, record.source_row) == (
        "csv_import", batch.id, "wallet.csv", 2,
    )
    assert record.created_at.tzinfo is not None
    event = session.scalars(select(AuditEvent)).one()
    assert (event.action, event.entity_id, event.details["inserted"]) == ("import_committed", batch.id, 1)


def test_commit_and_discard_only_work_once(session, rules):
    committed = _import(session, rules, COFFEE)
    with pytest.raises(ConflictError):
        imports.commit_import(session, committed.id)
    with pytest.raises(ConflictError):
        imports.discard_import(session, committed.id)

    discarded = imports.discard_import(session, _preview(session, rules, COFFEE).id)
    assert discarded.status == "discarded" and discarded.rows == []
    with pytest.raises(ConflictError):
        imports.commit_import(session, discarded.id)
    with pytest.raises(NotFoundError):
        imports.commit_import(session, 999)
    assert _ledger_count(session) == 1


def test_reimporting_the_same_file_adds_nothing(session, rules):
    first = _import(session, rules, COFFEE)
    second = _preview(session, rules, COFFEE)

    assert (second.new_rows, second.duplicate_rows) == (0, 1)
    assert imports.same_file_imports(session, second) == [first.id]
    assert imports.commit_import(session, second.id).inserted_rows == 0
    assert _ledger_count(session) == 1


def test_commit_rechecks_duplicates_against_the_current_ledger(session, rules):
    """Two previews of overlapping data: whichever commits second skips the overlap."""
    slow = _preview(session, rules, COFFEE)
    fast = _preview(session, rules, COFFEE)
    assert slow.new_rows == fast.new_rows == 1  # neither knows about the other yet

    imports.commit_import(session, fast.id)
    slow = imports.commit_import(session, slow.id)
    assert (slow.inserted_rows, slow.duplicate_rows, slow.new_rows) == (0, 1, 0)
    assert slow.rows[0].reason.startswith("same account, date, amount")
    assert _ledger_count(session) == 1


def test_identical_rows_are_matched_by_occurrence_against_the_ledger(session, rules):
    header = "Date,Description,Amount,Account\n"
    two = header + "07/02/2026,CHAI POINT CAFE,-120.00,Wallet\n" * 2
    three = header + "07/02/2026,CHAI POINT CAFE,-120.00,Wallet\n" * 3

    first = _import(session, rules, two)
    assert (first.inserted_rows, first.suspected_rows) == (2, 1)
    second = _import(session, rules, three)
    assert (second.inserted_rows, second.duplicate_rows) == (1, 2)
    assert _ledger_count(session) == 3


def test_sample_data_round_trips_through_the_database(session, rules, dataset):
    batches = _load_sample(session, rules, dataset)
    expected = dataset.expected

    assert sum(b.inserted_rows for b in batches) == expected.unique_transactions
    assert sum(b.duplicate_rows for b in batches) == expected.duplicates
    assert sum(b.rejected_rows for b in batches) == expected.rejected
    assert sum(b.suspected_rows for b in batches) == expected.suspected_duplicates

    (s,) = ledger.summarize_ledger(session, ledger.TransactionFilter()).values()
    assert s.income == expected.income
    assert s.expenses == expected.expenses
    assert s.refunds == expected.refunds
    assert (s.unclassified_inflow, s.unclassified_outflow) == (
        expected.unclassified_inflow, expected.unclassified_outflow,
    )
    assert (s.transfers_in, s.transfers_out) == (expected.transfers_in, expected.transfers_out)
    assert s.net_cash_flow == expected.net_cash_flow

    accounts = {a.name for a in ledger.list_accounts(session)}
    assert accounts == {"Sample Savings 0001", synthetic.CARD_ACCOUNT}

    # Loading the same files again changes nothing.
    again = _load_sample(session, rules, dataset)
    assert sum(b.inserted_rows for b in again) == 0
    assert _ledger_count(session) == expected.unique_transactions


def test_summary_filters_by_date(session, rules, dataset):
    _load_sample(session, rules, dataset)
    march = ledger.TransactionFilter(start=date(2026, 3, 1), end=date(2026, 3, 31))
    (s,) = ledger.summarize_ledger(session, march).values()
    assert list(s.by_month) == ["2026-03"]
    assert s.income == Decimal("210000.00")  # salary + bonus


def test_reference_is_unique_per_account_in_the_database(session):
    account = get_or_create_account(session, "Card", "INR")

    def record():
        return TransactionRecord(
            account=account, occurred_on=date(2026, 1, 1), description="X", amount_minor=100,
            direction="debit", currency="INR", txn_type="unknown", type_basis="none",
            category="Uncategorized", category_basis="none", status="unknown",
            external_id="CC1", source="csv_import",
        )

    session.add_all([record(), record()])
    with pytest.raises(IntegrityError):
        session.commit()


# ------------------------------------------------------- manual entry & edits


def test_manual_entry_is_classified_and_audited(session, rules):
    record, warnings = ledger.create_manual(
        session, occurred_on=date(2026, 3, 1), description="Chai at station cafe",
        amount=Decimal("30.00"), direction=Direction.DEBIT, currency="inr", account="Cash", rules=rules,
    )
    assert warnings == []
    assert (record.source, record.currency, record.amount_minor) == ("manual", "INR", 3000)
    assert (record.category, record.category_basis) == ("Dining", "rule")
    assert (record.txn_type, record.type_basis) == ("expense", "rule")
    assert [e.action for e in ledger.audit_trail(session, "transaction", record.id)] == ["transaction_created"]


def test_manual_entry_with_user_type_and_duplicate_warning(session, rules):
    args = dict(
        occurred_on=date(2026, 3, 1), description="Loan to Sam", amount=Decimal("500"),
        direction=Direction.DEBIT, currency="INR", account="Cash", rules=rules,
        txn_type=TxnType.LENT,
    )
    first, warnings = ledger.create_manual(session, **args)
    assert (first.txn_type, first.type_basis) == ("lent", "user")
    assert warnings == []

    second, warnings = ledger.create_manual(session, **args)
    assert second.id != first.id  # still saved: the user typed it in
    assert len(warnings) == 1 and "already exists" in warnings[0]


@pytest.mark.parametrize(
    ("amount", "direction", "txn_type", "currency"),
    [
        (Decimal("0"), Direction.DEBIT, None, "INR"),
        (Decimal("-5"), Direction.DEBIT, None, "INR"),
        (Decimal("10.50"), Direction.DEBIT, None, "JPY"),
        (Decimal("10"), Direction.DEBIT, TxnType.INCOME, "INR"),
        (Decimal("10"), Direction.CREDIT, TxnType.EXPENSE, "INR"),
    ],
)
def test_manual_entry_validation(session, rules, amount, direction, txn_type, currency):
    with pytest.raises(InvalidRequestError):
        ledger.create_manual(
            session, occurred_on=date(2026, 3, 1), description="X", amount=amount,
            direction=direction, currency=currency, account="Cash", rules=rules, txn_type=txn_type,
        )
    assert _ledger_count(session) == 0


def test_correction_is_recorded_and_changes_the_summary(session, rules, dataset):
    _load_sample(session, rules, dataset)
    records, _ = ledger.list_transactions(session, ledger.TransactionFilter(txn_type=TxnType.UNKNOWN))
    friend = next(r for r in records if r.direction == "debit")
    (before,) = ledger.summarize_ledger(session, ledger.TransactionFilter()).values()

    corrected = ledger.correct_transaction(session, friend.id, txn_type=TxnType.LENT)
    assert (corrected.txn_type, corrected.type_basis) == ("lent", Basis.USER.value)

    (after,) = ledger.summarize_ledger(session, ledger.TransactionFilter()).values()
    assert after.unclassified_outflow == before.unclassified_outflow - Decimal("1500.00")
    assert after.by_type[TxnType.LENT] == Decimal("1500.00")
    assert after.net_cash_flow == before.net_cash_flow  # reclassifying moves no money

    (event,) = ledger.audit_trail(session, "transaction", friend.id)
    assert event.details["before"]["txn_type"] == "unknown"
    assert event.details["after"] == {
        "txn_type": "lent", "type_basis": "user", "category": "Uncategorized", "category_basis": "none",
    }


def test_correction_validation(session, rules):
    record, _ = ledger.create_manual(
        session, occurred_on=date(2026, 3, 1), description="X", amount=Decimal("1"),
        direction=Direction.DEBIT, currency="INR", account="Cash", rules=rules,
    )
    with pytest.raises(InvalidRequestError):
        ledger.correct_transaction(session, record.id, txn_type=TxnType.INCOME)
    with pytest.raises(InvalidRequestError):
        ledger.correct_transaction(session, record.id)
    with pytest.raises(NotFoundError):
        ledger.correct_transaction(session, 999, category="X")


def test_list_transactions_filters_and_pages(session, rules, dataset):
    _load_sample(session, rules, dataset)
    page, total = ledger.list_transactions(session, ledger.TransactionFilter(), limit=5, offset=0)
    assert total == dataset.expected.unique_transactions
    assert len(page) == 5
    assert page[0].occurred_on >= page[-1].occurred_on  # newest first

    card, card_total = ledger.list_transactions(
        session, ledger.TransactionFilter(account=synthetic.CARD_ACCOUNT), limit=500
    )
    assert card_total == len(card) and all(r.account.name == synthetic.CARD_ACCOUNT for r in card)


# ---------------------------------------------------------- data separation


def test_sample_and_real_databases_cannot_be_mixed(database_url, tmp_path):
    init_db(database_url, DataMode.SAMPLE).kw["bind"].dispose()
    with pytest.raises(DataModeError, match="holds sample data"):
        init_db(database_url, DataMode.REAL)

    real_url = f"sqlite:///{(tmp_path / 'real.db').as_posix()}"
    init_db(real_url, DataMode.REAL).kw["bind"].dispose()
    with pytest.raises(DataModeError, match="holds real data"):
        init_db(real_url, DataMode.SAMPLE)


def test_unstamped_database_with_data_is_refused(session, rules, database_url):
    from moneyos.db.tables import AppMeta

    _import(session, rules, COFFEE)
    session.delete(session.get(AppMeta, "data_mode"))
    session.commit()
    with pytest.raises(DataModeError, match="no data-mode stamp"):
        init_db(database_url, DataMode.REAL)
