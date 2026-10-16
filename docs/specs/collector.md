# Collector

Entry point: `cloudscope collect [--account ID] [--region R] [--trigger schedule|manual]`.

`collect` uses exported `Settings` (database URL, Fernet key, accounts path and
concurrency); it never implicitly loads `.env`. It prints a tab-separated summary
and exits 0 for success/partial, 1 for failed/configuration/database errors.
Invalid command-line options return 2. Setup failures print only safe categories:
configuration field locations (without inputs/messages), database exception class, the fixed unknown-account
message, or an unexpected exception class. Invalid YAML reports the `accounts`
location. Exception payloads are never printed; control characters in field
locations and file paths are escaped.

`--account` selects an account ID (across providers if shared); an unknown ID is
an error that rolls back reconciliation. `--region` intersects configured/discovered
regions, without forcing scans outside that list. No matching region yields a
failed run and exit 1. The runner always reconciles the complete account file,
so filtered-out accounts remain enabled. Unscanned inventory is untouched and
`last_success_at` advances only if every resolved region of that account ran
successfully. A filtered subset does not imply a fully successful account sync.

The CLI holds PostgreSQL advisory lock `1129530192` throughout collection and
releases it on exit. A concurrent CLI run fails immediately; future manual API
callers must use the same database-scoped lock. SDK retries remain provider-owned.

## Flow

1. Load `accounts.yaml`, upsert `accounts` rows with `source = file` (mark
   removed ones `enabled = false`), then read every enabled row, from either
   source, as the account list. See [accounts.md](accounts.md).
2. Mark any `sync_runs` row still `running` as `cancelled` if cancellation was
   requested, otherwise `failed` (the caller holds the
   collection lock, so such a row was left by a killed process, e.g. OOMKilled),
   then insert a `sync_runs` row with `status = running`. Any unexpected error
   after this point marks the run `failed` before it propagates.
3. For each selected enabled account, resolve credentials (see below), read the
   account alias once, and resolve the region list. Alias failures preserve the
   previous alias/check timestamp and do not fail scans. An empty alias clears
   the stored value. File configuration updates change `updated_at` only when
   values change; alias checks and scan success have their own timestamps.
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
   `failed` if all failed, or `cancelled` when Stop was requested. Update `accounts.last_success_at`.

A failure in one scan (throttling, access denied, region disabled) is caught,
logged and recorded; it never aborts the run. Retries use the SDKs' built-in
retry with adaptive mode for AWS.

`SyncRunner(session_factory, providers, concurrency=8)` accepts injected provider
instances and a SQLAlchemy session factory. `run(accounts, trigger="manual")`
accepts the complete validated file configuration; `run_file(path, ...)` loads
it from YAML. Each worker owns its database session. Inventory changes and its
successful result commit together; failed writes roll back the entire region.
Existing row IDs and `first_seen` are preserved, and reappearing instances become
present again. Missing rows retain their last actual observation timestamp.

Removed file accounts are disabled and skipped; restoring them to configuration
re-enables them. An account's `last_success_at` advances only when all its regions
succeed. Region discovery errors (including an empty region list) produce an
error result with region `*`. An empty file configuration disables previously configured file accounts and
scans enabled UI accounts. If neither source has enabled accounts, the run is
a successful no-op.
A missing file behaves like an empty file account list; invalid YAML still fails. Error records and logs
include only the SDK error code (AWS/Alibaba) or exception class name, never
exception messages, arguments or tracebacks. Stored errors include the phase
prefix and are capped at 200 characters. Logs identify the run, phase, provider,
account and region; account IDs are unquoted with unsafe characters escaped,
and regions are quoted to prevent log injection.
Callers must serialize runs; overlapping collection runs are not supported.

## Provider interface

```python
class Provider(Protocol):
    name: Literal["aws", "alibaba"]
    def get_account_alias(self, account: AccountConfig) -> str | None: ...
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
configured for other AWS partitions. AssumeRole always uses this fixed discovery
region for STS, independent of which target region is scanned first.
Explicit configured regions need no API call.

Describe pagination follows every NextToken, with repeated tokens treated as
errors. Enrichment uses batched ID filters (100 IDs) and per-scan maps; images
are described for their names. Missing lookup results are null, while API errors
propagate so a failed scan cannot be mistaken for an empty inventory.
Normalized records preserve the original instance payload in `raw`, with SDK
datetimes represented as UTC ISO strings for JSONB. Database writes are handled by `SyncRunner`, independently of the SDK adapters.

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

`AlibabaProvider` accepts an injected `(account, region) -> AlibabaReader`
factory. The default adapter uses the official ECS, VPC and STS request models,
SDK retries, regional ECS/VPC endpoints and the global STS endpoint. Base keys
come from the documented environment variables; assumed credentials are cached
per account/role/external ID and refreshed five minutes before expiration.

Instance, ENI and security-rule reads exhaust NextToken pagination (100 results
per request). Missing secondary-IP lists trigger ENI enrichment; embedded payloads
are preserved in `raw`. Security groups and VPC/vSwitch rows are cached only
within a scan. An empty network lookup yields null, but API errors propagate.
Alibaba rules additionally retain `policy`, `priority` and `source_port_range`
so allow/deny semantics are not lost. Image name, monitoring and IAM role are
null when absent from the instance payload; CPU and memory come from Cpu/Memory.

## Testing

- AWS: `moto` (`mock_aws`) with instances, SGs, VPCs in two regions and an
  assumed-role account.
- Alibaba: inject a fake client via the provider constructor; fixture JSON in
  `backend/tests/fixtures/alibaba/` copied from real response shapes with
  placeholder IDs.
- Runner: test that a failing region gives `partial`, that missing instances are
  marked `present = false` only after a successful scan, and that re-runs are
  idempotent.

## Load balancer collection (T-069)

See [load-balancers.md](load-balancers.md) for the additive schema, read-only
operations, per-family failure behavior, API and opt-in rollout.

## Cooperative cancellation and API scope (T-076)

A scoped API run filters by both provider and account ID under the same advisory
lock. Run scope is stored in `sync_runs`. The runner reads `cancel_requested_at`
from a fresh database session before account discovery and before each worker
starts a region scan. This works across API and CronJob processes. Already active
scans finish atomically; queued scans are skipped. Finalization locks the run row
against concurrent cancellation and records `cancelled` when requested. Only
accounts with successful results for every discovered region advance last success.

## Excluded regions (T-077)

After region discovery, the runner removes each account's `excluded_regions`,
including explicit region lists. The access check uses the same selection. If the
selection is empty it fails with `no regions left after exclusions`. Only after
all included regions of a selected account have successful results are instances
and load balancers in excluded regions marked `present=false`. Failed, partial,
region-filtered or incompletely cancelled accounts retain excluded inventory.
Retirement also removes that account’s excluded-region LB scan status rows in
the same transaction, so stale access errors disappear. Re-enabling a region
allows its next successful scan to restore presence.

An empty discovery or unmatched explicit selection reports `no valid regions`;
`no regions left after exclusions` is reserved for exclusions removing candidates.
