"""Command-line entry point for Cloudscope services."""

import os
from collections.abc import Iterable
from enum import StrEnum

import typer
import uvicorn
from argon2.exceptions import HashingError
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from cloudscope.auth.passwords import hash_password
from cloudscope.collector.alibaba import AlibabaProvider
from cloudscope.collector.aws import AWSProvider
from cloudscope.collector.base import Provider
from cloudscope.collector.manual import COLLECTION_LOCK_KEY
from cloudscope.collector.runner import AccountFilterError, SyncRunner
from cloudscope.config import AccountsConfigError, Settings, load_accounts
from cloudscope.db.models import SyncResult, User
from cloudscope.db.session import create_db_engine, create_session_factory

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


@app.callback()
def main() -> None:
    """Manage Cloudscope services."""


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", envvar="CLOUDSCOPE_API_HOST"),
    port: int = typer.Option(8000, envvar="CLOUDSCOPE_API_PORT"),
) -> None:
    """Serve the HTTP API."""
    uvicorn.run("cloudscope.api.app:create_app", factory=True, host=host, port=port)


@app.command()
def create_user(username: str, admin: bool = False) -> None:
    """Create a local user, prompting twice for a hidden password."""
    if not username.strip():
        raise typer.BadParameter("Username cannot be blank", param_hint="username")
    database_url = os.environ.get("CLOUDSCOPE_DATABASE_URL")
    if not database_url:
        typer.echo("Set CLOUDSCOPE_DATABASE_URL before creating a user.", err=True)
        raise typer.Exit(code=1)
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        password_hash = hash_password(password)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    except HashingError:
        typer.echo("Could not hash password.", err=True)
        raise typer.Exit(code=1) from None

    engine = None
    try:
        engine = create_db_engine(database_url)
        factory = create_session_factory(engine)
        with factory.begin() as session:
            session.add(User(username=username, password_hash=password_hash, is_admin=admin))
    except IntegrityError:
        typer.echo("A user with this username already exists.", err=True)
        raise typer.Exit(code=1) from None
    except (SQLAlchemyError, ValueError):
        typer.echo("Could not create user. Check database configuration and migrations.", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if engine is not None:
            engine.dispose()
    typer.echo(f"Created user {username}.")


class CollectTrigger(StrEnum):
    manual = "manual"
    schedule = "schedule"


def collect_providers() -> dict[str, Provider]:
    return {"aws": AWSProvider(), "alibaba": AlibabaProvider()}


def configuration_failure(locations: Iterable[tuple[str | int, ...]]) -> str:
    fields = dict.fromkeys(".".join(map(str, location)) or "accounts" for location in locations)
    return "Configuration invalid: " + ", ".join(fields).encode("unicode_escape").decode("ascii")


@app.command()
def collect(
    account: str | None = typer.Option(None, "--account", help="Scan only this account ID."),
    region: str | None = typer.Option(None, "--region", help="Scan only this configured region."),
    trigger: CollectTrigger = typer.Option(CollectTrigger.manual, "--trigger"),
) -> None:
    """Collect read-only inventory and print per-region results."""
    engine = None
    settings: Settings | None = None
    try:
        settings = Settings()  # type: ignore[call-arg]
        accounts = load_accounts(settings.accounts_file)
        engine = create_db_engine(settings.database_url.get_secret_value())
        factory = create_session_factory(engine)
        # A session-level advisory lock serializes CLI processes across hosts.
        # API/manual callers use this same lock key.
        with engine.connect() as lock:
            lock_key = COLLECTION_LOCK_KEY
            acquired = lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key})
            if not acquired:
                typer.echo("Another collection is running.", err=True)
                raise typer.Exit(1)
            try:
                run = SyncRunner(
                    factory, collect_providers(), concurrency=settings.collect_concurrency
                ).run(
                    accounts,
                    account_id=account,
                    region=region,
                    trigger=trigger.value,
                )
                with factory() as session:
                    results = list(
                        session.scalars(
                            select(SyncResult)
                            .where(SyncResult.run_id == run.id)
                            .order_by(SyncResult.provider, SyncResult.account_id, SyncResult.region)
                        )
                    )
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
    except typer.Exit:
        raise
    except Exception as exc:
        # Only known field locations, our configured path, and class names are
        # diagnostic data. Never render exception text, validation inputs/messages.
        if isinstance(exc, ValidationError):
            message = configuration_failure(
                error["loc"]
                for error in exc.errors(
                    include_input=False, include_context=False, include_url=False
                )
            )
        elif isinstance(exc, FileNotFoundError) or (
            isinstance(exc, AccountsConfigError) and exc.missing_file
        ):
            path = str(settings.accounts_file) if settings is not None else "config/accounts.yaml"
            message = "Accounts file not found: " + path.encode("unicode_escape").decode("ascii")
        elif isinstance(exc, AccountsConfigError) and exc.locations is not None:
            message = configuration_failure(exc.locations)
        elif isinstance(exc, SQLAlchemyError):
            message = f"Database error: {type(exc).__name__}"
        elif isinstance(exc, AccountFilterError):
            message = "Account filter does not match configuration"
        else:
            message = f"Collection failed: {type(exc).__name__}"
        typer.echo(message, err=True)
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()
    typer.echo(f"Run {run.id}: {run.status}; instances_seen={run.instances_seen}")
    typer.echo("PROVIDER\tACCOUNT\tREGION\tSTATUS\tSEEN\tDURATION_MS\tERROR")
    for result in results:
        values = [
            result.provider,
            result.account_id,
            result.region,
            result.status,
            str(result.instances_seen),
            str(result.duration_ms),
            result.error or "-",
        ]
        typer.echo("\t".join(value.encode("unicode_escape").decode("ascii") for value in values))
    if not results and region is not None:
        typer.echo("Region filter matched no scan targets.", err=True)
    raise typer.Exit(1 if run.status == "failed" else 0)
