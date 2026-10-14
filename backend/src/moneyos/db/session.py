"""Engine creation, schema setup and the real/sample data-mode guard."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from moneyos.config import DataMode
from moneyos.db.tables import AppMeta, Base, ImportBatch, TransactionRecord


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
    """Create tables if needed, check the data mode, return a session factory.

    ``create_all`` only adds missing tables. Once the schema starts changing
    under existing data, this should be replaced by Alembic migrations.
    """
    engine = make_engine(database_url)
    try:
        Base.metadata.create_all(engine)
        ensure_data_mode(engine, mode)
    except BaseException:
        engine.dispose()
        raise
    return sessionmaker(engine, expire_on_commit=False)
