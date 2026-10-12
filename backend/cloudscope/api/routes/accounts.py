"""Configured accounts and present inventory counts."""

import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudscope.api.account_schema import CreateAccount, PatchAccount
from cloudscope.api.routes.instances import Auth
from cloudscope.auth.deps import current_user, require_admin, require_csrf
from cloudscope.collector.access import AccessResult, AccountAccess
from cloudscope.collector.errors import log_account_id
from cloudscope.config import AccountConfig
from cloudscope.db.models import Account, Instance, User

logger = logging.getLogger(__name__)
Admin = Annotated[User, Depends(require_admin)]

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
        return [response(account, count) for account, count in rows]


def response(account: Account, count: int = 0) -> dict[str, object]:
    return {
        **{
            field: getattr(account, field)
            for field in (
                "provider",
                "account_id",
                "name",
                "enabled",
                "last_success_at",
                "source",
                "cloud_alias",
                "role_arn",
                "external_id",
                "regions",
            )
        },
        "instance_count": count,
    }


def target(session: Session, provider: str, account_id: str) -> Account:
    account = session.get(Account, (provider, account_id), with_for_update=True)
    if account is None:
        raise HTTPException(404, "Account not found")
    return account


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def create_account(body: CreateAccount, auth: Auth, actor: Admin) -> dict[str, object]:
    try:
        with auth.sessions.begin() as session:
            account = Account(**body.model_dump(), source="ui")
            session.add(account)
            session.flush()
            result = response(account)
    except IntegrityError:
        raise HTTPException(409, "Account already exists") from None
    logger.info(
        "event=account_create actor=%s provider=%s account_id=%s",
        actor.id,
        account.provider,
        account.account_id,
    )
    return result


@router.patch("/{provider}/{account_id}", dependencies=[Depends(require_csrf)])
def patch_account(
    provider: str, account_id: str, body: PatchAccount, auth: Auth, actor: Admin
) -> dict[str, object]:
    with auth.sessions.begin() as session:
        account = target(session, provider, account_id)
        if account.source != "ui":
            raise HTTPException(409, "Managed by accounts.yaml")
        changes = body.model_dump(exclude_unset=True)
        try:
            CreateAccount.model_validate(
                {
                    **{key: getattr(account, key) for key in CreateAccount.model_fields},
                    **changes,
                }
            )
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_context=False, include_url=False)
            raise HTTPException(
                422,
                detail=[
                    {"loc": ["body", *error["loc"]], "msg": error["msg"], "type": error["type"]}
                    for error in errors
                ],
            ) from None
        changed = sorted(key for key, value in changes.items() if getattr(account, key) != value)
        for key in changed:
            setattr(account, key, changes[key])
        session.flush()
        count = (
            session.scalar(
                select(func.count())
                .select_from(Instance)
                .where(
                    Instance.provider == provider,
                    Instance.account_id == account_id,
                    Instance.present.is_(True),
                )
            )
            or 0
        )
        result = response(account, count)
    action = ("enable" if account.enabled else "disable") if changed == ["enabled"] else "update"
    logger.info(
        "event=account_%s actor=%s provider=%s account_id=%s changed=%s",
        action,
        actor.id,
        account.provider,
        account.account_id,
        ",".join(changed),
    )
    return result


@router.post("/{provider}/{account_id}/test", dependencies=[Depends(require_csrf)])
async def test_account(
    provider: str, account_id: str, request: Request, auth: Auth, actor: Admin
) -> AccessResult:
    with auth.sessions() as session:
        account = session.get(Account, (provider, account_id))
        if account is None:
            raise HTTPException(404, "Account not found")
        config = AccountConfig.model_validate(
            {key: getattr(account, key) for key in AccountConfig.model_fields}
        )
    service = cast(AccountAccess, request.app.state.account_access)
    result = await service.check(config)
    logger.info(
        "event=account_test actor=%s provider=%s account_id=%s",
        actor.id,
        config.provider,
        log_account_id(config.account_id),
    )
    return result
