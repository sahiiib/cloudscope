"""NAT inventory, atomicity and association tests; never use real cloud APIs."""

from dataclasses import asdict, replace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import event, select
from test_auth import client as client
from test_auth import login
from test_auth import user as user
from test_load_balancers import ACCOUNT, NOW, Reader
from test_network import Provider as EIPProvider
from test_network import factory, seed
from test_network import normalized as eip_normalized

from cloudscope.collector.alibaba import AlibabaProvider, SDKReader
from cloudscope.collector.aws import AWSProvider, BotoReader
from cloudscope.collector.nat_gateways import nat_gateways, normalize_nat
from cloudscope.collector.network import NetworkCollector
from cloudscope.db.models import Account, ElasticIP, NatGateway, NetworkScan


def payload(**changes):
    return {
        "NatGatewayId": "nat-demo",
        "State": "available",
        "ConnectivityType": "public",
        "VpcId": "vpc-demo",
        "SubnetId": "subnet-demo",
        "Tags": [{"Key": "Name", "Value": "Web_100%"}],
        "NatGatewayAddresses": [
            {
                "AllocationId": "eipalloc-demo",
                "PublicIp": "192.0.2.1",
                "PrivateIp": "10.0.0.1",
                "NetworkInterfaceId": "eni-demo",
            }
        ],
        **changes,
    }


def normalized(**changes):
    return replace(normalize_nat(payload(), ACCOUNT, "us-east-1"), **changes)


class Provider(EIPProvider):
    nats = None

    def scan_nat_gateways(self, account, region):
        if isinstance(self.nats, Exception):
            raise self.nats
        return self.nats if self.nats is not None else [normalized()]


def test_aws_tokens_and_normalization():
    reader = Reader(
        [
            {"NatGateways": [payload()], "NextToken": "next"},
            {
                "NatGateways": [
                    payload(
                        NatGatewayId="nat-private",
                        ConnectivityType="private",
                        State="deleted",
                        NatGatewayAddresses=[{"PrivateIp": "10.0.0.2"}],
                    )
                ]
            },
        ]
    )
    rows = nat_gateways(reader, ACCOUNT, "us-east-1")
    assert len(rows) == 2 and rows[0].name == "Web_100%"
    assert rows[0].addresses == [
        {
            "allocation_id": "eipalloc-demo",
            "public_ip": "192.0.2.1",
            "private_ip": "10.0.0.1",
            "network_interface_id": "eni-demo",
        }
    ]
    assert rows[1].state == "deleted" and rows[1].connectivity_type == "private"
    assert rows[1].addresses[0]["allocation_id"] is None
    assert reader.calls == [
        ("describe_nat_gateways", {}),
        ("describe_nat_gateways", {"NextToken": "next"}),
    ]


def ali_payload(**changes):
    return {
        "NatGatewayId": "ngw-demo",
        "Name": "Alibaba demo",
        "Status": "Available",
        "NatType": "Enhanced",
        "NetworkType": "internet",
        "Spec": "Small",
        "VpcId": "vpc-demo",
        "NatGatewayPrivateInfo": {"VswitchId": "vsw-demo", "PrivateIpAddress": "10.0.0.2"},
        "IpLists": {"IpList": [{"AllocationId": "eip-demo", "IpAddress": "192.0.2.2"}]},
        "Tags": {"Tag": [{"TagKey": "env", "TagValue": "test"}]},
        **changes,
    }


def test_alibaba_pages_and_normalization():
    account = ACCOUNT.model_copy(update={"provider": "alibaba"})
    reader = Reader(
        [
            {"NatGateways": {"NatGateway": [ali_payload()]}, "TotalCount": 2},
            {"NatGateways": {"NatGateway": [ali_payload(NatGatewayId="ngw-2")]}, "TotalCount": 2},
        ]
    )
    rows = nat_gateways(reader, account, "us-east-1")
    assert rows[0].nat_type == "Enhanced" and rows[0].network_type == "internet"
    assert rows[0].private_ip == "10.0.0.2" and rows[0].subnet_id == "vsw-demo"
    assert rows[0].spec == "Small" and rows[0].tags == {"env": "test"}
    assert rows[0].addresses[0]["allocation_id"] == "eip-demo"
    assert reader.calls[1] == (
        "describe_nat_gateways",
        {"region_id": "us-east-1", "page_number": 2, "page_size": 50},
    )


@pytest.mark.parametrize(
    "cloud,pages",
    [
        ("aws", [{}]),
        ("aws", [{"NatGateways": [payload(), payload()]}]),
        ("aws", [{"NatGateways": [], "NextToken": "same"}] * 2),
        ("aws", [{"NatGateways": [], "NextToken": 4}]),
        ("aws", [{"NatGateways": [payload(NatGatewayAddresses={})]}]),
        ("aws", [{"NatGateways": [payload(State=None)]}]),
        ("aws", [{"NatGateways": [payload(RegionId="other")]}]),
        ("alibaba", [{"NatGateways": {"NatGateway": []}, "TotalCount": 1}]),
        ("alibaba", [{"NatGateways": {"NatGateway": []}}]),
        ("alibaba", [{"NatGateways": {"NatGateway": []}, "TotalCount": 0, "PageNumber": 2}]),
        (
            "alibaba",
            [
                {"NatGateways": {"NatGateway": [ali_payload()]}, "TotalCount": 2},
                {"NatGateways": {"NatGateway": []}, "TotalCount": 0},
            ],
        ),
        ("alibaba", [{"NatGateways": {"NatGateway": [ali_payload()]}, "TotalCount": 2}] * 2),
    ],
)
def test_bad_pages_fail(cloud, pages):
    with pytest.raises((ValueError, KeyError, TypeError)):
        nat_gateways(Reader(pages), ACCOUNT.model_copy(update={"provider": cloud}), "us-east-1")


