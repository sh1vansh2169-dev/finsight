"""Engine creation, schema migrations and the real/sample data-mode guard."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, event, func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from moneyos.config import DataMode
from moneyos.db.tables import AppMeta, ImportBatch, TransactionRecord

# The schema as v0.2 created it, before migrations existed.
BASELINE_REVISION = "0001"


class DataModeError(RuntimeError):
    """The database holds a different kind of data than the app expects."""


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    if url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(resources.files("moneyos.db") / "migrations"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def migrate(engine: Engine, revision: str = "head") -> None:
    """Bring the schema up to ``revision``.

    A database created before migrations existed has the baseline tables but
    no ``alembic_version``; it is stamped as the baseline, then upgraded.
    """
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        config = alembic_config(connection)
        if "alembic_version" not in tables and "transactions" in tables:
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, revision)


def ensure_data_mode(engine: Engine, mode: DataMode) -> None:
    """Stamp a new database with ``mode``, or refuse one stamped differently.

    This is what keeps synthetic sample data and real records apart: a
    database seeded with sample data can never be opened in real mode, and
    vice versa.
    """
    with Session(engine) as session, session.begin():
        stamp = session.get(AppMeta, "data_mode")
        if stamp is None:
            has_data = session.scalar(select(func.count()).select_from(TransactionRecord)) or (
                session.scalar(select(func.count()).select_from(ImportBatch))
            )
            if has_data:
                raise DataModeError(
                    f"{engine.url} contains data but no data-mode stamp; refusing to guess"
                )
            session.add(AppMeta(key="data_mode", value=mode.value))
        elif stamp.value != mode.value:
            raise DataModeError(
                f"{engine.url} holds {stamp.value} data but MoneyOS is running in "
                f"{mode.value} mode; use a different database file"
            )


def init_db(database_url: str, mode: DataMode) -> sessionmaker[Session]:
    """Migrate the schema, check the data mode, return a session factory.

    The data mode is checked *before* migrating, so opening a database in
    the wrong mode never modifies it.
    """
    engine = make_engine(database_url)
    try:
        with engine.connect() as connection:
            existing = "app_meta" in inspect(connection).get_table_names()
        if existing:
            ensure_data_mode(engine, mode)
        migrate(engine)
        if not existing:
            ensure_data_mode(engine, mode)
    except BaseException:
        engine.dispose()
        raise
    return sessionmaker(engine, expire_on_commit=False)
