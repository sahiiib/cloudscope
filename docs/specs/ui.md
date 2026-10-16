# Web UI

React + TypeScript + Vite. Plain, fast, data-dense. Light and dark mode follow
the OS. No component library is required; if one is used, prefer a small one
(e.g. Radix primitives + CSS modules). All API calls go to the same origin
under `/api` and send `X-Requested-With: cloudscope`.

## Pages

### Login (`/login`)
Username + password. If the API answers `mfa_required`, show a 6-digit code
step. Errors are shown inline.

### Instances (`/`)

Shown as "Instances" in the navigation and heading (named Search before T-075).
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
| Account | `account_name` |
| Account alias | `account_alias` ("–" if null) |
| Account ID | `account_id` (copy button) |
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
- Admin only, on the Accounts page (`/accounts`) since T-075: **Cloud accounts** ([accounts.md](accounts.md)). Table of all
  accounts (provider, name, cloud alias, ID, regions, role, source, enabled, last success,
  instance count). Add and edit forms for `ui` accounts; `file` accounts are
  read-only with a "Managed by accounts.yaml" label. Enable/disable with an
  inline confirmation. "Test access" shows the result inline.

## App shell implementation (T-030)

The shell checks `/api/auth/me` before rendering protected routes. A 401 returns
to login and preserves the requested in-app path; a network/server failure shows
a retry action. Login and MFA failures remain inline, including rate limiting.
Passwords/codes stay only in component state and are cleared after submission;
no tokens or credentials are written to browser storage. A user menu shows the
username/role and logout. Successful login/logout clears the query cache.

Search, Sync and Settings are described in their own sections below. Layout
adapts to narrow screens and OS light/dark preference. The shared HTTP client still redirects other 401s; the
route guard explicitly handles its own redirect to retain the destination.

## Search implementation (T-031)

The search route now fetches inventory and facets with TanStack Query. Search is
sent after 300 ms; repeatable filters, missing visibility, sort and pagination
are shareable URL parameters and restore on browser navigation. Changing a
filter/sort/page size resets pagination. The default size is 50 (maximum 500).
Rows expose detail links for T-032, ID copy, state badges, all default fields,
relative launch dates with exact timestamps, and the first three tags. Loading,
empty and retryable error states are inline; facet counts can fail independently
of inventory. Previous rows, pagination and facet options stay visible while
new query results load, with an Updating indicator. No inventory or credentials
are persisted in browser storage.

## Sync implementation (T-033)

The Sync route loads the latest 20 runs and refreshes every five seconds while
a run is in progress, or every thirty seconds when idle, while visible. Expanding
a run fetches its per-account/region results, including errors and duration; unfinished details also refresh until complete. Cached history
remains visible during a refetch failure. Administrators can request a manual
sync; the button is disabled while a request or a known run is active. Conflicts
and unavailable collection are shown inline and history is refreshed after the
request. A 403 explains that permission was lost and asks the user to reload
to refresh access. Non-admin users only see history and refresh controls.

## Settings implementation (T-034)

Settings includes password changes, authenticator enrollment/confirmation and
disable, plus an administrator-only user list and create/deactivate/reactivate/
reset-MFA controls. Destructive user changes require an inline confirmation.
Password changes and successful self-admin mutations clear cached data and return
to login because the API revokes the current session. Last-admin conflicts,
duplicate usernames and invalid credentials/codes remain actionable inline.

Passwords/codes are cleared after submission and are never mutation variables.
The enrollment QR is displayed locally as an image, not injected HTML or sent to
an external QR service. Provisioning data stays in mounted component state only,
outside query/mutation caches, and is removed after confirmation/cancel/navigation.
MFA changes refresh the shell's current-user state and the admin users list.

## Instance details implementation (T-032)

The protected details route loads an instance using all four identity fields.
Summary, Tags, Network, Security groups and Raw JSON are separate components
using the shared normalized provider data. Optional/missing values show
"Not available"; empty security rule arrays explicitly show "No rules". Network
IDs remain visible when enriched VPC/subnet details are absent. Alibaba rules
also expose policy, priority and source ports. Timestamps include their exact
UTC offset; a missing instance keeps its last observed data with a clear notice.
404 and retryable request failures have separate states. Raw JSON is collapsible,
rendered as text, and copied locally with clipboard success/failure feedback.

