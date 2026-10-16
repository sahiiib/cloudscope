"""Configured accounts and present inventory counts."""

import asyncio
import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudscope.api.account_schema import AdoptAccount, CreateAccount, PatchAccount
from cloudscope.api.routes.instances import Auth
from cloudscope.auth.deps import current_user, require_admin, require_csrf
from cloudscope.collector.access import AccessResult, AccountAccess, test_connection
from cloudscope.collector.errors import log_account_id
from cloudscope.collector.manual import COLLECTION_LOCK_KEY
from cloudscope.config import AccountConfig
from cloudscope.credentials import CredentialError, Credentials, CredentialStore
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
            .where(Account.deleted.is_(False))
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
                "excluded_regions",
            )
        },
        "instance_count": count,
        "connection_mode": account.connection_mode,
        "credentials_configured": account.credential_reference is not None,
        "configuration_version": account.configuration_version,
    }


def target(session: Session, provider: str, account_id: str) -> Account:
    account = session.get(Account, (provider, account_id), with_for_update=True)
    if account is None or account.deleted:
        raise HTTPException(404, "Account not found")
    return account


def collection_lock(session: Session) -> None:
    if not session.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": COLLECTION_LOCK_KEY}
    ):
        raise HTTPException(409, "Collection is running; retry after it finishes")


def version_check(account: Account, expected: int | None) -> None:
    if expected is not None and account.configuration_version != expected:
        raise HTTPException(409, "Account changed; refresh and retry")


@router.get("/capabilities")
def capabilities(request: Request, actor: Admin) -> dict[str, bool]:
    return {
        "dedicated_credentials": bool(
            getattr(request.app.state, "dedicated_credentials_enabled", False)
        )
    }


async def prepare_credentials(
    request: Request,
    settings: CreateAccount,
    keys: Credentials | None,
    current_reference: str | None = None,
) -> str | None:
    if settings.connection_mode == "runtime":
        return None
    if not getattr(request.app.state, "dedicated_credentials_enabled", False):
        raise HTTPException(409, "Dedicated credentials are disabled by the operator")
    if keys is None:
        if current_reference is None:
            raise HTTPException(422, "Enter an access key ID and secret access key")
        return current_reference
    store = cast(CredentialStore, request.app.state.credential_store)
    try:
        reference = await asyncio.to_thread(
            store.create, settings.provider, settings.account_id, keys
        )
    except CredentialError:
        raise HTTPException(
            503, "Credential store unavailable; previous connection is unchanged"
        ) from None
    config = AccountConfig.model_validate(
        {
            **settings.model_dump(exclude={"credentials", "enabled"}),
            "credential_reference": reference,
        }
    )
    service = cast(AccountAccess, request.app.state.account_access)
    access = await service.check(config)
    if not access.get("ok"):
        # Immutable unreferenced versions are retained for operator cleanup, not deleted.
        raise HTTPException(422, "Access validation failed: " + access.get("error", "Unavailable"))
    return reference


