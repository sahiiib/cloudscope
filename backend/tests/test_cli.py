from unittest.mock import patch

from typer.testing import CliRunner

from cloudscope.cli import app


def test_api_command() -> None:
    with patch("cloudscope.cli.uvicorn.run") as run:
        result = CliRunner().invoke(app, ["api"])

    assert result.exit_code == 0, result.output
    run.assert_called_once_with(
        "cloudscope.api.app:create_app", factory=True, host="127.0.0.1", port=8000
    )
