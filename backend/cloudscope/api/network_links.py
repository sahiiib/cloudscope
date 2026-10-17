"""Resolve one EIP page with at most three inventory queries, never cloud calls."""

from collections.abc import Sequence
from urllib.parse import quote

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from cloudscope.db.models import ElasticIP, Instance, LoadBalancer, NatGateway


def resource_link(prefix: str, *identity: str) -> str:
    return "/" + prefix + "/" + "/".join(quote(part, safe="") for part in identity)


def associations(
    session: Session, eips: Sequence[ElasticIP]
) -> dict[int, dict[str, object] | None]:
    active = [eip for eip in eips if eip.status != "available"]
    result: dict[int, dict[str, object] | None] = {eip.id: None for eip in eips}
    if not active:
        return result
    scopes = {(eip.provider, eip.account_id, eip.region) for eip in active}
    instances = session.scalars(
        select(Instance).where(
            tuple_(Instance.provider, Instance.account_id, Instance.region).in_(scopes),
            Instance.present.is_(True),
            Instance.instance_id.in_(
                [eip.associated_id for eip in active if eip.associated_type == "instance"]
            ),
        )
    ).all()
    lbs = session.scalars(
        select(LoadBalancer)
        .where(
            tuple_(LoadBalancer.provider, LoadBalancer.account_id, LoadBalancer.region).in_(scopes),
            LoadBalancer.present.is_(True),
        )
        .order_by(LoadBalancer.id)
    ).all()
    nats = session.scalars(
        select(NatGateway)
        .where(
            tuple_(NatGateway.provider, NatGateway.account_id, NatGateway.region).in_(scopes),
            NatGateway.present.is_(True),
            func.lower(NatGateway.state) != "deleted",
        )
        .order_by(NatGateway.id)
    ).all()
    links: dict[tuple[str, str, str, str, str], str] = {}
    allocations: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for instance in instances:
        scope = (instance.provider, instance.account_id, instance.region)
        links[(*scope, "instance", instance.instance_id)] = resource_link(
            "instances", *scope, instance.instance_id
        )
    for lb in lbs:
        scope = (lb.provider, lb.account_id, lb.region)
        link = resource_link("load-balancers", *scope, lb.family, lb.load_balancer_id)
        if lb.provider == "alibaba" and lb.family == "clb":
            links[(*scope, "load_balancer", lb.load_balancer_id)] = link
        if lb.provider == "aws" and lb.family == "elbv2" and lb.kind == "network":
            zones = lb.raw.get("AvailabilityZones", [])
            if isinstance(zones, list):
                for zone in zones:
                    if not isinstance(zone, dict):
                        continue
                    for address in zone.get("LoadBalancerAddresses", []):
                        if isinstance(address, dict) and address.get("AllocationId"):
                            allocations.setdefault(
                                (*scope, address["AllocationId"]),
                                {"type": "load_balancer", "id": lb.load_balancer_id, "link": link},
                            )
    for nat in nats:
        scope = (nat.provider, nat.account_id, nat.region)
        link = resource_link("nat-gateways", *scope, nat.nat_gateway_id)
        links[(*scope, "nat_gateway", nat.nat_gateway_id)] = link
        if nat.provider == "aws":
            for address in nat.addresses:
                allocation = address.get("allocation_id")
                if allocation:
                    allocations[(*scope, allocation)] = {
                        "type": "nat_gateway",
                        "id": nat.nat_gateway_id,
                        "link": link,
                    }
    for eip in active:
        scope = (eip.provider, eip.account_id, eip.region)
        kind, resource_id = eip.associated_type, eip.associated_id
        allocation_target = allocations.get((*scope, eip.allocation_id))
        if eip.provider == "aws" and kind in (None, "network_interface") and allocation_target:
            result[eip.id] = allocation_target
        else:
            result[eip.id] = {
                "type": kind,
                "id": resource_id,
                "link": links.get((*scope, kind or "", resource_id or "")),
            }
    return result
