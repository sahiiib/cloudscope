"""Authenticated network inventory and database-only association resolution."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import ColumnElement, func, or_, select

from cloudscope.api.network_links import associations
from cloudscope.auth.deps import current_user, get_auth
from cloudscope.auth.sessions import AuthService
from cloudscope.db.models import Account, ElasticIP, NetworkScan

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
Auth = Annotated[AuthService, Depends(get_auth)]
FIELDS = (
    "provider",
    "account_id",
    "region",
    "allocation_id",
    "public_ip",
    "name",
    "status",
    "associated_type",
    "associated_id",
    "private_ip",
    "network_interface_id",
    "bandwidth",
    "charge_type",
    "tags",
    "last_observed",
    "present",
)


def item(
    eip: ElasticIP, account: Account, association: dict[str, object] | None, detail: bool = False
) -> dict[str, object]:
    return {
        **{field: getattr(eip, field) for field in FIELDS},
        "account_name": account.name,
        "account_alias": account.cloud_alias,
        "association": association,
        **({"raw": eip.raw, "first_seen": eip.first_seen} if detail else {}),
    }


@router.get("/elastic-ips")
def inventory(
    auth: Auth,
    q: Annotated[str, Query(max_length=500)] = "",
    provider: Literal["aws", "alibaba"] | None = None,
    account_id: str | None = None,
    region: str | None = None,
    status: str | None = None,
    associated_type: str | None = None,
    include_missing: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, object]:
    conditions: list[ColumnElement[bool]] = [Account.deleted.is_(False)]
    if not include_missing:
        conditions.append(ElasticIP.present.is_(True))
    for field, value in (
        ("provider", provider),
        ("account_id", account_id),
        ("region", region),
        ("status", status),
        ("associated_type", associated_type),
    ):
        if value is not None:
            conditions.append(getattr(ElasticIP, field) == value)
    if q.strip():
        conditions.append(
            or_(
                *(
                    func.lower(column).contains(q.strip().lower(), autoescape=True)
                    for column in (
                        ElasticIP.public_ip,
                        ElasticIP.private_ip,
                        ElasticIP.allocation_id,
                        ElasticIP.name,
                        ElasticIP.associated_id,
                        Account.name,
                        Account.cloud_alias,
                        Account.account_id,
                    )
                )
            )
        )
    query = select(ElasticIP, Account).join(Account).where(*conditions)
    with auth.sessions() as session:
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.execute(
            query.order_by(ElasticIP.public_ip, ElasticIP.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        targets = associations(session, [eip for eip, _ in rows])
        return {
            "items": [item(eip, account, targets[eip.id]) for eip, account in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/network/scans")
def scans(auth: Auth, request: Request) -> dict[str, object]:
    with auth.sessions() as session:
        rows = session.scalars(
            select(NetworkScan)
            .join(Account)
            .where(Account.deleted.is_(False))
            .order_by(
                NetworkScan.provider,
                NetworkScan.account_id,
                NetworkScan.region,
                NetworkScan.resource_type,
            )
        ).all()
        return {
            "enabled": request.app.state.network_enabled,
            "items": [
                {
                    field: getattr(row, field)
                    for field in (
                        "provider",
                        "account_id",
                        "region",
                        "resource_type",
                        "status",
                        "error",
                        "last_attempt",
                        "last_success",
                    )
                }
                for row in rows
            ],
        }


@router.get("/elastic-ips/{provider}/{account_id}/{region}/{allocation_id}")
def detail(
    auth: Auth,
    provider: Literal["aws", "alibaba"],
    account_id: str,
    region: str,
    allocation_id: str,
) -> dict[str, object]:
    with auth.sessions() as session:
        row = session.execute(
            select(ElasticIP, Account)
            .join(Account)
            .where(
                ElasticIP.provider == provider,
                ElasticIP.account_id == account_id,
                ElasticIP.region == region,
                ElasticIP.allocation_id == allocation_id,
                Account.deleted.is_(False),
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(404, "Elastic IP not found")
        return item(*row, associations(session, [row[0]])[row[0].id], detail=True)
