"""Network inventory tests use injected clients and an isolated database."""

from dataclasses import asdict, replace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_auth import client as client
from test_auth import login
from test_auth import user as user
from test_load_balancers import ACCOUNT, NOW, Reader
from test_load_balancers import normalized as lb_normalized

from cloudscope.collector.alibaba import AlibabaProvider, SDKReader
from cloudscope.collector.aws import AWSProvider, BotoReader
from cloudscope.collector.network import (
    NetworkCollector,
    build_network_collector,
    elastic_ips,
    normalize,
)
from cloudscope.config import Settings
from cloudscope.db.models import (
    Account,
    ElasticIP,
    Instance,
    LoadBalancer,
    NetworkScan,
    SyncResult,
    SyncRun,
)


def normalized(**changes):
    return replace(
        normalize(
            {
                "AllocationId": "eipalloc-demo",
                "PublicIp": "192.0.2.1",
                "Tags": [{"Key": "Name", "Value": "Web_100%"}],
            },
            ACCOUNT,
            "us-east-1",
        ),
        **changes,
    )


class Provider:
    rows = None

    def scan_elastic_ips(self, account, region):
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows if self.rows is not None else [normalized()]


def factory(db_session):
    return sessionmaker(
        bind=db_session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


def seed(db_session, **changes):
    db_session.add(
        Account(provider="aws", account_id=ACCOUNT.account_id, name="Demo", cloud_alias="alias")
    )
    db_session.flush()
    row = ElasticIP(**asdict(normalized(**changes)), first_seen=NOW, last_observed=NOW)
    db_session.add(row)
    db_session.commit()
    return row


def test_aws_single_call_and_normalization():
    reader = Reader(
        [
            {
                "Addresses": [
                    {
                        "AllocationId": "eipalloc-demo",
                        "PublicIp": "192.0.2.1",
                        "AssociationId": "eipassoc-demo",
                        "InstanceId": "i-demo",
                        "NetworkInterfaceId": "eni-demo",
                        "PrivateIpAddress": "10.0.0.1",
                        "Tags": [{"Key": "Name", "Value": "Demo"}],
                    }
                ]
            }
        ]
    )
    row = elastic_ips(reader, ACCOUNT, "us-east-1")[0]
    assert (row.status, row.associated_type, row.associated_id, row.name) == (
        "associated",
        "instance",
        "i-demo",
        "Demo",
    )
    assert row.private_ip == "10.0.0.1" and row.network_interface_id == "eni-demo"
    assert reader.calls == [("describe_addresses", {})]
    assert row.raw["AssociationId"] == "eipassoc-demo"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("EcsInstance", "instance"),
        ("SlbInstance", "load_balancer"),
        ("Nat", "nat_gateway"),
        ("NetworkInterface", "network_interface"),
        ("Other", "Other"),
    ],
)
def test_alibaba_normalization_and_pages(kind, expected):
    account = ACCOUNT.model_copy(update={"provider": "alibaba"})
    payload = {
        "AllocationId": "eip-1",
        "IpAddress": "192.0.2.1",
        "Status": "InUse",
        "InstanceType": kind,
        "InstanceId": "resource-demo",
        "Name": "Demo",
        "Bandwidth": "100",
        "InternetChargeType": "PayByTraffic",
        "Tags": {"Tag": [{"Key": "env", "Value": "test"}]},
    }
    reader = Reader(
        [
            {"EipAddresses": {"EipAddress": [payload]}, "TotalCount": 2},
            {
                "EipAddresses": {
                    "EipAddress": [{**payload, "AllocationId": "eip-2", "Status": "Available"}]
                },
                "TotalCount": 2,
            },
        ]
    )
    rows = elastic_ips(reader, account, "us-east-1")
    assert len(rows) == 2 and rows[1].status == "available"
    assert rows[0].associated_type == expected and rows[0].bandwidth == "100"
    assert rows[0].tags == {"env": "test"}
    assert reader.calls[1] == (
        "describe_eip_addresses",
        {"region_id": "us-east-1", "page_number": 2, "page_size": 100},
    )


