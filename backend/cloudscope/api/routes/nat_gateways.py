"""Authenticated, paginated read-only NAT gateway inventory."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from cloudscope.auth.deps import current_user, get_auth
from cloudscope.auth.sessions import AuthService
from cloudscope.db.models import Account, NatGateway

router = APIRouter(prefix="/api/nat-gateways", dependencies=[Depends(current_user)])
Auth = Annotated[AuthService, Depends(get_auth)]
FIELDS = (
    "provider",
    "account_id",
    "region",
    "nat_gateway_id",
    "name",
    "connectivity_type",
    "nat_type",
    "network_type",
    "spec",
    "state",
    "addresses",
    "vpc_id",
    "subnet_id",
    "private_ip",
    "tags",
    "last_observed",
    "present",
)


def item(nat: NatGateway, account: Account, detail: bool = False) -> dict[str, object]:
    return {
        **{field: getattr(nat, field) for field in FIELDS},
        "account_name": account.name,
        "account_alias": account.cloud_alias,
        **({"raw": nat.raw, "first_seen": nat.first_seen} if detail else {}),
    }


@router.get("")
def inventory(
    auth: Auth,
    q: Annotated[str, Query(max_length=500)] = "",
    provider: Literal["aws", "alibaba"] | None = None,
    account_id: str | None = None,
    region: str | None = None,
    state: str | None = None,
    include_missing: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, object]:
    conditions: list[ColumnElement[bool]] = [Account.deleted.is_(False)]
    if not include_missing:
        conditions.extend([NatGateway.present.is_(True), func.lower(NatGateway.state) != "deleted"])
    for field, value in (
        ("provider", provider),
        ("account_id", account_id),
        ("region", region),
        ("state", state),
    ):
        if value is not None:
            conditions.append(getattr(NatGateway, field) == value)
    if q.strip():
        address = func.jsonb_array_elements(NatGateway.addresses).table_valued("value")
        address_json = cast(address.c.value, JSONB)
        address_match = (
            select(1)
            .select_from(address)
            .where(
                or_(
                    *(
                        func.lower(address_json[field].astext).contains(
                            q.strip().lower(), autoescape=True
                        )
                        for field in ("public_ip", "private_ip")
                    )
                )
            )
            .correlate(NatGateway)
            .exists()
        )
        conditions.append(
            or_(
                *(
                    func.lower(column).contains(q.strip().lower(), autoescape=True)
                    for column in (
                        NatGateway.name,
                        NatGateway.nat_gateway_id,
                        Account.name,
                        Account.cloud_alias,
                        Account.account_id,
                        NatGateway.vpc_id,
                        NatGateway.private_ip,
                    )
                ),
                address_match,
            )
        )
    query = select(NatGateway, Account).join(Account).where(*conditions)
    with auth.sessions() as session:
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.execute(
            query.order_by(NatGateway.name, NatGateway.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [item(nat, account) for nat, account in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/{provider}/{account_id}/{region}/{nat_gateway_id}")
def detail(
    auth: Auth,
    provider: Literal["aws", "alibaba"],
    account_id: str,
    region: str,
    nat_gateway_id: str,
) -> dict[str, object]:
    with auth.sessions() as session:
        row = session.execute(
            select(NatGateway, Account)
            .join(Account)
            .where(
                NatGateway.provider == provider,
                NatGateway.account_id == account_id,
                NatGateway.region == region,
                NatGateway.nat_gateway_id == nat_gateway_id,
                Account.deleted.is_(False),
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="NAT gateway not found")
        return item(*row, detail=True)
