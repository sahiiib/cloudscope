# Web UI

React + TypeScript + Vite. Plain, fast, data-dense. Light and dark mode follow
the OS. No component library is required; if one is used, prefer a small one
(e.g. Radix primitives + CSS modules). All API calls go to the same origin
under `/api` and send `X-Requested-With: cloudscope`.

## Pages

### Login (`/login`)
Username + password. If the API answers `mfa_required`, show a 6-digit code
step. Errors are shown inline.

### Search (`/`)
- Search box (debounced 300 ms) → `q`.
- Filters: provider, account, region, state (multi-select, counts from
  `/api/instances/facets`), "show terminated/missing" toggle.
- Filters and query are kept in the URL so a search can be shared.
- Table columns (default list fields):

| Column | Source |
| --- | --- |
| Name | `name` |
| Instance ID | `instance_id` (copy button) |
| State | `state` (colored badge) |
| Type | `instance_type` |
| Private IPs | `private_ips` |
| Public IPs | `public_ips` |
| Account | `account_name` + `account_id` |
| Region | `region` |
| Provider | `provider` (icon or label) |
| Launch time | `launch_time` (relative + exact on hover) |
| Tags | first 3 as chips, `+N` |

- Sortable columns, pagination, page size 50.
- Clicking a row opens the details page.

### Instance details (`/instances/:provider/:account/:region/:id`)

Sections:
1. **Summary**: all list fields + zone, platform, image, key pair, CPU,
   memory, first seen, **last observed**, present/missing.
2. **Tags**: full key/value table.
3. **Network**: VPC (id, name, CIDR), subnet / vSwitch, network interfaces
   with their IPs.
4. **Security groups**: one card per group with inbound and outbound rules.
5. **Raw JSON**: collapsible, with copy button.

The detail field list will grow; each section is its own component reading
from `details` so new fields are easy to add.

### Sync status (`/sync`)
Last 20 runs (time, trigger, status, instance count, duration). Expanding a run
shows per account/region results with errors. Admins get a "Sync now" button.

### Settings (`/settings`)
- Change password.
- Enable MFA (show QR, confirm code) / disable MFA.
- Admin only: users list, create user, deactivate, reset MFA.

## App shell implementation (T-030)

The shell checks `/api/auth/me` before rendering protected routes. A 401 returns
to login and preserves the requested in-app path; a network/server failure shows
a retry action. Login and MFA failures remain inline, including rate limiting.
Passwords/codes stay only in component state and are cleared after submission;
no tokens or credentials are written to browser storage. A user menu shows the
username/role and logout. Successful login/logout clears the query cache.

Search, Sync and Settings currently have protected placeholder pages; their full
content belongs to T-031, T-033 and T-034. Layout adapts to narrow screens and OS
light/dark preference. The shared HTTP client still redirects other 401s; the
route guard explicitly handles its own redirect to retain the destination.

## Search implementation (T-031)

The search route now fetches inventory and facets with TanStack Query. Search is
sent after 300 ms; repeatable filters, missing visibility, sort and pagination
are shareable URL parameters and restore on browser navigation. Changing a
filter/sort/page size resets pagination. The default size is 50 (maximum 500).
Rows expose detail links for T-032, ID copy, state badges, all default fields,
relative launch dates with exact timestamps, and the first three tags. Loading,
empty and retryable error states are inline; facet counts can fail independently
of inventory. No inventory or credentials are persisted in browser storage.