@pytest.mark.parametrize(
    "pages",
    [
        [{}],
        [{"EipAddresses": {"EipAddress": []}}],
        [{"EipAddresses": {"EipAddress": []}, "TotalCount": 1}],
        [{"EipAddresses": {"EipAddress": [{"AllocationId": "x"}]}, "TotalCount": 1}],
        [
            {
                "EipAddresses": {"EipAddress": [{"AllocationId": "x", "IpAddress": "192.0.2.1"}]},
                "TotalCount": 2,
            }
        ]
        * 2,
        [
            {
                "EipAddresses": {"EipAddress": [{"AllocationId": "x", "IpAddress": "192.0.2.1"}]},
                "TotalCount": 2,
            },
            {"EipAddresses": {"EipAddress": []}, "TotalCount": 0},
        ],
    ],
)
def test_malformed_or_incomplete_pages_fail(pages):
    with pytest.raises((ValueError, KeyError)):
        elastic_ips(Reader(pages), ACCOUNT.model_copy(update={"provider": "alibaba"}), "us-east-1")


def test_sdk_wiring_and_flag(monkeypatch):
    ec2 = Mock()
    ec2.describe_addresses.return_value = {"Addresses": []}
    aws = BotoReader(ec2)
    assert (
        AWSProvider(client_factory=lambda account, region: aws).scan_elastic_ips(
            ACCOUNT, "us-east-1"
        )
        == []
    )
    ec2.describe_addresses.assert_called_once_with()
    vpc = Mock()
    vpc.describe_eip_addresses_with_options.return_value.body.to_map.return_value = {
        "EipAddresses": {"EipAddress": []},
        "TotalCount": 0,
    }
    ali = SDKReader(Mock(), vpc)
    assert (
        AlibabaProvider(client_factory=lambda account, region: ali).scan_elastic_ips(
            ACCOUNT.model_copy(update={"provider": "alibaba"}), "us-east-1"
        )
        == []
    )
    request = vpc.describe_eip_addresses_with_options.call_args.args[0]
    assert request.page_size == 100 and request.region_id == "us-east-1"
    assert build_network_collector(Mock(), False) is None
    monkeypatch.delenv("CLOUDSCOPE_NETWORK_ENABLED", raising=False)
    assert not Settings(
        database_url="postgresql+psycopg://localhost/test",
        secret_key=Fernet.generate_key().decode(),
        _env_file=None,
    ).network_enabled
    monkeypatch.setenv("CLOUDSCOPE_NETWORK_ENABLED", "true")
    assert Settings(
        database_url="postgresql+psycopg://localhost/test",
        secret_key=Fernet.generate_key().decode(),
        _env_file=None,
    ).network_enabled


def test_atomic_failure_missing_reappearance(db_session, caplog):
    row = seed(db_session)
    original_id = row.id
    provider = Provider()
    collector = NetworkCollector(
        factory(db_session), {"aws": provider}, clock=lambda: NOW + timedelta(hours=1)
    )
    collector.scan(ACCOUNT, "us-east-1")
    for bad in (
        RuntimeError("sensitive payload"),
        [normalized(), normalized()],
        [normalized(account_id="222222222222")],
    ):
        provider.rows = bad
        collector.clock = lambda: NOW + timedelta(hours=2)
        collector.scan(ACCOUNT, "us-east-1")
        db_session.expire_all()
        current = db_session.get_one(ElasticIP, original_id)
        assert current.present and current.last_observed == NOW + timedelta(hours=1)
        status = db_session.get_one(
            NetworkScan, ("aws", ACCOUNT.account_id, "us-east-1", "elastic_ip")
        )
        assert status.status == "error" and status.last_success == NOW + timedelta(hours=1)
        assert status.last_attempt == NOW + timedelta(hours=2)
    assert "sensitive payload" not in caplog.text
    provider.rows = []
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert not db_session.get_one(ElasticIP, original_id).present
    provider.rows = [normalized()]
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert db_session.get_one(ElasticIP, original_id).present
    assert db_session.get_one(ElasticIP, original_id).first_seen == NOW


