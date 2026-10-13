# Load balancer inventory (T-069)

Assigned by the fork contributor. Cloud access remains read-only. This task adds
basic inventory for AWS ALB, NLB, GWLB and Classic, and Alibaba CLB, ALB and NLB.
Listeners, target health and backend topology are outside this first increment;
the UI never implies that a provisioned load balancer or its targets are healthy.
Classic ELB does not expose an overall state here, so its state is `unknown`.

## Collection and persistence

- Reuse the existing account/base-credential/AssumeRole adapters and configured
  EC2/ECS regions. No separate credentials or discovery of unconfigured regions.
- AWS: `DescribeLoadBalancers` on ELBv2 and Classic, using `Marker`/`NextMarker`.
- Alibaba: CLB `DescribeLoadBalancers` with page numbers; ALB/NLB
  `ListLoadBalancers` with continuation tokens. ALB selects its region by endpoint.
- New migration `0007` creates `load_balancers` and `load_balancer_scans` without
  changing account, instance, user or session data. Identity includes provider,
  account, region, API family and resource ID; AWS ELBv2 IDs are full ARNs.
- Fields: name, type, provider state, scheme, addresses, VPC, availability zones,
  returned tags, raw provider payload, first seen, last observed and present.
  No extra tag or network calls. AWS tags are currently empty.
- Each family is atomic. Only a complete successful snapshot may mark that
  family's unseen rows missing. Errors, repeated tokens, duplicate/mismatched
  identities and malformed pages preserve previous data and timestamps.
- Store sanitized error codes, last attempt and last success per account/region/
  family. One failed family does not discard another family's snapshot or stop
  instance collection. Existing Sync summaries/counts still describe instances;
  LB errors and completeness are shown on the Load balancers page.
- CLI and manual sync share their existing global advisory lock. LB collection
  uses the existing bounded account/region worker pool.

## API and UI

All endpoints require a full authenticated session. None mutate cloud resources.

- `GET /api/load-balancers`: `q`, provider, account_id, region, kind,
  include_missing (default false), page (default 1), page_size (default 50,
  maximum 500). Stable name/ID ordering. Returns items, total, page, page_size.
  Search matches name, resource ID, address, VPC and account name/alias/ID;
  wildcard characters are literal. List responses omit raw data.
- `GET /api/load-balancers/scans`: enabled flag and per-family scan status.
- `GET /api/load-balancers/{provider}/{account}/{region}/{family}/{id}`:
  full identity, including URL-encoded AWS ARNs. Returns raw and first_seen
  in addition to list fields; absent identity returns 404.
- `/load-balancers`: navigation available to all authenticated users. Search,
  filters, pagination and missing visibility are shareable URL parameters.
  Refresh every 30 seconds while visible. Accessible details button reveals
  metadata/raw text. Failed, disabled and never-run scans are explicit; an empty
  list is never described as proof that the cloud has no load balancers.

## Deployment

Collection is opt-in: `CLOUDSCOPE_LOAD_BALANCERS_ENABLED=false` by default;
Helm `collector.loadBalancersEnabled` sets the flag for API/manual and CronJob.
Operators grant exactly these additional reads before enabling:

- AWS `elasticloadbalancing:DescribeLoadBalancers`.
- Alibaba `slb:DescribeLoadBalancers`, `alb:ListLoadBalancers`,
  `nlb:ListLoadBalancers`.

The templates document these permissions; this PR does not apply IAM/RAM changes.
New dependencies are the three official Alibaba LB SDKs, required because ECS/VPC
SDKs do not implement these APIs. Existing dependency versions remain unchanged.

Release process: maintainer reviews/merges; build the approved source, verify both
images in an isolated environment, record image digests, back up and restore-test
the current database, then upgrade the coordinated shared release with collection
initially disabled. Inspect readiness and instance/account preservation, grant
read permissions and enable LB collection. Confirm successful scans for every
enabled account/region/family before calling the inventory complete.

Migration is additive. An older image can run against the added tables; routine
Helm rollback should leave those tables intact. An explicit `0007` downgrade
deletes only LB history and requires an operator's backup/recovery decision.

Official API references:
[AWS ELBv2](https://docs.aws.amazon.com/boto3/latest/reference/services/elbv2/client/describe_load_balancers.html),
[Alibaba CLB](https://www.alibabacloud.com/help/en/slb/classic-load-balancer/developer-reference/api-slb-2014-05-15-describeloadbalancers),
[Alibaba ALB](https://www.alibabacloud.com/help/en/slb/application-load-balancer/developer-reference/api-alb-2020-06-16-listloadbalancers),
[Alibaba NLB](https://www.alibabacloud.com/help/en/slb/network-load-balancer/developer-reference/api-nlb-2022-04-30-listloadbalancers).
