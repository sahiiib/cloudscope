# Contributing to Cloudscope

`sahiiib/cloudscope` is the shared source of truth. Contributors work on short-lived
branches in their forks and submit PRs to its `main`. The maintainer reviews and
merges; authors do not merge their own PRs. Follow [AGENTS.md](AGENTS.md),
[docs/TASKS.md](docs/TASKS.md) and each task's specifications.

## Start and submit a task

1. Open an issue with the problem, expected behavior, acceptance criteria and
   proposed owner. Agree on scope before overlapping work starts.
2. Read the relevant specification. Discuss changes to its design in the issue.
3. Start with a clean working tree and branch from current upstream `main`.

For a fork cloned as `origin`, configure `upstream` once (check `git remote -v`
first; do not add it again if already configured):

```sh
git remote add upstream https://github.com/sahiiib/cloudscope.git
git fetch upstream
git switch -c codex/T-XXX-short-slug upstream/main
```

Keep the fork's `main` as an upstream mirror and feature work on task branches.
To update local `main`, switch to it explicitly, then return to your task branch:

```sh
git fetch upstream
git switch main
git merge --ff-only upstream/main
git switch codex/T-XXX-short-slug
```

If the fast-forward fails, stop and inspect the divergence rather than resetting
or force-pushing away work.

Run `make lint` and `make test`, plus checks appropriate to the change. On Windows,
use the equivalent backend `uv` and frontend `npm` commands from the Makefile.
Tests use disposable databases, never a shared application database. Container
changes also need the image smoke check. Documentation-only PRs need link,
command and template review rather than artificial implementation tests.

```sh
git add <changed-files>
git commit -m "T-XXX: Describe the resulting behavior"
git push -u origin codex/T-XXX-short-slug
```

Open a draft PR with **base** `sahiiib/cloudscope:main` and **head** your fork's
task branch. Link the issue/task; describe behavior, validation, migration impact
and open questions. Set the task to `review`. Resolve comments and checks; the
maintainer approves and can squash-merge. Update shared branches by merging
upstream; reserve rebase for unpublished personal branches.

## Maintainer repository controls

Protect upstream `main`: require one approving review, resolved conversations
and passing CI backend/frontend/secret-scan and Images smoke/multiarch checks.
Confirm exact check names from successful PR runs before requiring them. Block
force pushes and branch deletion. Keep deployment credentials in the upstream
deployment environment, outside forks. These are maintainer settings; this
document does not enable them. Review and deployment permissions are separate.

## Release and deployment

The Images workflow builds PR images and publishes upstream `main` images to
GHCR. A successful build does not itself deploy the application.

1. Build the reviewed upstream commit in CI; record its SHA and both image digests.
2. Deploy those images to staging with its own DB, credentials, release and values.
3. Verify login, account visibility, search and collection. Review migrations
   and back up the database before shared rollout.
4. A designated operator promotes the **same tested digests** to the shared
   environment. Never deploy an ambiguous `latest` tag.
5. Record release/revision, image digests, migration head, verification and recovery
   instructions. Check readiness and collection after deployment.

The current chart accepts `repository` and `tag`, without a separate `digest`
value. Set each tag to `sha-<commit>@sha256:<digest>` so the rendered image uses
both the commit tag and the immutable digest (the digest determines the image):

```yaml
# Merge these entries into your environment-specific values file.
# Replace each placeholder with the reviewed commit and its recorded image digest.
image:
  backend:
    repository: ghcr.io/sahiiib/cloudscope-backend
    tag: "sha-<full-commit-sha>@sha256:<backend-image-digest>"
  web:
    repository: ghcr.io/sahiiib/cloudscope-web
    tag: "sha-<full-commit-sha>@sha256:<web-image-digest>"
```

Render before deploying, using the same image entries in staging and production:

```sh
helm template cloudscope deploy/helm/cloudscope -f values.staging.yaml
helm upgrade --install cloudscope deploy/helm/cloudscope \
  --namespace cloudscope-staging --create-namespace \
  --wait --timeout 10m -f values.staging.yaml
```

The backend entry also pins the collector and migration Job. Keep each
environment's database, credentials and other values separate; only promote the
tested image entries. See the [chart configuration](deploy/helm/cloudscope/README.md)
for prerequisites and migration ordering.

Until automation exists, use one designated operator and a written release record.
Two contributors must not independently upgrade the same release. Automated
deployment should use environment approval and a concurrency group per environment.

## Database compatibility and recovery

Migration IDs and parent revisions belong to the shared project. Coordinate them
in review. Never edit an applied migration, reuse its ID for a different schema or
stamp a database to hide incompatibility. Prefer additive changes readable by the
previous image, removing old fields in a later coordinated release.

Helm rollback does not automatically reverse database changes or restore data.
Document whether the previous image can use the new schema or recovery needs a
tested backup restore or forward fix. Trial migrations/recovery on a disposable DB.

When reconciling a divergent fork, compare **actual schema and migration contents**,
not just Alembic revision strings. Preserve a backup and review an explicit
reconciliation plan before deploying upstream code against a fork database.

## Credentials

Keep kubeconfig, DB dumps, cloud keys, `.env`, `config/accounts.yaml` and runtime
Secrets out of commits and issue/PR attachments. Use placeholder IDs and addresses.
Cloud calls stay read-only. Development, staging and shared deployments use
separate databases and credentials.