@pytest.mark.parametrize("step_failure", [False, True])
def test_network_failure_preserves_instance_and_lb_collection(db_session, caplog, step_failure):
    from test_load_balancers import Provider as LBProvider
    from test_runner import FakeProvider

    from cloudscope.collector.load_balancers import LoadBalancerCollector
    from cloudscope.collector.runner import SyncRunner

    seed(db_session)
    run = SyncRun(trigger="manual")
    db_session.add(run)
    db_session.commit()
    provider = Provider()
    provider.rows = PermissionError("secret")
    sessions = factory(db_session)
    network = NetworkCollector(sessions, {"aws": provider})
    if step_failure:
        network.scan = Mock(side_effect=RuntimeError("sensitive step payload"))
    runner = SyncRunner(
        sessions,
        {"aws": FakeProvider()},
        network=network,
        load_balancers=LoadBalancerCollector(sessions, {"aws": LBProvider()}),
    )
    runner._scan(run.id, ACCOUNT, "us-east-1")
    assert db_session.scalar(select(Instance)) is not None
    assert db_session.scalar(select(LoadBalancer)) is not None
    assert db_session.scalar(select(SyncResult)).status == "success"
    event = "network_step_failed" if step_failure else "network_scan_failed"
    message = next(
        record.getMessage() for record in caplog.records if f"event={event}" in record.getMessage()
    )
    assert f"account_id={ACCOUNT.account_id}" in message
    assert "region=us-east-1" in message
    assert "error=RuntimeError" in message if step_failure else "error=PermissionError" in message
    assert "sensitive step payload" not in caplog.text and "secret" not in caplog.text
    if not step_failure:
        assert db_session.scalar(select(NetworkScan)).status == "error"


def test_inventory_auth_filters_missing_details(client, db_session):
    for path in ("/api/elastic-ips", "/api/network/scans", "/api/elastic-ips/aws/a/r/id"):
        assert client.get(path).status_code == 401
    row = seed(db_session)
    db_session.add(
        ElasticIP(
            **asdict(normalized(allocation_id="gone", public_ip="192.0.2.2")),
            first_seen=NOW,
            last_observed=NOW,
            present=False,
        )
    )
    db_session.commit()
    login(client)
    for q in ("web_100%", "192.0.2.1", "alias", ACCOUNT.account_id):
        result = client.get("/api/elastic-ips", params={"q": q}).json()
        assert result["total"] == 1 and "raw" not in result["items"][0]
    assert client.get("/api/elastic-ips", params={"q": "web_100%z"}).json()["total"] == 0
    assert (
        client.get(
            "/api/elastic-ips", params={"include_missing": True, "page_size": 1, "page": 2}
        ).json()["items"][0]["allocation_id"]
        == "gone"
    )
    for key, value in [
        ("provider", "alibaba"),
        ("account_id", "other"),
        ("region", "other"),
        ("status", "associated"),
        ("associated_type", "instance"),
    ]:
        assert client.get("/api/elastic-ips", params={key: value}).json()["total"] == 0
    assert client.get("/api/elastic-ips?page_size=501").status_code == 422
    path = f"/api/elastic-ips/aws/{ACCOUNT.account_id}/us-east-1/"
    assert client.get(path + "gone").json()["present"] is False
    assert client.get(path + row.allocation_id).json()["raw"] == row.raw
    assert client.get(path + "absent").status_code == 404
    assert client.get("/api/network/scans").json() == {"enabled": False, "items": []}


def test_associations_present_and_same_identity_only(client, db_session):
    from dataclasses import asdict

    from test_runner import instance

    row = seed(db_session, status="associated", associated_type="instance", associated_id="i-1")
    instance_row = Instance(
        **asdict(replace(instance(), instance_id="i-1")), first_seen=NOW, last_observed=NOW
    )
    db_session.add(instance_row)
    db_session.commit()
    login(client)
    path = f"/api/elastic-ips/aws/{ACCOUNT.account_id}/us-east-1/{row.allocation_id}"
    target = f"/instances/aws/{ACCOUNT.account_id}/us-east-1/i-1"
    assert client.get(path).json()["association"]["link"] == target
    assert client.get("/api" + target).json()["elastic_ips"] == [
        {"public_ip": row.public_ip, "allocation_id": row.allocation_id}
    ]
    instance_row.present = False
    db_session.commit()
    assert client.get(path).json()["association"]["link"] is None
    instance_row.present = True
    instance_row.region = "other"
    db_session.commit()
    assert client.get(path).json()["association"]["link"] is None
    row.status = "available"
    db_session.commit()
    assert client.get(path).json()["association"] is None


