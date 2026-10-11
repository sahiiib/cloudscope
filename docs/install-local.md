# Install on the local cluster

How to run cloudscope on the 3-node kubeadm cluster on Proxmox. The general
chart reference is [deploy/helm/cloudscope/README.md](../deploy/helm/cloudscope/README.md);
the design is in [specs/deployment.md](specs/deployment.md#local-cluster-kubeadm-3-nodes-on-proxmox).

What this cluster has, and what the guide assumes:

| Need | On this cluster |
|---|---|
| Storage | `local-path-provisioner`, StorageClass `local-path` (not default, reclaim policy `Delete`, data on one node's disk) |
| Pod CIDR | Calico pool `10.244.0.0/16`, does not overlap the LAN |
| Ingress | Istio: `istio-ingressgateway` Service, NodePort `31008` (HTTP) / `32497` (HTTPS); no MetalLB |
| CNI | Calico, which enforces the chart's NetworkPolicies |
| Exposure | LAN only. No cloudflared tunnel: the app is not on the internet |

Run every command from a machine with `kubectl` and `helm` (3.x) pointed at
the cluster, inside a checkout of this repository.

## 1. Check the cluster

```sh
kubectl get storageclass                        # expect local-path
kubectl get ippools -o yaml | grep -i cidr      # Calico pod CIDR, for step 4
kubectl get ingressclass                        # is there one named istio?
kubectl -n istio-system get svc istio-ingressgateway
```

If `kubectl get ingressclass` shows no `istio` class, create it once. istiod
only serves Ingress objects whose class points at its controller:

```sh
kubectl apply -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: IngressClass
metadata:
  name: istio
spec:
  controller: istio.io/ingress-controller
EOF
```

## 2. Namespace

```sh
kubectl create namespace cloudscope
kubectl get namespace cloudscope --show-labels   # must NOT have istio-injection=enabled
```

The chart is not built for sidecars: the migration Job would never finish
with an Envoy sidecar next to it. Leave injection off for this namespace.

## 3. Secrets (typed in your shell, never stored in the repo or pasted in chat)

`read -s` keeps the values out of shell history and off the screen.

```sh
read -rs -p 'AWS access key id: ' AWS_ID; echo
read -rs -p 'AWS secret access key: ' AWS_SECRET; echo
read -rs -p 'Alibaba access key id: ' ALI_ID; echo
read -rs -p 'Alibaba access key secret: ' ALI_SECRET; echo
PG_PASS="$(openssl rand -hex 24)"
FERNET="$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"

kubectl -n cloudscope create secret generic cloudscope \
  --from-literal=POSTGRES_PASSWORD="$PG_PASS" \
  --from-literal=DATABASE_URL="postgresql+psycopg://cloudscope:${PG_PASS}@cloudscope-postgres:5432/cloudscope" \
  --from-literal=SECRET_KEY="$FERNET" \
  --from-literal=AWS_ACCESS_KEY_ID="$AWS_ID" \
  --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET" \
  --from-literal=ALIBABA_CLOUD_ACCESS_KEY_ID="$ALI_ID" \
  --from-literal=ALIBABA_CLOUD_ACCESS_KEY_SECRET="$ALI_SECRET"

unset AWS_ID AWS_SECRET ALI_ID ALI_SECRET PG_PASS FERNET
```

`SECRET_KEY` encrypts TOTP secrets in the database. If it is lost, every user
must enroll MFA again, so keep a copy in your password manager.

The images live in GHCR under a private repository, so the nodes need a pull
secret. Use a GitHub personal access token with only `read:packages`:

```sh
read -rs -p 'GHCR token (read:packages): ' GHCR_TOKEN; echo
kubectl -n cloudscope create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io --docker-username=sahiiib --docker-password="$GHCR_TOKEN"
unset GHCR_TOKEN
```

## 4. Values

```sh
cp deploy/helm/values.local.example.yaml deploy/helm/values.local.yaml   # git-ignored
git rev-parse origin/main                                                # the commit to deploy
```

Edit `deploy/helm/values.local.yaml`:

- `image.backend.tag` and `image.web.tag`: `sha-<that full sha>`. Check that
  the "images" workflow succeeded for that commit first, since it pushes the tags.
- `accounts`: your real accounts, same shape as `config/accounts.yaml`.
- `api.forwardedAllowIPs`: already `10.244.0.0/16`, the Calico pool. Change
  it only if step 1 shows a different CIDR.
- `api.cookieSecure: false` stays only while the app is plain HTTP.

## 5. Install

```sh
helm lint deploy/helm/cloudscope -f deploy/helm/values.local.yaml
helm upgrade --install cloudscope deploy/helm/cloudscope -n cloudscope \
  -f deploy/helm/values.local.yaml --wait --timeout 10m
kubectl -n cloudscope get pods,pvc,ingress,cronjob
```

On the first install the migration Job runs after the pods are up (see the
chart README, "Migration order"); `helm` returns once it has finished.

Create the first admin. The password is prompted twice and not echoed:

```sh
kubectl -n cloudscope exec -it deploy/cloudscope-api -- cloudscope create-user admin --admin
```

## 6. Open it

On each machine that should reach the app, add one node's LAN IP to the hosts
file (`/etc/hosts`, or `C:\Windows\System32\drivers\etc\hosts`):

```
<node-lan-ip>  cloudscope.home.arpa
```

Then open `http://cloudscope.home.arpa:31008`, log in, and enable MFA under
Settings. A local DNS record on your router works too and saves editing hosts files.

## 7. Verify (T-043 acceptance)

Run one collection now instead of waiting for the schedule:

```sh
kubectl -n cloudscope create job --from=cronjob/cloudscope-collector collect-manual
kubectl -n cloudscope logs -f job/collect-manual
kubectl -n cloudscope delete job collect-manual
```

The Sync page should show the run, and Search the instances (34 on the test
accounts). The CronJob runs every 15 minutes:

```sh
kubectl -n cloudscope get cronjob cloudscope-collector    # SCHEDULE */15 * * * *
kubectl -n cloudscope get jobs --watch
```

## Upgrade

Set the new `sha-<sha>` in both image tags, then rerun the `helm upgrade
--install` command from step 5. Migrations run before the new pods roll out.

## Client IPs and the login rate limit

The login rate limit counts attempts per client IP. Traffic reaches the API
through NodePort, then the Istio gateway, then the web pod's nginx. Two
consequences on this cluster:

- The Istio gateway Service uses `externalTrafficPolicy: Cluster`, so
  kube-proxy replaces your browser's IP with a node IP. All LAN users then
  share up to three "client IPs". That is fine for a single admin. To see real
  client IPs, set `externalTrafficPolicy: Local` on `istio-ingressgateway`;
  this changes a shared component, so do it only if the other apps behind the
  gateway are fine with it.
- `forwardedAllowIPs` must cover only pod addresses. `10.244.0.0/16` does not
  overlap the LAN, so a LAN machine cannot forge `X-Forwarded-For` to dodge
  the limit. Keep it that way if the pool or the LAN ever changes.

## Data and backup

`local-path` keeps the Postgres data on the node that first ran the pod; the
pod stays pinned to that node. Losing that node loses the inventory and the
users (the inventory comes back with the next sync; users and MFA do not).
Back up with:

```sh
kubectl -n cloudscope exec cloudscope-postgres-0 -- pg_dump -U cloudscope cloudscope > cloudscope-$(date +%F).sql
```

Move to Longhorn when the data must survive a node loss.

## Uninstall

```sh
helm uninstall cloudscope -n cloudscope
kubectl -n cloudscope get pvc     # the Postgres PVC survives uninstall
```

`local-path` uses reclaim policy `Delete`: deleting that PVC (or the namespace)
deletes the database files on the node. Take a `pg_dump` first.
