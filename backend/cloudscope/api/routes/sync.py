"""Collection history and administrator-triggered background collection."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from cloudscope.api.routes.instances import Auth
from cloudscope.auth.deps import current_user, require_admin, require_csrf
from cloudscope.collector.manual import (
    ManualSync,
    SyncAccountDisabled,
    SyncAccountNotFound,
    SyncAlreadyRunning,
    SyncConfigError,
)
from cloudscope.db.models import SyncResult, SyncRun, User

logger = logging.getLogger(__name__)


class SyncScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["aws", "alibaba"]
    account_id: str = Field(min_length=1, max_length=64, pattern=r"^[0-9]+$")


router = APIRouter(prefix="/api/sync/runs", dependencies=[Depends(current_user)])


def summary(run: SyncRun) -> dict[str, object]:
    return {
        **{
            field: getattr(run, field)
            for field in (
                "id",
                "started_at",
                "finished_at",
                "trigger",
                "status",
                "instances_seen",
                "cancel_requested_at",
            )
        },
        "scope": {"provider": run.scope_provider, "account_id": run.scope_account_id}
        if run.scope_account_id is not None
        else None,
    }


@router.get("")
def runs(auth: Auth, limit: Annotated[int, Query(ge=1, le=500)] = 20) -> list[dict[str, object]]:
    with auth.sessions() as session:
        return [
            summary(run)
            for run in session.scalars(
                select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(limit)
            )
        ]


@router.get("/{id}")
def run_detail(id: int, auth: Auth) -> dict[str, object]:
    with auth.sessions() as session:
        run = session.get(SyncRun, id)
        if run is None:
            raise HTTPException(404, "Sync run not found")
        results = session.scalars(
            select(SyncResult)
            .where(SyncResult.run_id == id)
            .order_by(SyncResult.provider, SyncResult.account_id, SyncResult.region)
        )
        return {
            **summary(run),
            "results": [
                {
                    field: getattr(result, field)
                    for field in (
                        "provider",
                        "account_id",
                        "region",
                        "status",
                        "instances_seen",
                        "error",
                        "duration_ms",
                    )
                }
                for result in results
            ],
        }


@router.post("", status_code=202, dependencies=[Depends(require_admin), Depends(require_csrf)])
def start_run(request: Request, scope: SyncScope | None = None) -> dict[str, str]:
    service = cast(ManualSync | None, getattr(request.app.state, "manual_sync", None))
    if service is None:
        raise HTTPException(503, "Collection unavailable")
    try:
        if scope is None:
            service.start()
        else:
            service.start(provider=scope.provider, account_id=scope.account_id)
    except SyncAccountNotFound:
        raise HTTPException(404, "Account not found") from None
    except SyncAccountDisabled:
        raise HTTPException(409, "Account is disabled") from None
    except SyncAlreadyRunning:
        raise HTTPException(409, "Another collection is running") from None
    except SyncConfigError:
        raise HTTPException(503, "Collection unavailable") from None
    return {"status": "accepted"}


@router.post("/{id}/cancel", status_code=202, dependencies=[Depends(require_csrf)])
def cancel_run(
    id: int, auth: Auth, actor: Annotated[User, Depends(require_admin)]
) -> dict[str, str]:
    with auth.sessions.begin() as session:
        run = session.get(SyncRun, id, with_for_update=True)
        if run is None:
            raise HTTPException(404, "Sync run not found")
        if run.status != "running":
            raise HTTPException(409, "Sync run is not running")
        if run.cancel_requested_at is None:
            run.cancel_requested_at = datetime.now(UTC)
    logger.info("event=sync_cancel_requested actor=%s run_id=%s", actor.id, id)
    return {"status": "accepted"}
