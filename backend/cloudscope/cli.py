"""Command-line entry point for Cloudscope services."""

import typer
import uvicorn

app = typer.Typer(no_args_is_help=True)


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
