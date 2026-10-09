# Roadmap

Each phase ends with something usable. Task IDs refer to [TASKS.md](TASKS.md).

## Phase 0: Foundation

Goal: an empty but runnable skeleton with CI.

- Backend and frontend project scaffolds, linting, tests, CI (T-001 to T-004)
- Database schema and migrations (T-005)
- Accounts config loader (T-006)

Done when: `make test` and CI pass on an empty app, and migrations create all tables.

## Phase 1: Collector MVP

Goal: the database holds a correct, fresh inventory of every instance.

- AWS EC2 collector (T-010)
- Alibaba ECS collector (T-011)
- Sync orchestration, sync run history, "missing" detection (T-012)
- `cloudscope collect` CLI (T-013)

Done when: one `cloudscope collect` run with the test keys fills `instances` for
all configured accounts and regions, and a second run updates `last_observed`.

## Phase 2: API, login and search UI

Goal: people can log in and find any instance.

- Auth: users, password login, sessions, TOTP MFA (T-020 to T-022)
- Instances, accounts and sync API (T-023)
- UI: login + MFA screens (T-030)
- UI: search page with filters (T-031)
- UI: instance details page (T-032)
- UI: sync status page (T-033)

Done when: a user logs in (with MFA if enabled), searches by name, ID, IP or tag,
filters by provider/account/region/state, and opens a details page.

## Phase 3: Local Kubernetes deployment

Goal: running on the 3-node kubeadm cluster (Proxmox).

- Dockerfiles (T-040)
- Helm chart: API, UI, collector CronJob, PostgreSQL, ingress (T-041)
- Local install guide incl. StorageClass (T-042)

Done when: `helm install` on the local cluster gives a working app and the
CronJob syncs every 15 minutes.

## Phase 4: Production on EKS

Goal: production deployment with no long-lived AWS keys.

- Read-only roles in all AWS accounts via StackSet, RAM roles in all Alibaba
  accounts (T-050, T-051)
- EKS Pod Identity / IRSA for the collector, Alibaba key in Secrets Manager (T-052)
- Optional external PostgreSQL (RDS) (T-053)

Done when: the EKS deployment syncs all ~20 accounts with no static AWS keys.

## Later (not scheduled)

- More detail fields (list is expected to grow)
- SSO login (OIDC)
- Export to CSV
- Change history per instance
- More resource types (RDS, load balancers, ...)
