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
  - AWS: `AmazonEC2ReadOnlyAccess` (or the custom policy below)
  - Alibaba: `AliyunECSReadOnlyAccess` + `AliyunVPCReadOnlyAccess`

## Phase 4: AWS (12 accounts)

```
 EKS pod ──Pod Identity──▶ cloudscope-hub (hub account)
                               │ sts:AssumeRole
                               ▼
              cloudscope-readonly (in each of the 12 accounts)
```

1. **Hub role** `cloudscope-hub` in the account that runs EKS. Trusted by EKS
   Pod Identity (`pods.eks.amazonaws.com`) for the `cloudscope` service account.
   Permission: only
   ```json
   {"Effect": "Allow", "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::*:role/cloudscope-readonly"}
   ```
2. **Read-only role** `cloudscope-readonly` in every account, deployed with a
   CloudFormation StackSet from the management account
   (`deploy/aws/readonly-role.yaml`). Trust: the hub role ARN, condition
   `sts:ExternalId = cloudscope`. Permissions:
   ```json
   {"Effect": "Allow", "Resource": "*", "Action": [
     "ec2:DescribeInstances", "ec2:DescribeRegions",
     "ec2:DescribeSecurityGroups", "ec2:DescribeSecurityGroupRules",
     "ec2:DescribeVpcs", "ec2:DescribeSubnets",
     "ec2:DescribeNetworkInterfaces", "ec2:DescribeInstanceTypes",
     "ec2:DescribeImages", "ec2:DescribeKeyPairs"
   ]}
   ```
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
   `AliyunECSReadOnlyAccess` and `AliyunVPCReadOnlyAccess`.
   Template: `deploy/alibaba/readonly-role.tf` (Terraform) or created by hand.
3. Add each account to `accounts.yaml` with its `role_arn`.
4. Rotate the RAM user key every 90 days.