def test_aws_nlb_allocation_resolution(client, db_session):
    row = seed(
        db_session,
        status="associated",
        associated_type="network_interface",
        associated_id="eni-demo",
    )
    lb = LoadBalancer(
        **asdict(
            replace(
                lb_normalized(),
                kind="network",
                raw={
                    "AvailabilityZones": [
                        {"LoadBalancerAddresses": [{"AllocationId": row.allocation_id}]}
                    ]
                },
            )
        ),
        first_seen=NOW,
        last_observed=NOW,
    )
    db_session.add(lb)
    db_session.commit()
    login(client)
    path = f"/api/elastic-ips/aws/{ACCOUNT.account_id}/us-east-1/{row.allocation_id}"
    result = client.get(path).json()["association"]
    assert result["type"] == "load_balancer" and result["link"].endswith("/elbv2/lb-demo")
    lb.present = False
    db_session.commit()
    assert client.get(path).json()["association"] == {
        "type": "network_interface",
        "id": "eni-demo",
        "link": None,
    }


def test_excluded_region_never_reaches_network_collector(migrated_engine):
    from sqlalchemy import delete
    from test_runner import FakeProvider

    from cloudscope.collector.runner import SyncRunner

    sessions = sessionmaker(migrated_engine, expire_on_commit=False)
    calls = []

    class Recorder:
        def scan(self, account, region):
            calls.append(region)

    account = ACCOUNT.model_copy(
        update={"regions": ["us-east-1", "us-west-2"], "excluded_regions": ["us-west-2"]}
    )
    try:
        SyncRunner(sessions, {"aws": FakeProvider()}, network=Recorder()).run([account])
        assert calls == ["us-east-1"]
    finally:
        with sessions.begin() as session:
            session.execute(delete(SyncResult))
            session.execute(delete(SyncRun))
            session.execute(delete(Instance))
            session.execute(delete(Account))


def test_aws_describe_addresses_with_moto():
    import boto3
    from moto import mock_aws

    with mock_aws():
        ec2 = boto3.client("ec2", region_name="us-east-1")
        # Only the fake service is mutated to set up an inventory fixture.
        allocation = ec2.allocate_address(Domain="vpc")
        rows = elastic_ips(BotoReader(ec2), ACCOUNT, "us-east-1")
        assert rows[0].allocation_id == allocation["AllocationId"]
        assert rows[0].status == "available"


def test_alibaba_clb_links_require_present_matching_resource(client, db_session):
    account = ACCOUNT.model_copy(update={"provider": "alibaba"})
    db_session.add(Account(provider="alibaba", account_id=account.account_id, name="Demo"))
    db_session.flush()
    eip = normalize(
        {
            "AllocationId": "eip-demo",
            "IpAddress": "192.0.2.1",
            "Status": "InUse",
            "InstanceType": "SlbInstance",
            "InstanceId": "lb-demo",
        },
        account,
        "us-east-1",
    )
    db_session.add(ElasticIP(**asdict(eip), first_seen=NOW, last_observed=NOW))
    lb = LoadBalancer(
        **asdict(replace(lb_normalized(), provider="alibaba", family="clb")),
        first_seen=NOW,
        last_observed=NOW,
    )
    db_session.add(lb)
    db_session.commit()
    login(client)
    path = f"/api/elastic-ips/alibaba/{account.account_id}/us-east-1/eip-demo"
    assert (
        client.get(path).json()["association"]["link"]
        == f"/load-balancers/alibaba/{account.account_id}/us-east-1/clb/lb-demo"
    )
    lb.present = False
    db_session.commit()
    assert client.get(path).json()["association"]["link"] is None


def test_failed_provider_pages_preserve_previous_snapshot(db_session):
    seed(db_session)
    broken = Reader([{"Addresses": [{"AllocationId": "new", "PublicIp": "192.0.2.2"}, {}]}])
    provider = AWSProvider(client_factory=lambda account, region: broken)
    NetworkCollector(factory(db_session), {"aws": provider}).scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    rows = list(db_session.scalars(select(ElasticIP)))
    assert len(rows) == 1 and rows[0].allocation_id == "eipalloc-demo"
    assert rows[0].present and rows[0].last_observed == NOW
    assert db_session.scalar(select(NetworkScan)).status == "error"


def test_payload_region_must_match_scan_scope():
    with pytest.raises(ValueError, match="Mismatched"):
        normalize(
            {"AllocationId": "eip-demo", "IpAddress": "192.0.2.1", "RegionId": "other"},
            ACCOUNT.model_copy(update={"provider": "alibaba"}),
            "us-east-1",
        )
