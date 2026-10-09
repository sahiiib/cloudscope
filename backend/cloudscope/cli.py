"""Command-line entry point for Cloudscope services."""

import typer
import uvicorn

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Manage Cloudscope services."""


@app.command()
def api() -> None:
    """Serve the HTTP API on localhost:8000."""
    uvicorn.run("cloudscope.api.app:create_app", factory=True, host="127.0.0.1", port=8000)
