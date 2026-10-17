# Elastic IPs and NAT gateways (T-081, T-082)

Saheb, 2026-10-17. Two new read-only inventory pages, built the same way as
[load balancers](load-balancers.md): **Elastic IPs** (T-081) and **NAT gateways**
(T-082). Other public addresses (auto-assigned public IPs, ENIs) get their own
"Network addresses" page in a later phase and are out of scope here.

## Collection and persistence

- Reuse the account/base-credential/AssumeRole adapters, the configured regions,
  `excluded_regions`, the global advisory lock and the bounded account/region
  worker pool. Collection runs after instances and load balancers in the same
  sync; a network failure never stops instance or LB collection.
- Opt-in: `CLOUDSCOPE_NETWORK_ENABLED=false` by default; Helm
  `collector.networkEnabled` sets it for API/manual sync and the CronJob. One
  flag covers both resource types.
- Each resource type per account/region is atomic, with the same rules as load
  balancers: only a complete successful snapshot marks unseen rows missing
  (`present=false`); errors, bad pagination or malformed pages keep previous rows
  and timestamps. Store sanitized error code, last attempt and last success in
  `network_scans` (provider, account_id, region, resource_type), with
  `resource_type` in `elastic_ip`, `nat_gateway`.
- Every row keeps tags, the raw provider payload, first seen, last observed and
  present. No extra calls beyond the ones listed below.

### Elastic IPs (T-081, migration `0012`)

Migration `0012` creates `elastic_ips` and `network_scans`. Identity: provider,
account, region, allocation ID.

| Field | AWS `ec2:DescribeAddresses` | Alibaba `vpc:DescribeEipAddresses` |
| --- | --- | --- |
| allocation_id | `AllocationId` | `AllocationId` |
| public_ip | `PublicIp` | `IpAddress` |
| name | `Name` tag, else empty | `Name` |
| status | `associated` if `AssociationId`, else `available` | `InUse` → `associated`, `Available` → `available`, other values kept lower-case |
| associated_type | `instance` if `InstanceId`, else `network_interface` if `NetworkInterfaceId`, else none | `EcsInstance` → `instance`, `SlbInstance` → `load_balancer`, `Nat` → `nat_gateway`, `NetworkInterface` → `network_interface`, others kept as given |
| associated_id | `InstanceId`, else `NetworkInterfaceId` | `InstanceId` |
| private_ip | `PrivateIpAddress` | `PrivateIpAddress` |
| network_interface_id | `NetworkInterfaceId` | `InstanceId` when type is `NetworkInterface` |
| bandwidth / charge_type | none | `Bandwidth`, `InternetChargeType` |

AWS `DescribeAddresses` is one call per region (no pagination). Alibaba pages
with `PageNumber`/`PageSize=100`.

AWS does not name a NAT gateway or NLB in `DescribeAddresses`; the API resolves
those by allocation ID (below).

### NAT gateways (T-082, migration `0013`)

Migration `0013` creates `nat_gateways`. Identity: provider, account, region,
NAT gateway ID.

- AWS `ec2:DescribeNatGateways` with `NextToken`. Fields: name (`Name` tag),
  state, connectivity type (`public`/`private`), VPC, subnet, and addresses from
  `NatGatewayAddresses` (allocation ID, public IP, private IP, ENI).
- Alibaba `vpc:DescribeNatGateways` with `PageNumber`/`PageSize=50`. Fields:
  name, status, `NatType`, network type (`internet`/`intranet`), spec, VPC,
  vSwitch, private IP from `NatGatewayPrivateInfo.PrivateIpAddress`, and
  addresses from `IpLists` (allocation ID, IP).
- Deleted gateways (AWS state `deleted`) are stored like any other row with
  their state; the list hides them unless "Include missing" is on.

## Association links

The API resolves each Elastic IP to a link at read time, from data already in the
database (no cloud call). `association` is `null` for an available EIP, else
`{type, id, link}`. `link` is the identity of a present row in the same
provider/account/region, or `null` when that resource is not in the inventory:

- `instance`: the instance with that ID → `/instances/{provider}/{account}/{region}/{id}`.
- `nat_gateway`: Alibaba by `associated_id`; AWS by a NAT gateway whose
  addresses contain the EIP's allocation ID (overrides `network_interface`).
