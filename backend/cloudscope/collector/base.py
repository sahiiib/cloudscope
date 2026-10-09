"""Provider contract and database-ready normalized inventory records."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from cloudscope.config import AccountConfig

# Cloud SDK payloads are heterogeneous nested mappings; normalization types the fields we use.
type Payload = dict[str, Any]


@dataclass
class NormalizedInstance:
    provider: Literal["aws", "alibaba"]
    account_id: str
    region: str
    instance_id: str
    state: str
    provider_state: str
    instance_type: str
    private_ips: list[str]
    public_ips: list[str]
    tags: dict[str, str]
    details: Payload
    raw: Payload
    zone: str | None = None
    name: str | None = None
    launch_time: datetime | None = None
    vpc_id: str | None = None
    subnet_id: str | None = None
    key_name: str | None = None
    image_id: str | None = None
    platform: str | None = None


class Provider(Protocol):
    @property
    def name(self) -> Literal["aws", "alibaba"]: ...

    def list_regions(self, account: AccountConfig) -> list[str]: ...

    def scan(self, account: AccountConfig, region: str) -> list[NormalizedInstance]: ...


def unique(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def utc_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def json_payload(value: Payload) -> Payload:
    """Preserve SDK data, converting datetime objects to UTC ISO strings for JSONB."""

    def encode(item: object) -> str:
        if isinstance(item, datetime):
            normalized = utc_datetime(item)
            assert normalized is not None
            return normalized.isoformat()
        raise TypeError(f"Unsupported cloud payload type: {type(item).__name__}")

    result: Payload = json.loads(json.dumps(value, default=encode))
    return result
