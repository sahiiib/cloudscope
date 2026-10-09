"""Alembic entry point; DB configuration is independent of authentication secrets."""

import os

from alembic import context
from sqlalchemy import Connection

from cloudscope.db.models import Base
from cloudscope.db.session import create_db_engine

config = context.config


def database_url() -> str:
    # Programmatic callers (tests) may supply a URL without editing process env.
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("CLOUDSCOPE_DATABASE_URL")
    if not url:
        raise RuntimeError("Export CLOUDSCOPE_DATABASE_URL before running migrations")
    return url


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = config.attributes.get("connection")
    if connection is not None:
        migrate(connection)
    else:
        engine = create_db_engine(database_url())
        try:
            with engine.connect() as connection:
                migrate(connection)
        finally:
            engine.dispose()
