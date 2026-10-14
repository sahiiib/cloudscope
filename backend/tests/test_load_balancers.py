"""Read-only adapters, pagination and snapshots; no live cloud calls."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_auth import client as client
from test_auth import login
from test_auth import user as user

from cloudscope.collector.alibaba import SDKReader
from cloudscope.collector.aws import BotoReader
from cloudscope.collector.base import Payload
from cloudscope.collector.load_balancers import (
    LoadBalancerCollector,
    NormalizedLoadBalancer,
    alibaba_load_balancers,
    aws_load_balancers,
)
from cloudscope.config import AccountConfig
from cloudscope.db.models import Account, LoadBalancer, LoadBalancerScan

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ACCOUNT = AccountConfig(
    provider="aws", account_id="111111111111", name="Demo", regions=["us-east-1"]
)


class Reader:
    def __init__(self, pages: list[Payload]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call(self, operation: str, **params: object) -> Payload:
        self.calls.append((operation, params))
        return self.pages.pop(0)


@pytest.mark.parametrize("kind", ["application", "network", "gateway"])
def test_aws_v2_pages_and_normalization(kind: str) -> None:
    lb = {
        "LoadBalancerArn": (
            "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/app/demo/1"
        ),
        "LoadBalancerName": "demo",
        "Type": kind,
        "DNSName": "demo.example.com",
        "State": {"Code": "active"},
        "Scheme": "internet-facing",
        "VpcId": "vpc-test",
        "AvailabilityZones": [{"ZoneName": "us-east-1a"}],
    }
    reader = Reader([{"LoadBalancers": [lb], "NextMarker": "next"}, {"LoadBalancers": []}])
    rows = aws_load_balancers(reader, ACCOUNT, "us-east-1", "elbv2")
    assert rows[0].kind == kind and rows[0].addresses == ["demo.example.com"]
    assert rows[0].zones == ["us-east-1a"] and rows[0].raw == lb
    assert reader.calls[1] == ("elbv2_describe_load_balancers", {"Marker": "next"})


def test_classic_never_invents_health_status() -> None:
    reader = Reader(
        [
            {
                "LoadBalancerDescriptions": [
                    {
                        "LoadBalancerName": "demo",
                        "DNSName": "demo.example.com",
                        "AvailabilityZones": ["us-east-1a"],
                    }
                ]
            }
        ]
    )
    row = aws_load_balancers(reader, ACCOUNT, "us-east-1", "classic")[0]
    assert row.load_balancer_id == "demo" and row.state == "unknown"


@pytest.mark.parametrize("family", ["alb", "nlb"])
def test_alibaba_token_pages_and_request_parameters(family: str) -> None:
    account = ACCOUNT.model_copy(update={"provider": "alibaba"})
    reader = Reader(
        [
            {
                "LoadBalancers": [
                    {
                        "LoadBalancerId": "lb-demo",
                        "LoadBalancerStatus": "Active",
                        "DNSName": "demo.example.com",
                        "AddressType": "Intranet",
                    }
                ],
                "NextToken": "next",
            },
            {"LoadBalancers": []},
        ]
    )
    row = alibaba_load_balancers(reader, account, "cn-hangzhou", family)[0]
    assert row.scheme == "internal" and row.kind == family
    assert reader.calls[1][1]["next_token"] == "next"
    assert ("region_id" in reader.calls[0][1]) == (family == "nlb")


def test_clb_page_numbers() -> None:
    account = ACCOUNT.model_copy(update={"provider": "alibaba"})
    reader = Reader(
        [
            {
                "LoadBalancers": {
                    "LoadBalancer": [{"LoadBalancerId": "lb-1", "Address": "10.0.0.1"}]
                },
                "TotalCount": 2,
            },
            {"LoadBalancers": {"LoadBalancer": [{"LoadBalancerId": "lb-2"}]}, "TotalCount": 2},
        ]
    )
    rows = alibaba_load_balancers(reader, account, "cn-hangzhou", "clb")
    assert len(rows) == 2 and rows[0].addresses == ["10.0.0.1"]
    assert reader.calls[1][1]["page_number"] == 2


@pytest.mark.parametrize("cloud,family", [("aws", "elbv2"), ("alibaba", "alb")])
def test_repeated_tokens_and_malformed_pages_fail(cloud: str, family: str) -> None:
    account = ACCOUNT.model_copy(update={"provider": cloud})
    normalize = aws_load_balancers if cloud == "aws" else alibaba_load_balancers
    token = "NextMarker" if cloud == "aws" else "NextToken"
    with pytest.raises(RuntimeError):
        normalize(Reader([{"LoadBalancers": [], token: "same"}] * 2), account, "test", family)
    with pytest.raises(ValueError):
        normalize(Reader([{}]), account, "test", family)


def test_sdk_adapters_allow_only_read_operations() -> None:
    class SDK:
        def describe_load_balancers(self, **params: object) -> Payload:
            return {"LoadBalancers": []}

    aws = BotoReader(object(), lb=lambda service: SDK())
    assert aws.call("elbv2_describe_load_balancers") == {"LoadBalancers": []}
    with pytest.raises(ValueError):
        aws.call("delete_load_balancer")

    class Body:
        def to_map(self) -> Payload:
            return {"LoadBalancers": []}

    class Response:
        body = Body()

    class Alibaba:
        def list_load_balancers_with_options(self, request: Any, options: Any) -> Response:
            assert request.max_results == 100 and request.next_token == "next"
            return Response()

    ali = SDKReader(object(), object(), lb=lambda service: Alibaba())
    assert ali.call("alb_load_balancers", max_results=100, next_token="next") == {
        "LoadBalancers": []
    }
    with pytest.raises(ValueError):
        ali.call("delete_load_balancer")


def normalized(family: str = "elbv2") -> NormalizedLoadBalancer:
    return NormalizedLoadBalancer(
        provider="aws",
        account_id=ACCOUNT.account_id,
        region="us-east-1",
        family=family,
        load_balancer_id="lb-demo",
        name="Web_100%",
        kind="application",
        state="active",
        scheme="internal",
        addresses=["demo.example.com"],
        vpc_id="vpc-test",
        zones=[],
        tags={},
        raw={},
    )


class Provider:
    def __init__(self) -> None:
        self.rows: dict[str, list[NormalizedLoadBalancer] | Exception] = {
            "elbv2": [normalized()],
            "classic": [],
        }

    def scan_load_balancers(
        self, account: AccountConfig, region: str, family: str
    ) -> list[NormalizedLoadBalancer]:
        rows = self.rows[family]
        if isinstance(rows, Exception):
            raise rows
        return rows


def test_success_missing_failure_reappearance_and_invalid_identity(db_session: Session) -> None:
    db_session.add(Account(provider="aws", account_id=ACCOUNT.account_id, name="Demo"))
    db_session.commit()
    sessions = sessionmaker(
        bind=db_session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    provider = Provider()
    collector = LoadBalancerCollector(sessions, {"aws": provider}, clock=lambda: NOW)
    collector.scan(ACCOUNT, "us-east-1")
    first = db_session.scalar(select(LoadBalancer))
    assert first is not None and first.present
    original_id = first.id
    provider.rows["elbv2"] = RuntimeError("sensitive provider payload")
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert db_session.get_one(LoadBalancer, original_id).present
    status = db_session.get_one(LoadBalancerScan, ("aws", ACCOUNT.account_id, "us-east-1", "elbv2"))
    assert (
        status.status == "error" and status.error == "RuntimeError" and status.last_success == NOW
    )
    provider.rows["elbv2"] = [normalized(), normalized()]
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert db_session.get_one(LoadBalancer, original_id).present
    provider.rows["elbv2"] = [replace(normalized(), account_id="222222222222")]
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert db_session.get_one(LoadBalancer, original_id).present
    provider.rows["elbv2"] = []
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert not db_session.get_one(LoadBalancer, original_id).present
    provider.rows["elbv2"] = [normalized()]
    collector.scan(ACCOUNT, "us-east-1")
    db_session.expire_all()
    assert db_session.get_one(LoadBalancer, original_id).present
    assert db_session.get_one(LoadBalancer, original_id).first_seen == NOW


def test_inventory_auth_search_pagination_missing_and_details(
    client: TestClient, db_session: Session
) -> None:
    assert client.get("/api/load-balancers").status_code == 401
    db_session.add(
        Account(provider="aws", account_id=ACCOUNT.account_id, name="Demo", cloud_alias="alias")
    )
    db_session.flush()
    from dataclasses import asdict

    db_session.add_all(
        [
            LoadBalancer(**asdict(normalized()), first_seen=NOW, last_observed=NOW),
            LoadBalancer(
                **asdict(replace(normalized(), load_balancer_id="gone")),
                first_seen=NOW,
                last_observed=NOW,
                present=False,
            ),
        ]
    )
    db_session.commit()
    login(client)
    for q in ("web_100%", "demo.example.com", "alias", "vpc-test"):
        body = client.get("/api/load-balancers", params={"q": q}).json()
        assert body["total"] == 1 and "raw" not in body["items"][0]
    assert (
        client.get(
            "/api/load-balancers", params={"include_missing": "true", "page_size": 1}
        ).json()["total"]
        == 2
    )
    assert client.get("/api/load-balancers", params={"provider": "alibaba"}).json()["total"] == 0
    assert client.get("/api/load-balancers", params={"page_size": 501}).status_code == 422
    path = f"/api/load-balancers/aws/{ACCOUNT.account_id}/us-east-1/elbv2/lb-demo"
    assert client.get(path).json()["raw"] == {}
    assert client.get(path + "-absent").status_code == 404
    assert client.get("/api/load-balancers/scans").json() == {"enabled": False, "items": []}


def test_aws_arn_details_are_routed_without_losing_slashes(
    client: TestClient, db_session: Session
) -> None:
    from dataclasses import asdict
    from urllib.parse import quote

    arn = "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/app/demo/1"
    db_session.add(Account(provider="aws", account_id=ACCOUNT.account_id, name="Demo"))
    db_session.flush()
    db_session.add(
        LoadBalancer(
            **asdict(replace(normalized(), load_balancer_id=arn)), first_seen=NOW, last_observed=NOW
        )
    )
    db_session.commit()
    login(client)
    path = f"/api/load-balancers/aws/{ACCOUNT.account_id}/us-east-1/elbv2/{quote(arn, safe='')}"
    result = client.get(path)
    assert result.status_code == 200 and result.json()["load_balancer_id"] == arn


def test_lb_access_failure_does_not_stop_instance_collection(db_session: Session) -> None:
    from test_runner import FakeProvider

    from cloudscope.collector.runner import SyncRunner
    from cloudscope.db.models import Instance, SyncResult, SyncRun

    db_session.add(Account(provider="aws", account_id=ACCOUNT.account_id, name="Demo"))
    run = SyncRun(trigger="manual")
    db_session.add(run)
    db_session.commit()
    sessions = sessionmaker(
        bind=db_session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    lbs = Provider()
    lbs.rows["elbv2"] = PermissionError("sensitive SDK response")
    collector = LoadBalancerCollector(sessions, {"aws": lbs}, clock=lambda: NOW)
    runner = SyncRunner(
        sessions, {"aws": FakeProvider()}, clock=lambda: NOW, load_balancers=collector
    )
    runner._scan(run.id, ACCOUNT, "us-east-1")
    assert db_session.scalar(select(Instance)) is not None
    assert db_session.scalar(select(SyncResult)).status == "success"
    assert (
        db_session.get_one(
            LoadBalancerScan, ("aws", ACCOUNT.account_id, "us-east-1", "elbv2")
        ).status
        == "error"
    )
    assert (
        db_session.get_one(
            LoadBalancerScan, ("aws", ACCOUNT.account_id, "us-east-1", "classic")
        ).status
        == "success"
    )


def test_clb_tags_from_official_sdk_model() -> None:
    from alibabacloud_slb20140515.models import DescribeLoadBalancersResponseBody

    body = DescribeLoadBalancersResponseBody().from_map(
        {
            "LoadBalancers": {
                "LoadBalancer": [
                    {
                        "LoadBalancerId": "lb-demo",
                        "AddressType": "internet",
                        "Tags": {"Tag": [{"TagKey": "env", "TagValue": "test"}]},
                    }
                ]
            },
            "TotalCount": 1,
        }
    )
    row = alibaba_load_balancers(
        Reader([body.to_map()]),
        ACCOUNT.model_copy(update={"provider": "alibaba"}),
        "cn-hangzhou",
        "clb",
    )[0]
    assert row.tags == {"env": "test"} and row.scheme == "internet-facing"


@pytest.mark.parametrize("family", ["alb", "nlb"])
def test_alibaba_public_exposure_and_nlb_addresses(family: str) -> None:
    from alibabacloud_alb20200616.models import ListLoadBalancersResponseBody as ALBBody
    from alibabacloud_nlb20220430.models import ListLoadBalancersResponseBody as NLBBody

    model = ALBBody if family == "alb" else NLBBody
    body = model().from_map(
        {
            "LoadBalancers": [
                {
                    "LoadBalancerId": "lb-demo",
                    "AddressType": "Internet",
                    "DNSName": "demo.example.com",
                    "ZoneMappings": [
                        {
                            "ZoneId": "cn-hangzhou-a",
                            "LoadBalancerAddresses": [
                                {
                                    "PublicIPv4Address": "192.0.2.1",
                                    "PrivateIPv4Address": "10.0.0.1",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    row = alibaba_load_balancers(
        Reader([body.to_map()]),
        ACCOUNT.model_copy(update={"provider": "alibaba"}),
        "cn-hangzhou",
        family,
    )[0]
    assert row.scheme == "internet-facing"
    if family == "nlb":
        assert row.addresses == ["demo.example.com", "192.0.2.1", "10.0.0.1"]
    else:
        assert row.addresses == ["demo.example.com"]


def test_real_aws_factory_reader_with_moto() -> None:
    import boto3
    from moto import mock_aws

    from cloudscope.collector.aws import AWSClientFactory

    with mock_aws():
        session = boto3.Session(region_name="us-east-1")
        ec2 = session.client("ec2")
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.0.0/24")["Subnet"]["SubnetId"]
        session.client("elbv2").create_load_balancer(
            Name="demo",
            Subnets=[subnet],
            Type="network",
            Scheme="internal",
        )
        session.client("elb").create_load_balancer(
            LoadBalancerName="classic-demo",
            AvailabilityZones=["us-east-1a"],
            Listeners=[{"Protocol": "HTTP", "LoadBalancerPort": 80, "InstancePort": 80}],
        )
        reader = AWSClientFactory(base_session=session)(ACCOUNT, "us-east-1")
        assert aws_load_balancers(reader, ACCOUNT, "us-east-1", "elbv2")[0].kind == "network"
        assert aws_load_balancers(reader, ACCOUNT, "us-east-1", "classic")[0].name == "classic-demo"


@pytest.mark.parametrize("family", ["alb", "nlb"])
def test_alibaba_tags_and_addresses_in_same_public_snapshot(family: str) -> None:
    row = alibaba_load_balancers(
        Reader(
            [
                {
                    "LoadBalancers": [
                        {
                            "LoadBalancerId": "lb-demo",
                            "AddressType": "Internet",
                            "Tags": [{"Key": "env", "Value": "dev"}],
                            "ZoneMappings": [
                                {
                                    "LoadBalancerAddresses": [
                                        {
                                            "PublicIPv4Address": "192.0.2.2",
                                            "PrivateIPv4Address": "10.0.0.3",
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                }
            ]
        ),
        ACCOUNT.model_copy(update={"provider": "alibaba"}),
        "cn-hangzhou",
        family,
    )[0]
    assert row.tags == {"env": "dev"} and row.scheme == "internet-facing"
    assert row.addresses == ["192.0.2.2", "10.0.0.3"]


def test_lb_status_write_failure_cannot_fail_instance_result(db_session: Session) -> None:
    from test_runner import FakeProvider

    from cloudscope.collector.runner import SyncRunner
    from cloudscope.db.models import Instance, SyncResult, SyncRun

    class BrokenCollector(LoadBalancerCollector):
        def scan(self, account: AccountConfig, region: str) -> None:
            raise RuntimeError("status store unavailable")

    db_session.add(Account(provider="aws", account_id=ACCOUNT.account_id, name="Demo"))
    run = SyncRun(trigger="manual")
    db_session.add(run)
    db_session.commit()
    sessions = sessionmaker(
        bind=db_session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    runner = SyncRunner(
        sessions,
        {"aws": FakeProvider()},
        clock=lambda: NOW,
        load_balancers=BrokenCollector(sessions, {}),
    )
    runner._scan(run.id, ACCOUNT, "us-east-1")
    assert db_session.scalar(select(Instance)) is not None
    assert db_session.scalar(select(SyncResult)).status == "success"