## Cloud accounts implementation (T-061)

Settings shows Cloud accounts only for administrators. File-managed rows display
"Managed by accounts.yaml" and offer only a read-only access test. UI-managed
accounts have add/edit forms; provider and ID are fixed after creation. Blank
optional role/external-ID fields clear those values. Validation runs locally
and server 422/409 errors remain beside the relevant field.

Enable/disable requires inline confirmation and preserves existing inventory.
Access tests display a region count or the sanitized provider error in the row;
editing connection settings clears the previous test result. Successful writes
invalidate account lists, search facets/results, instance details and sync queries,
so the next view uses updated labels and configuration.

## Account identity implementation (T-062)

Search has separate Account, Account alias and Account ID columns; the account
ID copy button reports success or failure without opening the instance. Details
Summary has separate Account name, Account alias and Account ID rows. Settings
also shows the cloud alias. Unknown/absent aliases display "–". Free-text search
includes account names, aliases and IDs as well as the instance fields.

## Load balancer page (T-069)

See [load-balancers.md](load-balancers.md) for the additive schema, read-only
operations, per-family failure behavior, API and opt-in rollout.
## Modern console (T-068)

The console uses a responsive sidebar and consistent card, table, form and
status styles. Administrators have a dedicated `/accounts` route; the Settings
section remains available for compatibility. Members cannot administer accounts
on either route. Search overview figures distinguish filtered inventory counts
from the total configured account count.

Appearance can be Light, Dark or System. System follows OS changes through CSS.
Only the validated preference is stored as `cloudscope.theme`; unavailable
storage does not block use. Login also offers the picker. Keyboard focus, skip
navigation, reduced motion and narrow-screen layouts are supported. No external
fonts, trackers or new dependencies are needed.

## UI polish (T-075)

- Page `/` is titled **Instances**.
- Filter dropdowns: the page owns which one is open; opening one closes the
  others, and a click outside the filter bar or Esc closes it.
- Wide tables (instances, load balancers, LB scan status) use `FloatingScroll`:
  their own horizontal scrollbar is hidden and a synced copy sticks to the bottom
  of the window while the table is on screen (T-078).
- State column: an icon (running, stopped, terminated, other) with the state as
  accessible name and tooltip. Copy buttons are icon buttons labelled
  `Copy <instance id>` / `Copy account ID <id>`.
- Accounts row actions (Manage in web, Edit, Enable/Disable, Test access,
  Delete) are icon buttons with the same accessible names and a tooltip.
- Settings: page heading, "Your security" (password, MFA) and, for admins,
  "Administration" (users). Cloud accounts are only on `/accounts`.
- Load balancers page (T-078): same floating scrollbar, State icon, copy icon for
  the account ID and an icon button for View/Hide details.


## Account dialog (T-077)

Accounts Add/Edit opens a named modal, traps focus, supports Escape/Cancel with
an unsaved-change confirmation, and restores focus to the opening button. Test
connection checks current values before save and shows a region checklist where
checked means excluded. Keys clear after the test and need re-entry for save;
they never enter React Query caches or browser storage. Existing row Test access
continues to check the saved connection. Mutations/tests disable the form while
pending; changing connection fields clears stale preview results.

## Region picker (T-079)

The Account dialog's Select regions button replaces Test connection and appears
under the Regions field. Edit immediately loads the account's known regions with
instance and load balancer counts. Checkbox semantics are now **checked = scan**;
unchecked regions are saved as `excluded_regions`. A preview merges newly discovered
regions with zero counts without discarding existing choices. An entirely unchecked
list displays "Keep at least one region" and blocks save. Region-list load errors
can be retried independently of preview errors.

Edit previews use that account's saved Dedicated keys when key fields are blank;
Add still requires supplied keys. New keys override saved keys for preview only,
are cleared afterward, and must be re-entered to save a rotation. No saved keys or
Secret references are sent to the browser.
