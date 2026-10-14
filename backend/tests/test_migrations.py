"""Migrations must reproduce the models exactly and upgrade old databases safely."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from moneyos.config import DataMode
from moneyos.db.session import DataModeError, alembic_config, init_db, make_engine, migrate
from moneyos.db.tables import Base


@pytest.fixture
def engine(database_url):
    engine = make_engine(database_url)
    yield engine
    engine.dispose()


def _revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_migrations_match_the_models(engine):
    """If this fails, a model changed without a migration (or vice versa)."""
    migrate(engine)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_v02_database_is_stamped_upgraded_and_keeps_its_data(engine, database_url):
    # Recreate a database exactly as v0.2 left it: baseline tables, data,
    # and no alembic_version table.
    migrate(engine, "0001")
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text("INSERT INTO app_meta VALUES ('data_mode', 'real')"))
        connection.execute(text(
            "INSERT INTO accounts (id, name, kind, currency, created_at) "
            "VALUES (1, 'Wallet', 'other', 'INR', '2026-10-01 00:00:00')"
        ))
        connection.execute(text(
            "INSERT INTO transactions (account_id, occurred_on, description, raw_description, "
            "amount_minor, direction, currency, txn_type, type_basis, category, category_basis, "
            "status, source, created_at, updated_at) VALUES (1, '2026-10-01', 'TEA', 'TEA', 1500, "
            "'debit', 'INR', 'expense', 'rule', 'Dining', 'rule', 'posted', 'manual', "
            "'2026-10-01 00:00:00', '2026-10-01 00:00:00')"
        ))
    assert _revision(engine) is None

    factory = init_db(database_url, DataMode.REAL)
    factory.kw["bind"].dispose()

    assert _revision(engine) == "0002"
    columns = {c["name"] for c in inspect(engine).get_columns("transactions")}
    assert "duplicate_of_id" in columns
    assert "match_candidates" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        row = connection.execute(text("SELECT description, amount_minor, duplicate_of_id FROM transactions")).one()
    assert tuple(row) == ("TEA", 1500, None)


def test_wrong_mode_database_is_refused_before_it_is_changed(engine, database_url):
    migrate(engine, "0001")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO app_meta VALUES ('data_mode', 'sample')"))

    with pytest.raises(DataModeError):
        init_db(database_url, DataMode.REAL)
    assert _revision(engine) == "0001"  # not migrated


def test_downgrade_and_upgrade_round_trip(engine):
    migrate(engine)
    with engine.begin() as connection:
        config = alembic_config(connection)
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
    assert _revision(engine) == "0002"
