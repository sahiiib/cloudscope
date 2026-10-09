"""Runtime settings and validated, non-secret account configuration."""

from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from cryptography.fernet import Fernet
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

NonEmptyStr = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]


class Settings(BaseSettings):
    """Read CLOUDSCOPE_* runtime variables; construction has no cloud or DB side effects."""

    model_config = SettingsConfigDict(env_prefix="CLOUDSCOPE_", hide_input_in_errors=True)

    database_url: SecretStr
    secret_key: SecretStr
    api_host: NonEmptyStr = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    accounts_file: Path = Path("config/accounts.yaml")
    session_ttl_hours: int = Field(default=12, gt=0)
    session_max_age_days: int = Field(default=7, gt=0)
    cookie_secure: bool = True
    collect_concurrency: int = Field(default=8, gt=0)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except (ArgumentError, ValueError):
            raise ValueError("must be a postgresql+psycopg database URL") from None
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("must be a postgresql+psycopg URL with a database name")
        return value

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: SecretStr) -> SecretStr:
        try:
            Fernet(value.get_secret_value().encode("utf-8"))
        except (ValueError, TypeError):
            raise ValueError("must be a valid Fernet key") from None
        return value


class AccountConfig(BaseModel):
    """One account, using direct credentials or an optional assumed role."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    provider: Literal["aws", "alibaba"]
    account_id: NonEmptyStr
    name: NonEmptyStr
    regions: Literal["all"] | Annotated[list[NonEmptyStr], Field(min_length=1)]
    role_arn: NonEmptyStr | None = None
    external_id: NonEmptyStr | None = None


class AccountsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    accounts: list[AccountConfig]

    @model_validator(mode="after")
    def unique_accounts(self) -> Self:
        seen: dict[tuple[str, str], str] = {}
        for account in self.accounts:
            key = (account.provider, account.account_id)
            if key in seen:
                raise ValueError(
                    f"duplicate account {account.provider}/{account.account_id}: "
                    f"{account.name!r} duplicates {seen[key]!r}"
                )
            seen[key] = account.name
        return self


class AccountsConfigError(ValueError):
    """An accounts file cannot be read or fails validation."""


def load_accounts(path: str | Path = Path("config/accounts.yaml")) -> list[AccountConfig]:
    """Load safe YAML, reporting entry names and fields without dumping file contents."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
    except (OSError, UnicodeError):
        raise AccountsConfigError(f"Cannot read accounts file {path}") from None
    except yaml.YAMLError:
        raise AccountsConfigError(f"Invalid YAML in accounts file {path}") from None

    try:
        return AccountsConfig.model_validate(data).accounts
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"]) or "accounts"
            if (
                len(error["loc"]) >= 2
                and error["loc"][0] == "accounts"
                and isinstance(error["loc"][1], int)
                and isinstance(data, dict)
                and isinstance(data.get("accounts"), list)
            ):
                entry = data["accounts"][error["loc"][1]]
                if isinstance(entry, dict):
                    name = entry.get("name")
                    if isinstance(name, str):
                        location += f" ({name!r})"
            messages.append(f"{location}: {error['msg']}")
        raise AccountsConfigError(f"Invalid accounts file {path}: " + "; ".join(messages)) from None
