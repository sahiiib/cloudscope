"""Database fixtures backed by local Compose or the CI Postgres service."""

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.engine import make_url

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://cloudscope:cloudscope@localhost:5432/postgres"


@pytest.fixture(scope="session")
def database_url() -> Iterator[URL]:
    """Create one uniquely named database per session, then drop only that database."""
    admin_url = make_url(os.environ.get("CLOUDSCOPE_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL))
    if admin_url.drivername != "postgresql+psycopg":
        raise ValueError("CLOUDSCOPE_TEST_DATABASE_URL must use postgresql+psycopg")

    # Never use the application's configured database: only this generated name
    # is created, exposed to tests, and dropped during teardown.
    database_name = f"cloudscope_test_{uuid4().hex}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        try:
            yield admin_url.set(database=database_name)
        finally:
            with admin_engine.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{database_name}" WITH (FORCE)')
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session")
def db_engine(database_url: URL) -> Iterator[Engine]:
    """Provide a sync SQLAlchemy engine; schema/migrations arrive in T-005."""
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
