"""Explicit sync database factories; importing this module never opens a connection."""

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def create_db_engine(database_url: str | URL) -> Engine:
    """Use UTC on every connection and avoid logging bound parameter values."""
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not url.database:
        raise ValueError("Expected a postgresql+psycopg URL with a database name")
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC", "connect_timeout": 5},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
