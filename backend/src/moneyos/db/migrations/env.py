"""Alembic environment.

Normally driven from ``moneyos.db.session.migrate``, which passes an open
connection in ``config.attributes["connection"]``. From the command line
(``alembic -c backend/alembic.ini ...``) the URL comes from
MONEYOS_DATABASE_URL or alembic.ini.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from moneyos.db.tables import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get("MONEYOS_DATABASE_URL") or config.get_main_option("sqlalchemy.url")


def _run(connection) -> None:
    # Batch mode lets SQLite, which cannot ALTER most things, rebuild tables.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
elif (connection := config.attributes.get("connection")) is not None:
    _run(connection)
else:
    engine = create_engine(_url())
    try:
        with engine.connect() as connection:
            _run(connection)
            connection.commit()
    finally:
        engine.dispose()
