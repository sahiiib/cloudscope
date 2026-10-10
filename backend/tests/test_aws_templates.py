"""Deployment policy regressions must not widen collector permissions."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class TemplateLoader(yaml.SafeLoader):
    pass


TemplateLoader.add_multi_constructor(
    "!", lambda loader, tag, node: {tag: loader.construct_scalar(node)}
)


def template(name: str) -> dict:
    return yaml.load((ROOT / "deploy/aws" / name).read_text(), Loader=TemplateLoader)


def test_readonly_permissions_match_spec_and_trust_requires_external_id() -> None:
    doc = template("readonly-role.yaml")
    properties = doc["Resources"]["ReadOnlyRole"]["Properties"]
    spec = (ROOT / "docs/specs/cloud-access.md").read_text()
    policies = [json.loads(block) for block in re.findall(r"```json\s*(.*?)\s*```", spec, re.S)]
    assert properties["Policies"][0]["PolicyDocument"]["Statement"] == [policies[1]]
    assert len(properties["Policies"]) == 1 and "ManagedPolicyArns" not in properties
    assert properties["RoleName"] == "cloudscope-readonly"
    trust = properties["AssumeRolePolicyDocument"]["Statement"]
    assert len(trust) == 1
    assert trust[0]["Principal"] == {"AWS": {"Ref": "HubRoleArn"}}
    assert trust[0]["Condition"] == {"StringEquals": {"sts:ExternalId": {"Ref": "ExternalId"}}}
    assert set(trust[0]["Action"]) == {"sts:AssumeRole", "sts:TagSession"}


def test_hub_only_assumes_inventory_roles_and_trusts_selected_pods() -> None:
    properties = template("hub-role.yaml")["Resources"]["HubRole"]["Properties"]
    assert len(properties["Policies"]) == 1 and "ManagedPolicyArns" not in properties
    assert properties["Policies"][0]["PolicyDocument"]["Statement"] == [
        {
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Resource": {"Sub": "arn:${AWS::Partition}:iam::*:role/cloudscope-readonly"},
        }
    ]
    trust = properties["AssumeRolePolicyDocument"]["Statement"]
    assert len(trust) == 1 and trust[0]["Principal"] == {"Service": "pods.eks.amazonaws.com"}
    assert set(trust[0]["Action"]) == {"sts:AssumeRole", "sts:TagSession"}
    assert trust[0]["Condition"]["StringEquals"] == {
        "aws:RequestTag/eks-cluster-arn": {"Ref": "ClusterArn"},
        "aws:RequestTag/kubernetes-namespace": {"Ref": "Namespace"},
        "aws:RequestTag/kubernetes-service-account": "cloudscope",
    }
