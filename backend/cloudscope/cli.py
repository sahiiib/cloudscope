"""Command-line entry point for Cloudscope services."""

import os

import typer
import uvicorn
from argon2.exceptions import HashingError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from cloudscope.auth.passwords import hash_password
from cloudscope.db.models import User
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
