# Cloud access setup

All access is read-only. Nothing here allows changing cloud resources.

## Phase 1–3: test keys (local)

For local development and the local cluster we use existing test access keys.

- Keys live only in `.env` (local) or a Kubernetes Secret. Never in git, never
  in chat, never in `accounts.yaml`.
- Accounts in `accounts.yaml` have no `role_arn`, so the key is used directly.
  With one key only one account per provider can be scanned; to scan more,
  add `role_arn` entries the test key can assume.
- Policies attached to the test identities should be limited to:
  - AWS: `AmazonEC2ReadOnlyAccess` plus `iam:ListAccountAliases` (or the custom policy below)
  - Alibaba: `AliyunECSReadOnlyAccess` + `AliyunVPCReadOnlyAccess` plus `ram:GetAccountAlias`

## Phase 4: AWS (12 accounts)

```
 EKS pod ──Pod Identity──▶ cloudscope-hub (hub account)
                               │ sts:AssumeRole
                               ▼
              cloudscope-readonly (in each of the 12 accounts)
```

1. **Hub role** `cloudscope-hub` in the account that runs EKS. Trusted by EKS
   Pod Identity (`pods.eks.amazonaws.com`) for the `cloudscope` service account.
   The trust allows `sts:AssumeRole` and `sts:TagSession`, because Pod Identity
   attaches session tags. Permission: only
   ```json
   {"Effect": "Allow", "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::*:role/cloudscope-readonly"}
   ```
2. **Read-only role** `cloudscope-readonly` in every account, deployed with a
   CloudFormation StackSet from the management account
   (`deploy/aws/readonly-role.yaml`). Trust: the hub role ARN, condition
   `sts:ExternalId = cloudscope`. The trust allows `sts:AssumeRole` and
   `sts:TagSession`, because Pod Identity session tags are transitive in the
   role chain. Permissions:
   ```json
   {"Effect": "Allow", "Resource": "*", "Action": [
     "ec2:DescribeAddresses", "ec2:DescribeInstances", "ec2:DescribeRegions",
     "ec2:DescribeSecurityGroups", "ec2:DescribeSecurityGroupRules",
     "ec2:DescribeVpcs", "ec2:DescribeSubnets",
     "ec2:DescribeNetworkInterfaces", "ec2:DescribeInstanceTypes",
     "ec2:DescribeImages", "ec2:DescribeKeyPairs",
     "iam:ListAccountAliases",
     "elasticloadbalancing:DescribeLoadBalancers"
   ]}
   ```
   Keep this block and `deploy/aws/readonly-role.yaml` together, because
   `backend/tests/test_aws_templates.py` checks that they match.
3. Add each account to `accounts.yaml` with its `role_arn` and `external_id`.

For local testing before EKS: an IAM user in the hub account whose only
permission is `sts:AssumeRole` on `cloudscope-readonly` roles. Its key goes in
the Kubernetes Secret and is deleted once EKS is live.

## Phase 4: Alibaba Cloud (8 accounts)

```
 collector ──AccessKey──▶ RAM user cloudscope-collector (central account)
                               │ sts:AssumeRole
                               ▼
              RAM role cloudscope-readonly (in each of the 8 accounts)
```

1. **Central RAM user** `cloudscope-collector`, API access only (no console),
   policy allowing only `sts:AssumeRole` on
   `acs:ram::*:role/cloudscope-readonly`.
2. **RAM role** `cloudscope-readonly` in each account, trusted by the central
   account (`"RAM": ["acs:ram::<central-account-id>:root"]`), with
   `AliyunECSReadOnlyAccess` and `AliyunVPCReadOnlyAccess`, plus a custom
   policy allowing only `ram:GetAccountAlias` (shows the account alias).
   Template: `deploy/alibaba/readonly-role.tf` (Terraform) or created by hand.
3. Add each account to `accounts.yaml` with its `role_arn`.
4. Rotate the RAM user key every 90 days.

## Load balancer permissions (T-069)

See [load-balancers.md](load-balancers.md) for the additive schema, read-only
operations, per-family failure behavior, API and opt-in rollout.

## Elastic IP and NAT gateway permissions (T-081, T-082)

See [network.md](network.md#permissions-and-rollout): AWS
`ec2:DescribeAddresses` and `ec2:DescribeNatGateways`; Alibaba reads are already
in `AliyunVPCReadOnlyAccess`.

## Dedicated connection identity (T-071)

Dedicated connections add read-only AWS STS GetCallerIdentity and Alibaba STS
GetCallerIdentity checks before region discovery or inventory. Their Account /
AccountId must match the configured account. These checks use the supplied key
pair; collector EC2/ECS/LB and alias calls then use that same validated connection.
Cloud write operations are never requested. See the official
[AWS identity API](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)
and [Alibaba identity API](https://www.alibabacloud.com/help/en/ram/developer-reference/api-sts-2015-04-01-getcalleridentity).
AWS documents that GetCallerIdentity does not require permissions; keep the
existing inventory/alias/LB permissions on each Dedicated account's user. Operators
must validate Alibaba STS/region permissions for their RAM users as well. No live
IAM/RAM grants are applied by this change. Kubernetes Secret RBAC is separate and
is documented in [account-credentials.md](account-credentials.md).
