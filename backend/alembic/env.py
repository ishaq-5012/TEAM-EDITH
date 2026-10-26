from __future__ import annotations

from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401 - registers all tables on Base.metadata
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # Tests and tooling may inject a connection or URL; otherwise use app settings.
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(conn) -> None:  # noqa: ANN001
    """Run migrations on a connection.

    SQLite cannot alter most constraints, so batch migrations copy a table, drop the original and rename the copy.
    With foreign-key enforcement on, dropping the original performs an implicit DELETE that cascades into child
    tables (for example validation_runs -> rule_results), silently destroying data. Enforcement is therefore off
    while migrations run (Alembic's documented requirement), and referential integrity is verified afterwards.
    """
    sqlite = conn.dialect.name == "sqlite"
    if sqlite:
        if conn.in_transaction():
            conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
    context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
    if sqlite:
        dangling = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()
        if dangling:
            raise RuntimeError(f"Migration left {len(dangling)} row(s) violating foreign keys: {dangling[:5]}")


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = make_engine(_url())
    with engine.connect() as conn:
        _run(conn)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
