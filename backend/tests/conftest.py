"""Database fixtures backed by local Compose or the CI Postgres service."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from cloudscope.db.session import create_db_engine, create_session_factory

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
    """Provide a sync SQLAlchemy engine using the production connection settings."""
    engine = create_db_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


@pytest.fixture(scope="session")
def migrated_engine(db_engine: Engine, alembic_config: Config) -> Engine:
    with db_engine.connect() as connection:
        alembic_config.attributes["connection"] = connection
        try:
            command.upgrade(alembic_config, "head")
        finally:
            alembic_config.attributes.pop("connection", None)
    return db_engine


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(migrated_engine)
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            with factory(bind=connection, join_transaction_mode="create_savepoint") as session:
                yield session
        finally:
            transaction.rollback()
