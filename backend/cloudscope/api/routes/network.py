"""Authenticated network inventory and database-only association resolution."""

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from cloudscope.auth.deps import current_user, get_auth
from cloudscope.auth.sessions import AuthService
from cloudscope.db.models import Account, ElasticIP, Instance, LoadBalancer, NetworkScan

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


def resource_link(prefix: str, *identity: str) -> str:
    return "/" + prefix + "/" + "/".join(quote(part, safe="") for part in identity)


def association(session: Session, eip: ElasticIP) -> dict[str, object] | None:
    if eip.status == "available":
        return None
    kind, resource_id = eip.associated_type, eip.associated_id
    scope = (eip.provider, eip.account_id, eip.region)
    if eip.provider == "aws" and kind in (None, "network_interface"):
        lb = session.scalar(
            select(LoadBalancer)
            .where(
                LoadBalancer.provider == eip.provider,
                LoadBalancer.account_id == eip.account_id,
                LoadBalancer.region == eip.region,
                LoadBalancer.present.is_(True),
                LoadBalancer.family == "elbv2",
                LoadBalancer.kind == "network",
                LoadBalancer.raw.contains(
                    {
                        "AvailabilityZones": [
                            {"LoadBalancerAddresses": [{"AllocationId": eip.allocation_id}]}
                        ]
                    }
                ),
            )
            .order_by(LoadBalancer.id)
            .limit(1)
        )
        if lb is not None:
            return {
                "type": "load_balancer",
                "id": lb.load_balancer_id,
                "link": resource_link("load-balancers", *scope, lb.family, lb.load_balancer_id),
            }
    link: str | None = None
    if kind == "instance" and resource_id:
        present = session.scalar(
            select(Instance.id).where(
                Instance.provider == eip.provider,
                Instance.account_id == eip.account_id,
                Instance.region == eip.region,
                Instance.instance_id == resource_id,
                Instance.present.is_(True),
            )
        )
        if present is not None:
            link = resource_link("instances", *scope, resource_id)
    elif kind == "load_balancer" and resource_id:
        lb = session.scalar(
            select(LoadBalancer).where(
                LoadBalancer.provider == eip.provider,
                LoadBalancer.account_id == eip.account_id,
                LoadBalancer.region == eip.region,
                LoadBalancer.load_balancer_id == resource_id,
                LoadBalancer.family == "clb",
                LoadBalancer.present.is_(True),
            )
        )
        if lb is not None:
            link = resource_link("load-balancers", *scope, lb.family, resource_id)
    return {"type": kind, "id": resource_id, "link": link}


def item(
    session: Session, eip: ElasticIP, account: Account, detail: bool = False
) -> dict[str, object]:
    return {
        **{field: getattr(eip, field) for field in FIELDS},
        "account_name": account.name,
        "account_alias": account.cloud_alias,
        "association": association(session, eip),
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
        return {
            "items": [item(session, eip, account) for eip, account in rows],
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
        return item(session, *row, detail=True)
