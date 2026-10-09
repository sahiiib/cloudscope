# Collector

Entry point: `cloudscope collect [--account ID] [--region R] [--trigger schedule|manual]`.

## Flow

1. Load `accounts.yaml`, upsert `accounts` (mark removed ones `enabled = false`).
2. Insert a `sync_runs` row with `status = running`.
3. For each enabled account, resolve credentials (see below) and the region list.
4. Scan each (account, region) in a thread pool (`CLOUDSCOPE_COLLECT_CONCURRENCY`).
5. For each scan:
   - Fetch instances and the extra objects needed for `details`.
   - Normalize into `NormalizedInstance` (see `collector/base.py`).
   - Upsert into `instances` (update all columns, set `last_observed = now()`,
     `present = true`; keep `first_seen`).
   - Mark instances of that (account, region) not seen in this scan as
     `present = false`, `state = terminated`. **Only if the scan succeeded.**
   - Write a `sync_results` row.
6. Finish the run: `success` if all scans succeeded, `partial` if some failed,
   `failed` if all failed. Update `accounts.last_success_at`.

A failure in one scan (throttling, access denied, region disabled) is caught,
logged and recorded; it never aborts the run. Retries use the SDKs' built-in
retry with adaptive mode for AWS.

## Provider interface

```python
class Provider(Protocol):
    name: Literal["aws", "alibaba"]
    def list_regions(self, account: AccountConfig) -> list[str]: ...
    def scan(self, account: AccountConfig, region: str) -> list[NormalizedInstance]: ...
```

`NormalizedInstance` carries exactly the `instances` columns from
[data-model.md](data-model.md) except `id`, `first_seen`, `last_observed`,
`present` and `search_text`.

## AWS

Credentials:
- Base session: default boto3 chain (env keys or `AWS_PROFILE` locally; Pod
  Identity / IRSA on EKS).
- If the account has `role_arn`: `sts:AssumeRole` with session name
  `cloudscope-collector` and optional `external_id`. Cache credentials per
  account and refresh before expiry.
- Without `role_arn`: use the base session directly (test-key mode).

Regions (`regions: all`): `ec2.describe_regions(AllRegions=False)` (only enabled
regions).

Per region:
- `describe_instances` (paginator), all states.
- `describe_security_groups` for the referenced group IDs (batched).
- `describe_vpcs` and `describe_subnets` for referenced IDs (for name + CIDR).
- Name = value of the `Name` tag.
- `public_ips`: `PublicIpAddress` plus `Association.PublicIp` on every ENI.
- `cpu`: `CpuOptions.CoreCount * ThreadsPerCore`. `memory_mib` is left `null`
  for now (needs `describe_instance_types`; later task).

`AWSProvider` takes an optional `(account, region) -> EC2Reader` factory.
The default `AWSClientFactory` uses the boto3 credential chain and adaptive
retries. Assumed sessions are cached by account/role/external ID and refreshed
five minutes before expiry; session/client construction is serialized for
threaded collection. Region discovery defaults to `us-east-1` and can be
configured for other AWS partitions. Explicit configured regions need no API call.

Describe pagination follows every NextToken, with repeated tokens treated as
errors. Enrichment uses batched ID filters (100 IDs) and per-scan maps; images
are described for their names. Missing lookup results are null, while API errors
propagate so a failed scan cannot be mistaken for an empty inventory.
Normalized records preserve the original instance payload in `raw`, with SDK
datetimes represented as UTC ISO strings for JSONB. Collection does not write to
the database until the runner is added in T-012.

Required permissions: see [cloud-access.md](cloud-access.md).

## Alibaba Cloud

Credentials:
- Base: `ALIBABA_CLOUD_ACCESS_KEY_ID` / `_SECRET`.
- If the account has `role_arn`: STS `AssumeRole` (session name
  `cloudscope-collector`, duration 3600s), cached per account.
- Without `role_arn`: use the base key directly (test-key mode).

Endpoints: `ecs.<region>.aliyuncs.com`, `vpc.<region>.aliyuncs.com`; STS
`sts.aliyuncs.com`.

Regions (`regions: all`): ECS `DescribeRegions`.

Per region:
- ECS `DescribeInstances` with `MaxResults=100` and `NextToken` pagination.
- ECS `DescribeSecurityGroupAttribute` per referenced group (inbound and
  outbound, `Direction=all`), cached within the scan.
- VPC `DescribeVpcs` and `DescribeVSwitches` for name + CIDR.
- Network interfaces: `NetworkInterfaces.NetworkInterface` in the instance
  payload; call ECS `DescribeNetworkInterfaces` only if secondary IPs are missing.
- Name = `InstanceName`. Tags from `Tags.Tag[]`.
- `public_ips`: `PublicIpAddress.IpAddress[]` plus `EipAddress.IpAddress`.
- `cpu` = `Cpu`, `memory_mib` = `Memory`.
- `launch_time` = `CreationTime` (note: Alibaba has no separate launch time).

## Testing

- AWS: `moto` (`mock_aws`) with instances, SGs, VPCs in two regions and an
  assumed-role account.
- Alibaba: inject a fake client via the provider constructor; fixture JSON in
  `backend/tests/fixtures/alibaba/` copied from real response shapes with
  placeholder IDs.
- Runner: test that a failing region gives `partial`, that missing instances are
  marked `present = false` only after a successful scan, and that re-runs are
  idempotent.
