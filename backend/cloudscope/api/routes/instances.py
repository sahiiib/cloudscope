"""Authenticated inventory search and disjunctive filter facets."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, func, select

from cloudscope.auth.deps import current_user, get_auth
from cloudscope.auth.sessions import AuthService
from cloudscope.db.models import Account, Instance

router = APIRouter(prefix="/api/instances", dependencies=[Depends(current_user)])
Auth = Annotated[AuthService, Depends(get_auth)]
Provider = Literal["aws", "alibaba"]
State = Literal["pending", "running", "stopping", "stopped", "terminated", "unknown"]
Sort = Literal[
    "name",
    "-name",
    "launch_time",
    "-launch_time",
    "last_observed",
    "-last_observed",
    "region",
    "-region",
    "account",
    "-account",
]
LIST_FIELDS = (
    "provider",
    "account_id",
    "region",
    "instance_id",
    "name",
    "state",
    "instance_type",
    "private_ips",
    "public_ips",
    "tags",
    "launch_time",
    "last_observed",
    "present",
)
DETAIL_FIELDS = (
    "zone",
    "vpc_id",
    "subnet_id",
    "key_name",
    "image_id",
    "platform",
    "provider_state",
    "first_seen",
    "details",
    "raw",
)


class Filters:
    def __init__(
        self,
        q: str = "",
        provider: Annotated[list[Provider] | None, Query()] = None,
        account_id: Annotated[list[str] | None, Query()] = None,
        region: Annotated[list[str] | None, Query()] = None,
        state: Annotated[list[State] | None, Query()] = None,
        tag: Annotated[list[str] | None, Query()] = None,
        include_missing: bool = False,
    ) -> None:
        self.q, self.tag, self.include_missing = q, tag or [], include_missing
        self.values = {
            "provider": provider,
            "account_id": account_id,
            "region": region,
            "state": state,
        }

    def conditions(self, omit: str = "") -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if not self.include_missing:
            conditions.append(Instance.present.is_(True))
        if self.q:
            conditions.append(Instance.search_text.contains(self.q.lower(), autoescape=True))
        for field, values in self.values.items():
            if values and field != omit:
                conditions.append(getattr(Instance, field).in_(values))
        for tag in self.tag:
            key, separator, value = tag.partition("=")
            conditions.append(
                Instance.tags.contains({key: value}) if separator else Instance.tags.has_key(key)
            )
        return conditions


def item(instance: Instance, account_name: str, *, detail: bool = False) -> dict[str, object]:
    return {
        "account_name": account_name,
        **{
            field: getattr(instance, field)
            for field in LIST_FIELDS + (DETAIL_FIELDS if detail else ())
        },
    }


@router.get("")
def instances(
    auth: Auth,
    filters: Annotated[Filters, Depends()],
    sort: Sort = "name",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, object]:
    column = {
        "name": Instance.name,
        "launch_time": Instance.launch_time,
        "last_observed": Instance.last_observed,
        "region": Instance.region,
        "account": Account.name,
    }[sort.lstrip("-")]
    order = column.desc() if sort.startswith("-") else column.asc()
    with auth.sessions() as session:
        total = session.scalar(
            select(func.count()).select_from(Instance).where(*filters.conditions())
        )
        rows = session.execute(
            select(Instance, Account.name)
            .join(Account)
            .where(*filters.conditions())
            .order_by(order.nulls_last(), Instance.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return {
            "items": [item(instance, name) for instance, name in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/facets")
def facets(
    auth: Auth, filters: Annotated[Filters, Depends()]
) -> dict[str, list[dict[str, object]]]:
    result = {}
    with auth.sessions() as session:
        for key, field in {
            "providers": "provider",
            "accounts": "account_id",
            "regions": "region",
            "states": "state",
        }.items():
            column = getattr(Instance, field)
            rows = session.execute(
                select(column, func.count())
                .where(*filters.conditions(omit=field))
                .group_by(column)
                .order_by(column)
            )
            result[key] = [{"value": value, "count": count} for value, count in rows]
    return result


@router.get("/{provider}/{account_id}/{region}/{instance_id}")
def instance_detail(
    auth: Auth, provider: Provider, account_id: str, region: str, instance_id: str
) -> dict[str, object]:
    with auth.sessions() as session:
        row = session.execute(
            select(Instance, Account.name)
            .join(Account)
            .where(
                Instance.provider == provider,
                Instance.account_id == account_id,
                Instance.region == region,
                Instance.instance_id == instance_id,
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(404, "Instance not found")
        return item(row[0], row[1], detail=True)
