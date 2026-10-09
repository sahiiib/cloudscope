from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudscope.db.models import Account, Instance, SyncResult, SyncRun, User, UserSession


def add_account(session: Session) -> Account:
    account = Account(provider="aws", account_id="111111111111", name="test-account")
    session.add(account)
    session.flush()
    return account


def instance(**overrides: object) -> Instance:
    return Instance(
        **{
            "provider": "aws",
            "account_id": "111111111111",
            "region": "eu-central-1",
            "instance_id": "i-0123456789abcdef0",
            "state": "running",
            "provider_state": "running",
            "instance_type": "t3.micro",
            **overrides,
        }
    )


def test_insert_and_read_every_model(db_session: Session) -> None:
    add_account(db_session)
    observed = datetime(2026, 1, 2, 12, tzinfo=UTC)
    vm = instance(
        name="Web-1",
        private_ips=["10.0.0.1", "10.0.0.2"],
        public_ips=["192.0.2.1"],
        tags={"Environment": "Testing"},
        details={"cpu": 2, "security_groups": [{"id": "sg-test", "inbound": []}]},
        raw={"InstanceId": "i-0123456789abcdef0"},
        first_seen=observed,
        last_observed=observed,
    )
    run = SyncRun(trigger="manual")
    user = User(username="test-user", password_hash="placeholder-not-a-real-password-hash")
    db_session.add_all([vm, run, user])
    db_session.flush()
    result = SyncResult(
        run_id=run.id,
        provider="aws",
        account_id="111111111111",
        region="eu-central-1",
        status="success",
        instances_seen=1,
        duration_ms=5,
    )
    login = UserSession(
        id_hash="0" * 64,
        user_id=user.id,
        expires_at=observed + timedelta(hours=12),
        ip="10.0.0.1",
        user_agent="test-client",
    )
    db_session.add_all([result, login])
    db_session.flush()
    db_session.expire_all()

    account = db_session.scalars(select(Account)).one()
    assert account.name == "test-account"
    assert account.enabled is True
    assert account.last_success_at is None
    stored_vm = db_session.scalars(select(Instance)).one()
    assert stored_vm.private_ips == ["10.0.0.1", "10.0.0.2"]
    assert stored_vm.public_ips == ["192.0.2.1"]
    assert stored_vm.tags == {"Environment": "Testing"}
    assert stored_vm.details["security_groups"] == [{"id": "sg-test", "inbound": []}]
    assert stored_vm.raw["InstanceId"] == "i-0123456789abcdef0"
    assert stored_vm.present is True
    assert stored_vm.first_seen == observed
    assert stored_vm.last_observed.utcoffset() == timedelta(0)
    stored_run = db_session.scalars(select(SyncRun)).one()
    assert stored_run.status == "running"
    assert stored_run.finished_at is None
    assert stored_run.instances_seen == 0
    assert stored_run.started_at.utcoffset() == timedelta(0)
    assert db_session.scalars(select(SyncResult)).one().duration_ms == 5
    stored_user = db_session.scalars(select(User)).one()
    assert stored_user.is_active is True
    assert stored_user.is_admin is False
    assert stored_user.mfa_enabled is False
    assert stored_user.failed_logins == 0
    assert stored_user.last_login_at is None
    assert stored_user.totp_secret_enc is None
    stored_session = db_session.scalars(select(UserSession)).one()
    assert stored_session.user_id == stored_user.id
    assert stored_session.mfa_passed is False
    assert stored_session.ip == "10.0.0.1"
    assert stored_session.created_at.utcoffset() == timedelta(0)
    assert db_session.scalar(text("SHOW timezone")) == "UTC"


def test_generated_search_tracks_inserts_and_updates(db_session: Session) -> None:
    add_account(db_session)
    vm = instance(
        name="WEB-Test",
        private_ips=["10.0.0.1"],
        public_ips=["192.0.2.1"],
        tags={"Owner": "Platform Team", "Note": "Line\nTwo"},
    )
    db_session.add(vm)
    db_session.flush()
    for term in [
        "web-test",
        "i-0123456789abcdef0",
        "10.0.0.1",
        "192.0.2.1",
        "owner",
        "platform team",
        "line\ntwo",
    ]:
        assert (
            db_session.scalar(select(Instance.id).where(Instance.search_text.contains(term)))
            == vm.id
        )
    assert vm.search_text == vm.search_text.lower()
    db_session.execute(
        text(
            "UPDATE instances SET name = NULL, private_ips = '{}', public_ips = '{}', "
            'tags = \'{"Service": "NEW"}\' WHERE id = :id'
        ),
        {"id": vm.id},
    )
    db_session.refresh(vm)
    assert "service new" in vm.search_text
    assert "web-test" not in vm.search_text
    assert "10.0.0.1" not in vm.search_text
    assert "platform team" not in vm.search_text


def test_defaults_for_unnamed_instance(db_session: Session) -> None:
    add_account(db_session)
    vm = instance()
    db_session.add(vm)
    db_session.flush()
    assert vm.name is None
    assert vm.private_ips == []
    assert vm.public_ips == []
    assert vm.tags == {}
    assert vm.details == {}
    assert vm.raw == {}
    assert vm.instance_id in vm.search_text


def test_duplicate_instance_identity_is_rejected(db_session: Session) -> None:
    add_account(db_session)
    db_session.add(instance())
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(instance())
        db_session.flush()
    db_session.add(instance(region="us-east-1"))
    db_session.flush()
    assert len(db_session.scalars(select(Instance)).all()) == 2


def test_instance_requires_matching_provider_and_account(db_session: Session) -> None:
    add_account(db_session)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(instance(provider="alibaba"))
        db_session.flush()


def test_duplicate_username_is_rejected(db_session: Session) -> None:
    db_session.add(User(username="test-user", password_hash="placeholder-hash"))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(User(username="test-user", password_hash="another-placeholder-hash"))
        db_session.flush()


def test_session_requires_a_user(db_session: Session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            UserSession(
                id_hash="1" * 64,
                user_id=999,
                expires_at=datetime(2026, 1, 2, tzinfo=UTC),
                ip="10.0.0.1",
                user_agent="test",
            )
        )
        db_session.flush()


@pytest.mark.parametrize("state", ["invalid", "Running"])
def test_state_is_normalized(db_session: Session, state: str) -> None:
    add_account(db_session)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(instance(state=state))
        db_session.flush()


def test_deleting_user_cascades_to_sessions(db_session: Session) -> None:
    user = User(username="cascade-test", password_hash="placeholder-hash")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserSession(
            id_hash="2" * 64,
            user_id=user.id,
            expires_at=datetime(2026, 1, 2, tzinfo=UTC),
            ip="10.0.0.1",
            user_agent="test",
        )
    )
    db_session.flush()
    db_session.delete(user)
    db_session.flush()
    assert (
        db_session.scalar(select(UserSession.id_hash).where(UserSession.user_id == user.id)) is None
    )