@router.post("/test-connection", dependencies=[Depends(require_csrf)])
async def test_unsaved_account(
    body: CreateAccount, request: Request, actor: Admin
) -> dict[str, object]:
    if body.connection_mode == "dedicated":
        if not getattr(request.app.state, "dedicated_credentials_enabled", False):
            raise HTTPException(409, "Dedicated credentials are disabled by the operator")
        if body.credentials is None:
            raise HTTPException(422, "Enter an access key ID and secret access key")
    config = AccountConfig.model_validate(
        {
            **body.model_dump(exclude={"credentials", "enabled"}),
            "credential_reference": "unsaved-test" if body.connection_mode == "dedicated" else None,
        }
    )
    result = await test_connection(config, body.credentials)
    logger.info(
        "event=account_test_connection actor=%s provider=%s account_id=%s ok=%s",
        actor.id,
        body.provider,
        body.account_id,
        result["ok"],
    )
    if result["ok"]:
        return {"ok": True, "regions": result["region_ids"]}
    return {"ok": False, "error": result["error"]}


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
async def create_account(
    body: CreateAccount, request: Request, auth: Auth, actor: Admin
) -> dict[str, object]:
    reference = await prepare_credentials(request, body, body.credentials)
    try:
        with auth.sessions.begin() as session:
            collection_lock(session)
            account = session.get(Account, (body.provider, body.account_id), with_for_update=True)
            if account is not None:
                if not account.deleted:
                    raise HTTPException(409, "Account already exists")
                for key, value in body.model_dump(exclude={"credentials"}).items():
                    setattr(account, key, value)
                account.deleted = False
                account.source = "ui"
                account.credential_reference = reference
                account.configuration_version += 1
            else:
                account = Account(
                    **body.model_dump(exclude={"credentials"}),
                    source="ui",
                    credential_reference=reference,
                )
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
async def patch_account(
    provider: str, account_id: str, body: PatchAccount, request: Request, auth: Auth, actor: Admin
) -> dict[str, object]:
    with auth.sessions() as session:
        old = target(session, provider, account_id)
        if old.source != "ui":
            raise HTTPException(409, "Managed by accounts.yaml; choose Manage in web first")
        observed_version = old.configuration_version
        version_check(old, body.expected_version)
        changes = body.model_dump(exclude_unset=True, exclude={"credentials", "expected_version"})
        try:
            config = CreateAccount.model_validate(
                {
                    **{
                        key: getattr(old, key)
                        for key in CreateAccount.model_fields
                        if key != "credentials"
                    },
                    **changes,
                    "credentials": body.credentials,
                }
            )
        except ValidationError:
            raise HTTPException(422, "Check the account connection fields") from None
        if (
            body.credentials is not None or "connection_mode" in changes
        ) and body.expected_version is None:
            raise HTTPException(422, "Connection changes require the current configuration version")
        reference = old.credential_reference
    reference = await prepare_credentials(request, config, body.credentials, reference)
    with auth.sessions.begin() as session:
        collection_lock(session)
        account = target(session, provider, account_id)
        version_check(account, observed_version)
        if account.source != "ui":
            raise HTTPException(409, "Managed by accounts.yaml")
        changes = body.model_dump(exclude_unset=True, exclude={"credentials", "expected_version"})
        changes["credential_reference"] = reference
        try:
            CreateAccount.model_validate(
                {
                    **{
                        key: getattr(account, key)
                        for key in CreateAccount.model_fields
                        if key != "credentials"
                    },
                    **{
                        key: value
                        for key, value in changes.items()
                        if key != "credential_reference"
                    },
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
        if changed:
            account.configuration_version += 1
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


@router.post("/{provider}/{account_id}/adopt", dependencies=[Depends(require_csrf)])
def adopt_account(
    provider: str, account_id: str, body: AdoptAccount, auth: Auth, actor: Admin
) -> dict[str, object]:
    with auth.sessions.begin() as session:
        collection_lock(session)
        account = target(session, provider, account_id)
        version_check(account, body.expected_version)
        if account.source != "file":
            raise HTTPException(409, "Already managed in web; refresh the account list")
        account.source = "ui"
        account.configuration_version += 1
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
    logger.info(
        "event=account_adopt actor=%s provider=%s account_id=%s",
        actor.id,
        provider,
        log_account_id(account_id),
    )
    return result


@router.post("/{provider}/{account_id}/test", dependencies=[Depends(require_csrf)])
async def test_account(
    provider: str, account_id: str, request: Request, auth: Auth, actor: Admin
) -> AccessResult:
    with auth.sessions() as session:
        account = session.get(Account, (provider, account_id))
        if account is None or account.deleted:
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


@router.delete("/{provider}/{account_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_account(
    provider: str, account_id: str, body: AdoptAccount, auth: Auth, actor: Admin
) -> Response:
    with auth.sessions.begin() as session:
        collection_lock(session)
        account = target(session, provider, account_id)
        version_check(account, body.expected_version)
        # Keep a disabled UI tombstone so accounts.yaml cannot recreate the account.
        account.source = "ui"
        account.enabled = False
        account.deleted = True
        account.configuration_version += 1
    logger.info(
        "event=account_delete actor=%s provider=%s account_id=%s",
        actor.id,
        provider,
        log_account_id(account_id),
    )
    return Response(status_code=204)
