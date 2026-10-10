"""Collection history and administrator-triggered background collection."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from cloudscope.api.routes.instances import Auth
from cloudscope.auth.deps import current_user, require_admin, require_csrf
from cloudscope.collector.manual import ManualSync, SyncAlreadyRunning, SyncConfigError
from cloudscope.db.models import SyncResult, SyncRun

router = APIRouter(prefix="/api/sync/runs", dependencies=[Depends(current_user)])


def summary(run: SyncRun) -> dict[str, object]:
    return {
        field: getattr(run, field)
        for field in ("id", "started_at", "finished_at", "trigger", "status", "instances_seen")
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
def start_run(request: Request) -> dict[str, str]:
    service = cast(ManualSync | None, getattr(request.app.state, "manual_sync", None))
    if service is None:
        raise HTTPException(503, "Collection unavailable")
    try:
        service.start()
    except SyncAlreadyRunning:
        raise HTTPException(409, "Another collection is running") from None
    except SyncConfigError:
        raise HTTPException(503, "Collection unavailable") from None
    return {"status": "accepted"}
