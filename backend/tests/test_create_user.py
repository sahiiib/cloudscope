from unittest.mock import Mock

import pytest
from argon2.exceptions import HashingError
from sqlalchemy import URL, Engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from cloudscope.auth.passwords import verify_password
from cloudscope.cli import app
from cloudscope.db.models import User

PASSWORD = "cli-password-placeholder"


@pytest.fixture
def cli_database(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Mock:
    # The command uses real Postgres and commits a savepoint inside the test transaction.
    engine = Mock(spec=Engine)
    monkeypatch.setenv("CLOUDSCOPE_DATABASE_URL", "postgresql+psycopg://localhost/test")
    monkeypatch.setattr("cloudscope.cli.create_db_engine", Mock(return_value=engine))
    factory = sessionmaker(
        bind=db_session.get_bind(), join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    monkeypatch.setattr("cloudscope.cli.create_session_factory", lambda engine: factory)
    return engine


@pytest.mark.parametrize("admin", [False, True])
def test_create_user_persists_only_hash_and_hides_password(
    cli_database: Mock, db_session: Session, admin: bool
) -> None:
    result = CliRunner().invoke(
        app,
        ["create-user", "test-cli-user", *(["--admin"] if admin else [])],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert PASSWORD not in result.output
    user = db_session.scalars(select(User)).one()
    assert user.username == "test-cli-user" and user.is_admin is admin
    assert user.is_active is True and user.mfa_enabled is False
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, user.password_hash)
    assert user.password_hash not in result.output
    cli_database.dispose.assert_called_once_with()


def test_duplicate_does_not_replace_existing_user(cli_database: Mock, db_session: Session) -> None:
    runner = CliRunner()
    args = ["create-user", "test-cli-user"]
    assert runner.invoke(app, args, input=f"{PASSWORD}\n{PASSWORD}\n").exit_code == 0
    original = db_session.scalars(select(User)).one().password_hash
    result = runner.invoke(
        app, [*args, "--admin"], input="other-password-placeholder\nother-password-placeholder\n"
    )
    assert result.exit_code == 1 and "already exists" in result.output
    db_session.expire_all()
    user = db_session.scalars(select(User)).one()
    assert user.password_hash == original and user.is_admin is False


@pytest.mark.parametrize("input_text", ["short\nshort\n", f"{PASSWORD}\ndifferent\n"])
def test_invalid_or_unconfirmed_password_creates_nothing(
    cli_database: Mock, db_session: Session, input_text: str
) -> None:
    result = CliRunner().invoke(app, ["create-user", "test-cli-user"], input=input_text)
    assert result.exit_code != 0
    assert db_session.scalars(select(User)).all() == []
    assert PASSWORD not in result.output
    cli_database.dispose.assert_not_called()


def test_blank_username_rejected(cli_database: Mock, db_session: Session) -> None:
    result = CliRunner().invoke(app, ["create-user", " "], input=f"{PASSWORD}\n{PASSWORD}\n")
    assert result.exit_code != 0 and "blank" in result.output
    assert db_session.scalars(select(User)).all() == []


def test_password_cannot_be_given_as_option(cli_database: Mock) -> None:
    result = CliRunner().invoke(app, ["create-user", "test-cli-user", "--password", PASSWORD])
    assert result.exit_code != 0
    assert PASSWORD not in result.output


def test_missing_database_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDSCOPE_DATABASE_URL", raising=False)
    result = CliRunner().invoke(app, ["create-user", "test-cli-user"])
    assert result.exit_code == 1 and "CLOUDSCOPE_DATABASE_URL" in result.output


def test_database_failure_does_not_expose_exception_or_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUDSCOPE_DATABASE_URL", "postgresql+psycopg://localhost/test")
    factory = Mock(side_effect=OperationalError(None, None, Exception("private-error-placeholder")))
    monkeypatch.setattr("cloudscope.cli.create_db_engine", factory)
    result = CliRunner().invoke(
        app, ["create-user", "test-cli-user"], input=f"{PASSWORD}\n{PASSWORD}\n"
    )
    assert result.exit_code == 1
    assert "Check database configuration" in result.output
    assert "private-error-placeholder" not in result.output
    assert PASSWORD not in result.output


def test_create_user_with_real_engine(
    migrated_engine: Engine, database_url: URL, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "CLOUDSCOPE_DATABASE_URL", database_url.render_as_string(hide_password=False)
    )
    username = "test-cli-full-connection"
    try:
        result = CliRunner().invoke(
            app, ["create-user", username], input=f"{PASSWORD}\n{PASSWORD}\n"
        )
        assert result.exit_code == 0, result.output
        with Session(migrated_engine) as session:
            user = session.scalars(select(User).where(User.username == username)).one()
            assert verify_password(PASSWORD, user.password_hash)
    finally:
        with Session(migrated_engine) as session, session.begin():
            session.execute(delete(User).where(User.username == username))


def test_hash_failure_does_not_expose_verifier_details(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDSCOPE_DATABASE_URL", "postgresql+psycopg://localhost/test")
    monkeypatch.setattr(
        "cloudscope.cli.hash_password", Mock(side_effect=HashingError("private-error-placeholder"))
    )
    result = CliRunner().invoke(
        app, ["create-user", "test-cli-user"], input=f"{PASSWORD}\n{PASSWORD}\n"
    )
    assert result.exit_code == 1
    assert "Could not hash password" in result.output
    assert "private-error-placeholder" not in result.output and PASSWORD not in result.output
