from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cloudscope.cli import app


@pytest.mark.parametrize(
    ("args", "env", "host", "port"),
    [
        ([], {}, "127.0.0.1", 8000),
        (["--host", "0.0.0.0", "--port", "9000"], {}, "0.0.0.0", 9000),
        ([], {"CLOUDSCOPE_API_HOST": "0.0.0.0", "CLOUDSCOPE_API_PORT": "9000"}, "0.0.0.0", 9000),
        (
            ["--host", "127.0.0.1", "--port", "8001"],
            {"CLOUDSCOPE_API_HOST": "0.0.0.0", "CLOUDSCOPE_API_PORT": "9000"},
            "127.0.0.1",
            8001,
        ),
    ],
)
def test_api_command(
    args: list[str], env: dict[str, str], host: str, port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDSCOPE_FORWARDED_ALLOW_IPS", raising=False)
    monkeypatch.delenv("CLOUDSCOPE_API_HOST", raising=False)
    monkeypatch.delenv("CLOUDSCOPE_API_PORT", raising=False)
    with patch("cloudscope.cli.uvicorn.run") as run:
        result = CliRunner().invoke(app, ["api", *args], env=env)

    assert result.exit_code == 0, result.output
    run.assert_called_once_with(
        "cloudscope.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], "10.0.0.0/24"),
        (["--forwarded-allow-ips", "127.0.0.1,10.0.1.0/24"], "127.0.0.1,10.0.1.0/24"),
    ],
)
def test_api_proxy_trust_env_and_cli_precedence(
    args: list[str], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDSCOPE_FORWARDED_ALLOW_IPS", "10.0.0.0/24")
    with patch("cloudscope.cli.uvicorn.run") as run:
        result = CliRunner().invoke(app, ["api", *args])
    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["proxy_headers"] is True
    assert run.call_args.kwargs["forwarded_allow_ips"] == expected