def test_sdk_adapters_with_moto_and_injected_alibaba():
    import boto3
    from moto import mock_aws

    with mock_aws():
        ec2 = boto3.client("ec2", region_name="us-east-1")
        # Fixture creation is confined to moto.
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
        allocation = ec2.allocate_address(Domain="vpc")["AllocationId"]
        nat = ec2.create_nat_gateway(SubnetId=subnet, AllocationId=allocation)["NatGateway"]
        rows = AWSProvider(
            client_factory=lambda account, region: BotoReader(ec2)
        ).scan_nat_gateways(ACCOUNT, "us-east-1")
        assert rows[0].nat_gateway_id == nat["NatGatewayId"]
    vpc = Mock()
    vpc.describe_nat_gateways_with_options.return_value.body.to_map.return_value = {
        "NatGateways": {"NatGateway": [ali_payload()]},
        "TotalCount": 1,
    }
    ali = AlibabaProvider(client_factory=lambda account, region: SDKReader(Mock(), vpc))
    assert (
        ali.scan_nat_gateways(ACCOUNT.model_copy(update={"provider": "alibaba"}), "us-east-1")[
            0
        ].nat_gateway_id
        == "ngw-demo"
    )
    request = vpc.describe_nat_gateways_with_options.call_args.args[0]
    assert (request.page_size, request.page_number, request.region_id) == (50, 1, "us-east-1")


def test_atomic_failure_missing_reappearance_and_resource_isolation(db_session):
    seed(db_session)
    provider = Provider()
    collector = NetworkCollector(factory(db_session), {"aws": provider}, clock=lambda: NOW)
    collector.scan(ACCOUNT, "us-east-1")
    nat = db_session.scalar(select(NatGateway))
    identity = nat.id
    collector.clock = lambda: NOW + timedelta(hours=1)
    for bad in (
        PermissionError("secret payload"),
        [normalized(), normalized()],
        [normalized(account_id="222222222222")],
    ):
        provider.nats = bad
        collector.scan(ACCOUNT, "us-east-1")
        db_session.expire_all()
        row = db_session.get_one(NatGateway, identity)
        assert row.present and row.last_observed == NOW
        status = db_session.get_one(
            NetworkScan, ("aws", ACCOUNT.account_id, "us-east-1", "nat_gateway")
        )
        assert status.status == "error" and status.last_success == NOW
        assert status.last_attempt == NOW + timedelta(hours=1)
        assert (
            db_session.get_one(
                NetworkScan, ("aws", ACCOUNT.account_id, "us-east-1", "elastic_ip")
            ).status
            == "success"
        )
    provider.rows = RuntimeError("EIP error")
    provider.nats = []
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert not db_session.get_one(NatGateway, identity).present
    assert db_session.scalar(select(ElasticIP)).present
    provider.nats = [normalized()]
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert db_session.get_one(NatGateway, identity).present
    assert db_session.get_one(NatGateway, identity).first_seen == NOW


def test_inventory_auth_search_filters_deleted_and_details(client, db_session):
    assert client.get("/api/nat-gateways").status_code == 401
    seed(db_session)
    for name, state, present in [
        ("nat-demo", "available", True),
        ("nat-deleted", "deleted", True),
        ("nat-missing", "available", False),
    ]:
        db_session.add(
            NatGateway(
                **asdict(normalized(nat_gateway_id=name, state=state)),
                first_seen=NOW,
                last_observed=NOW,
                present=present,
            )
        )
    db_session.commit()
    login(client)
    for query in ("web_100%", "nat-demo", "192.0.2.1", "10.0.0.1", "vpc-demo", "alias"):
        body = client.get("/api/nat-gateways", params={"q": query}).json()
        assert body["total"] == 1 and "raw" not in body["items"][0]
    assert client.get("/api/nat-gateways", params={"q": "web_100%X"}).json()["total"] == 0
    assert (
        client.get(
            "/api/nat-gateways", params={"include_missing": True, "page_size": 1, "page": 2}
        ).json()["items"][0]["nat_gateway_id"]
        == "nat-deleted"
    )
    for field, value in [
        ("provider", "alibaba"),
        ("account_id", "other"),
        ("region", "other"),
        ("state", "deleted"),
    ]:
        assert client.get("/api/nat-gateways", params={field: value}).json()["total"] == 0
    assert client.get("/api/nat-gateways?page_size=501").status_code == 422
    prefix = f"/api/nat-gateways/aws/{ACCOUNT.account_id}/us-east-1/"
    assert client.get(prefix + "nat-missing").json()["present"] is False
    assert client.get(prefix + "nat-demo").json()["raw"]["NatGatewayId"] == "nat-demo"
    assert client.get(prefix + "absent").status_code == 404


