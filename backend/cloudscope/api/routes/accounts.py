"""Configured accounts and present inventory counts."""

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select

from cloudscope.api.routes.instances import Auth
from cloudscope.auth.deps import current_user
from cloudscope.db.models import Account, Instance

router = APIRouter(prefix="/api/accounts", dependencies=[Depends(current_user)])


@router.get("")
def accounts(auth: Auth) -> list[dict[str, object]]:
    with auth.sessions() as session:
        rows = session.execute(
            select(Account, func.count(Instance.id))
            .outerjoin(
                Instance,
                and_(
                    Instance.provider == Account.provider,
                    Instance.account_id == Account.account_id,
                    Instance.present.is_(True),
                ),
            )
            .group_by(Account.provider, Account.account_id)
            .order_by(Account.provider, Account.account_id)
        )
        return [
            {
                **{
                    field: getattr(account, field)
                    for field in ("provider", "account_id", "name", "enabled", "last_success_at")
                },
                "instance_count": count,
            }
            for account, count in rows
        ]