- `load_balancer`: Alibaba CLB by `associated_id`; AWS NLB whose raw
  `AvailabilityZones[].LoadBalancerAddresses[].AllocationId` contains the
  allocation ID (overrides `network_interface`).
- `network_interface`: shown as text with a copy icon; no page yet.

The NAT gateway list and details show each address's EIP linked to its EIP
details page. Instance details show a new **Elastic IPs** row (public IP linked
to the EIP details page).

## API

All endpoints require a full authenticated session and never mutate cloud
resources. Same paging (`page` default 1, `page_size` default 50, max 500),
stable ordering, literal wildcards and `include_missing` (default false) as load
balancers. List responses omit raw data; details add raw and first_seen; an
unknown identity returns 404.

- `GET /api/elastic-ips`: `q` (public IP, private IP, allocation ID, name,
  associated ID, account name/alias/ID), provider, account_id, region,
  `status` (`associated`/`available`), `associated_type`.
- `GET /api/elastic-ips/{provider}/{account}/{region}/{allocation_id}`.
- `GET /api/nat-gateways`: `q` (name, ID, IP, VPC, account), provider,
  account_id, region, state.
- `GET /api/nat-gateways/{provider}/{account}/{region}/{id}`.
- `GET /api/network/scans`: enabled flag and per account/region/type status.
- `GET /api/instances/{provider}/{account}/{region}/{id}` gains
  `elastic_ips: [{public_ip, allocation_id}]` (present EIPs whose association is
  this instance).

## UI

Sidebar: **Elastic IPs** and **NAT gateways** under Load balancers. Both pages
look and behave like the Load balancers page: search, filters, pagination and
"Include missing" are shareable URL parameters; 30-second refresh while visible;
copy icons; floating scrollbar; explicit failed, disabled and never-run scans;
an empty list is never presented as proof that none exist.

- **Elastic IPs** columns: Public IP (copy), Name, Status, Associated with,
  Private IP, Account (name + ID with copy), Region, Observed, View.
  - *Associated with* shows the type and ID; when `link` is set it is a link to
    that resource's page.
  - Clicking a row opens the linked resource's page when `link` is set, else the
    EIP details page. The View icon always opens the EIP details page. Links,
    copy icons and buttons inside a row do not trigger the row click. The row is
    keyboard reachable (Enter opens the same target).
  - Filters: provider, account, region, status, associated type.
- **EIP details** `/elastic-ips/:provider/:account/:region/:id`: "Back to
  Elastic IPs", all fields, the association link, tags and raw JSON.
- **NAT gateways** columns: Name, ID (copy), State, Type, Public IPs (EIP links),
  Private IPs, VPC, Account, Region, Observed, View. Row click and View open
  **NAT details** `/nat-gateways/:provider/:account/:region/:id` ("Back to NAT
  gateways", addresses with EIP links, VPC/subnet, tags, raw JSON).

## Permissions and rollout

Operators grant these reads before setting `networkEnabled=true`:

- AWS: `ec2:DescribeAddresses` (T-081) and `ec2:DescribeNatGateways` (T-082),
  added to `deploy/aws/readonly-role.yaml` and the
  [cloud-access](cloud-access.md) policy block.
- Alibaba: `vpc:DescribeEipAddresses` and `vpc:DescribeNatGateways`, already in
  `AliyunVPCReadOnlyAccess`; the template documents them.

No new dependencies: boto3 and the Alibaba VPC SDK already cover these APIs.
Migrations are additive; older images run fine against the added tables.

### T-081 implementation notes

Elastic IP `associated_type` filtering uses the normalized provider field;
`association` contains the separately resolved inventory target (for example an
AWS `network_interface` can resolve to a present NLB). NAT inventory and NAT
allocation resolution follow in T-082. Alibaba pagination requires a stable
`TotalCount`; a missing/changing total, unexpected page number, duplicate ID or
premature empty page fails the snapshot without retiring earlier rows.

Provider references: [AWS DescribeAddresses](https://docs.aws.amazon.com/botocore/latest/reference/services/ec2/client/describe_addresses.html)
and [Alibaba DescribeEipAddresses](https://www.alibabacloud.com/help/en/eip/developer-reference/api-vpc-2016-04-28-describeeipaddresses-eips).