@pytest.mark.parametrize("cloud", ["aws", "alibaba"])
def test_eip_nat_association_scope_presence_and_deleted(client, db_session, cloud):
    seed(db_session)
    if cloud == "alibaba":
        db_session.add(Account(provider=cloud, account_id=ACCOUNT.account_id, name="Alibaba"))
        db_session.flush()
    eip = ElasticIP(
        **asdict(
            eip_normalized(
                provider=cloud,
                allocation_id="attached",
                status="associated",
                associated_type="network_interface" if cloud == "aws" else "nat_gateway",
                associated_id="eni-demo" if cloud == "aws" else "nat-demo",
            )
        ),
        first_seen=NOW,
        last_observed=NOW,
    )
    nat = NatGateway(
        **asdict(
            normalized(
                provider=cloud, addresses=[{"allocation_id": "attached", "public_ip": "192.0.2.1"}]
            )
        ),
        first_seen=NOW,
        last_observed=NOW,
    )
    db_session.add_all([eip, nat])
    db_session.commit()
    login(client)
    path = f"/api/elastic-ips/{cloud}/{ACCOUNT.account_id}/us-east-1/attached"
    expected = f"/nat-gateways/{cloud}/{ACCOUNT.account_id}/us-east-1/nat-demo"
    assert client.get(path).json()["association"] == {
        "type": "nat_gateway",
        "id": "nat-demo",
        "link": expected,
    }
    for attr, value in [
        ("present", False),
        ("region", "other"),
        ("account_id", "222222222222"),
        ("state", "deleted"),
    ]:
        if attr == "account_id":
            db_session.add(Account(provider=cloud, account_id=value, name="other"))
            db_session.flush()
        old = getattr(nat, attr)
        setattr(nat, attr, value)
        db_session.commit()
        assert client.get(path).json()["association"]["link"] is None
        setattr(nat, attr, old)
        db_session.commit()
    eip.status = "available"
    db_session.commit()
    assert client.get(path).json()["association"] is None


def test_association_queries_batched_per_page(client, db_session):
    seed(db_session)
    for index in range(20):
        db_session.add(
            ElasticIP(
                **asdict(
                    eip_normalized(
                        allocation_id=f"eip-{index}",
                        status="associated",
                        associated_type="network_interface",
                        associated_id="eni-demo",
                    )
                ),
                first_seen=NOW,
                last_observed=NOW,
            )
        )
    db_session.add(NatGateway(**asdict(normalized()), first_seen=NOW, last_observed=NOW))
    db_session.commit()
    login(client)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("SELECT") and any(
            f"FROM {name}" in statement for name in ("instances", "load_balancers", "nat_gateways")
        ):
            statements.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        assert client.get("/api/elastic-ips").status_code == 200
        assert len(statements) == 3
    finally:
        event.remove(connection, "before_cursor_execute", capture)


def test_excluded_regions_skip_nat_and_retire_only_after_success(migrated_engine):
    from sqlalchemy import delete
    from sqlalchemy.orm import sessionmaker
    from test_runner import FakeProvider, instance

    from cloudscope.collector.runner import SyncRunner
    from cloudscope.db.models import Instance, SyncResult, SyncRun

    sessions = sessionmaker(migrated_engine, expire_on_commit=False)
    calls = []

    class RegionalProvider(Provider):
        def scan_nat_gateways(self, account, region):
            calls.append(region)
            return [normalized(region=region)]

        def scan_elastic_ips(self, account, region):
            return []

    account = ACCOUNT.model_copy(update={"regions": ["us-east-1", "us-west-2"]})
    instances = FakeProvider()
    collector = NetworkCollector(sessions, {"aws": RegionalProvider()})
    runner = SyncRunner(sessions, {"aws": instances}, network=collector)
    try:
        assert runner.run([account]).status == "success"
        calls.clear()
        excluded = account.model_copy(update={"excluded_regions": ["us-west-2"]})
        instances.results["us-east-1"] = RuntimeError("failed")
        assert runner.run([excluded]).status == "failed"
        assert calls == ["us-east-1"]
        with sessions() as session:
            assert session.scalar(
                select(NatGateway.present).where(NatGateway.region == "us-west-2")
            )
        instances.results["us-east-1"] = [instance()]
        assert runner.run([excluded]).status == "success"
        with sessions() as session:
            assert not session.scalar(
                select(NatGateway.present).where(NatGateway.region == "us-west-2")
            )
            assert (
                session.scalar(select(NetworkScan).where(NetworkScan.region == "us-west-2")) is None
            )
    finally:
        with sessions.begin() as session:
            for model in (
                NetworkScan,
                NatGateway,
                ElasticIP,
                SyncResult,
                Instance,
                SyncRun,
                Account,
            ):
                session.execute(delete(model))
