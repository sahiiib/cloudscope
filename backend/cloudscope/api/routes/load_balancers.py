"""Authenticated, paginated read-only load-balancer inventory."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import ColumnElement, func, or_, select

from cloudscope.auth.deps import current_user, get_auth
from cloudscope.auth.sessions import AuthService
from cloudscope.db.models import Account, LoadBalancer, LoadBalancerScan

router = APIRouter(prefix="/api/load-balancers", dependencies=[Depends(current_user)])
Auth = Annotated[AuthService, Depends(get_auth)]
FIELDS = (
    "provider",
    "account_id",
    "region",
    "family",
    "load_balancer_id",
    "name",
    "kind",
    "state",
    "scheme",
    "addresses",
    "vpc_id",
    "zones",
    "tags",
    "last_observed",
    "present",
)


def item(lb: LoadBalancer, account: Account, detail: bool = False) -> dict[str, object]:
    return {
        **{field: getattr(lb, field) for field in FIELDS},
        "account_name": account.name,
        "account_alias": account.cloud_alias,
        **({"raw": lb.raw, "first_seen": lb.first_seen} if detail else {}),
    }


@router.get("")
def inventory(
    auth: Auth,
    q: Annotated[str, Query(max_length=500)] = "",
    provider: Literal["aws", "alibaba"] | None = None,
    account_id: str | None = None,
    region: str | None = None,
    kind: str | None = None,
    include_missing: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, object]:
    conditions: list[ColumnElement[bool]] = []
    if not include_missing:
        conditions.append(LoadBalancer.present.is_(True))
    for field, value in (
        ("provider", provider),
        ("account_id", account_id),
        ("region", region),
        ("kind", kind),
    ):
        if value is not None:
            conditions.append(getattr(LoadBalancer, field) == value)
    if q.strip():
        conditions.append(
            or_(
                *(
                    func.lower(column).contains(q.strip().lower(), autoescape=True)
                    for column in (
                        LoadBalancer.name,
                        LoadBalancer.load_balancer_id,
                        Account.name,
                        Account.cloud_alias,
                        Account.account_id,
                        LoadBalancer.vpc_id,
                    )
                ),
                func.lower(func.array_to_string(LoadBalancer.addresses, " ")).contains(
                    q.strip().lower(), autoescape=True
                ),
            )
        )
    query = select(LoadBalancer, Account).join(Account).where(*conditions)
    with auth.sessions() as session:
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.execute(
            query.order_by(LoadBalancer.name, LoadBalancer.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [item(lb, account) for lb, account in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/scans")
def scans(auth: Auth, request: Request) -> dict[str, object]:
    with auth.sessions() as session:
        rows = session.scalars(
            select(LoadBalancerScan).order_by(
                LoadBalancerScan.provider,
                LoadBalancerScan.account_id,
                LoadBalancerScan.region,
                LoadBalancerScan.family,
            )
        ).all()
        return {
            "enabled": request.app.state.load_balancers_enabled,
            "items": [
                {
                    field: getattr(row, field)
                    for field in (
                        "provider",
                        "account_id",
                        "region",
                        "family",
                        "status",
                        "error",
                        "last_attempt",
                        "last_success",
                    )
                }
                for row in rows
            ],
        }


@router.get("/{provider}/{account_id}/{region}/{family}/{load_balancer_id:path}")
def detail(
    auth: Auth,
    provider: Literal["aws", "alibaba"],
    account_id: str,
    region: str,
    family: str,
    load_balancer_id: str,
) -> dict[str, object]:
    with auth.sessions() as session:
        row = session.execute(
            select(LoadBalancer, Account)
            .join(Account)
            .where(
                LoadBalancer.provider == provider,
                LoadBalancer.account_id == account_id,
                LoadBalancer.region == region,
                LoadBalancer.family == family,
                LoadBalancer.load_balancer_id == load_balancer_id,
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Load balancer not found")
        return item(*row, detail=True)
