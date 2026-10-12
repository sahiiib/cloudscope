"""Strict validation of administrator-supplied, non-secret account settings."""

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationInfo, field_validator


class CreateAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)

    provider: Literal["aws", "alibaba"]
    account_id: str
    name: str
    regions: Literal["all"] | list[str]
    role_arn: str | None = None
    external_id: str | None = None
    enabled: StrictBool = True

    @field_validator("account_id")
    @classmethod
    def valid_id(cls, value: str, info: ValidationInfo) -> str:
        length = 12 if info.data.get("provider") == "aws" else 16
        if not re.fullmatch(rf"[0-9]{{{length}}}", value):
            raise ValueError("Invalid account ID length or digits")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if (
            not 1 <= len(value) <= 64
            or value != value.strip()
            or any(unicodedata.category(char).startswith("C") for char in value)
        ):
            raise ValueError(
                "Name must be 1–64 characters without surrounding whitespace or controls"
            )
        return value

    @field_validator("regions")
    @classmethod
    def valid_regions(cls, value: Literal["all"] | list[str]) -> Literal["all"] | list[str]:
        if isinstance(value, list) and (
            not value
            or len(set(value)) != len(value)
            or any(not re.fullmatch(r"[a-z0-9-]{2,32}", region) for region in value)
        ):
            raise ValueError("Use all or a nonempty list of unique region IDs")
        return value

    @field_validator("role_arn")
    @classmethod
    def valid_role(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None:
            prefix = "arn:aws:iam::" if info.data.get("provider") == "aws" else "acs:ram::"
            expected = re.escape(prefix + info.data.get("account_id", "") + ":role/")
            if not re.fullmatch(expected + r"[A-Za-z0-9_+=,.@/-]+", value):
                raise ValueError("Role must match the provider and account ID")
        return value

    @field_validator("external_id")
    @classmethod
    def valid_external_id(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None and (
            info.data.get("provider") != "aws"
            or not re.fullmatch(r"[\w+=,.@:/-]{2,1224}", value, flags=re.ASCII)
        ):
            raise ValueError("External ID is AWS-only and must contain 2–1224 allowed characters")
        return value


class PatchAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)

    name: str | None = None
    regions: Literal["all"] | list[str] | None = None
    role_arn: str | None = None
    external_id: str | None = None
    enabled: StrictBool | None = None

    @field_validator("name", "regions", "enabled")
    @classmethod
    def not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Field cannot be null")
        return value
