import os
from pathlib import Path

import pytest
import yaml
from cryptography.fernet import Fernet
from pydantic import ValidationError

from cloudscope.config import AccountsConfigError, Settings, load_accounts


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("CLOUDSCOPE_"):
            monkeypatch.delenv(key)


@pytest.fixture
def configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CLOUDSCOPE_DATABASE_URL",
        "postgresql+psycopg://cloudscope:cloudscope@localhost:5432/cloudscope",
    )
    monkeypatch.setenv("CLOUDSCOPE_SECRET_KEY", Fernet.generate_key().decode())


def test_settings_defaults(configured_environment: None) -> None:
    settings = Settings()
    assert settings.accounts_file == Path("config/accounts.yaml")
    assert settings.session_ttl_hours == 12
    assert settings.cookie_secure is True
    assert settings.collect_concurrency == 8
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.database_url.get_secret_value() == os.environ["CLOUDSCOPE_DATABASE_URL"]
    assert settings.secret_key.get_secret_value() == os.environ["CLOUDSCOPE_SECRET_KEY"]
    assert os.environ["CLOUDSCOPE_SECRET_KEY"] not in repr(settings)
    assert os.environ["CLOUDSCOPE_DATABASE_URL"] not in repr(settings)
    assert os.environ["CLOUDSCOPE_SECRET_KEY"] not in settings.model_dump_json()
    assert os.environ["CLOUDSCOPE_DATABASE_URL"] not in settings.model_dump_json()


def test_settings_environment_overrides(
    configured_environment: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLOUDSCOPE_ACCOUNTS_FILE", str(tmp_path / "accounts.yaml"))
    monkeypatch.setenv("CLOUDSCOPE_SESSION_TTL_HOURS", "24")
    monkeypatch.setenv("CLOUDSCOPE_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDSCOPE_COLLECT_CONCURRENCY", "3")
    monkeypatch.setenv("CLOUDSCOPE_API_HOST", "0.0.0.0")
    monkeypatch.setenv("CLOUDSCOPE_API_PORT", "9000")
    settings = Settings()
    assert settings.accounts_file == tmp_path / "accounts.yaml"
    assert settings.session_ttl_hours == 24
    assert settings.cookie_secure is False
    assert settings.collect_concurrency == 3
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 9000


@pytest.mark.parametrize("field", ["DATABASE_URL", "SECRET_KEY"])
def test_required_settings(
    configured_environment: None, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.delenv(f"CLOUDSCOPE_{field}")
    with pytest.raises(ValidationError, match=field.lower()):
        Settings()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("SESSION_TTL_HOURS", "0"),
        ("COLLECT_CONCURRENCY", "-1"),
        ("API_PORT", "0"),
        ("API_PORT", "65536"),
        ("API_HOST", " "),
        ("COOKIE_SECURE", "invalid"),
        ("SECRET_KEY", "invalid-fernet-placeholder"),
        ("DATABASE_URL", "invalid-url-placeholder"),
        ("DATABASE_URL", "sqlite:///test.db"),
        ("DATABASE_URL", "postgresql+psycopg://localhost"),
        ("DATABASE_URL", "postgresql+psycopg://localhost:invalid/cloudscope"),
    ],
)
def test_invalid_settings_hide_inputs(
    configured_environment: None, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(f"CLOUDSCOPE_{field}", value)
    with pytest.raises(ValidationError) as error:
        Settings()
    assert field.lower() in str(error.value)
    assert "input_value" not in str(error.value)
    assert os.environ["CLOUDSCOPE_SECRET_KEY"] not in str(error.value)
    assert os.environ["CLOUDSCOPE_DATABASE_URL"] not in str(error.value)


def test_settings_do_not_implicitly_read_dotenv(
    configured_environment: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("CLOUDSCOPE_API_PORT=9000\n")
    assert Settings().api_port == 8000


def write_accounts(tmp_path: Path, accounts: list[dict[str, object]]) -> Path:
    path = tmp_path / "accounts.yaml"
    path.write_text(yaml.safe_dump({"accounts": accounts}))
    return path


def account(**overrides: object) -> dict[str, object]:
    return {
        "provider": "aws",
        "account_id": "111111111111",
        "name": "test-account",
        "regions": "all",
        **overrides,
    }


def test_load_example_accounts() -> None:
    path = Path(__file__).resolve().parents[2] / "config/accounts.example.yaml"
    accounts = load_accounts(path)
    assert len(accounts) == 4
    assert accounts[0].regions == "all"
    assert accounts[0].role_arn is None
    assert accounts[1].regions == ["eu-central-1", "us-east-1"]
    assert accounts[1].external_id == "cloudscope"
    assert accounts[2].provider == "alibaba"
    assert accounts[3].role_arn is not None


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"provider": "unknown"}, "provider"),
        ({"regions": []}, "regions"),
        ({"regions": [""]}, "regions"),
        ({"regions": ["   "]}, "regions"),
        ({"regions": "us-east-1"}, "regions"),
        ({"account_id": 111111111111}, "account_id"),
        ({"role_arn": ""}, "role_arn"),
        ({"extra_field": "unexpected-value-placeholder"}, "extra_field"),
    ],
)
def test_invalid_account_names_entry(
    tmp_path: Path, overrides: dict[str, object], field: str
) -> None:
    path = write_accounts(
        tmp_path,
        [account(), account(**{"account_id": "222222222222", "name": "bad-entry", **overrides})],
    )
    with pytest.raises(AccountsConfigError) as error:
        load_accounts(path)
    message = str(error.value)
    assert "bad-entry" in message
    assert f"accounts.1.{field}" in message
    assert "unexpected-value-placeholder" not in message


def test_duplicate_account_names_both_entries(tmp_path: Path) -> None:
    path = write_accounts(tmp_path, [account(name="first-entry"), account(name="duplicate-entry")])
    with pytest.raises(AccountsConfigError) as error:
        load_accounts(path)
    assert "duplicate account aws/111111111111" in str(error.value)
    assert "first-entry" in str(error.value)
    assert "duplicate-entry" in str(error.value)


def test_same_account_id_in_different_providers_is_valid(tmp_path: Path) -> None:
    path = write_accounts(tmp_path, [account(), account(provider="alibaba")])
    assert len(load_accounts(path)) == 2


def test_empty_account_list_is_valid(tmp_path: Path) -> None:
    assert load_accounts(write_accounts(tmp_path, [])) == []


@pytest.mark.parametrize("content", ["", "[]", "accounts: {}", "accounts:\n  - not-an-object"])
def test_invalid_file_structure(tmp_path: Path, content: str) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(content)
    with pytest.raises(AccountsConfigError, match="Invalid accounts file"):
        load_accounts(path)


@pytest.mark.parametrize("content", ["accounts: [", "!!python/object:builtins.object {}"])
def test_invalid_or_unsafe_yaml(tmp_path: Path, content: str) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(content)
    with pytest.raises(AccountsConfigError, match="Invalid YAML"):
        load_accounts(path)


def test_missing_accounts_file(tmp_path: Path) -> None:
    with pytest.raises(AccountsConfigError, match="Cannot read accounts file"):
        load_accounts(tmp_path / "missing.yaml")
