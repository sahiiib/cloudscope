# AWS inventory roles

`hub-role.yaml` creates the named `cloudscope-hub` role. Supply `ClusterArn`
and optionally `Namespace` (default `cloudscope`). Trust is limited to EKS Pod
Identity with the selected cluster/namespace and the `cloudscope` service account.
Its permission policy only allows assuming `cloudscope-readonly` roles.

`readonly-role.yaml` is the StackSet template for target accounts. Supply the hub
`RoleArn` output as `HubRoleArn` and use the same `ExternalId` (default
`cloudscope`) in each account's collector configuration. The EC2 permission list
matches [cloud-access.md](../../docs/specs/cloud-access.md) exactly. Both templates
require `CAPABILITY_NAMED_IAM`; because IAM is global, deploy once per account,
not once per inventory region. Existing roles with the same names require an
explicit import/migration decision before rollout.

Trust policies allow `sts:TagSession`: EKS Pod Identity adds transitive session
tags and the target role must accept them during role chaining. This grants no
EC2 write permissions. Keep Pod Identity session tags enabled because the hub
trust evaluates them. See the official [Pod Identity trust policy](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-role.html),
[transitive tags](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-abac.html),
and [session tag trust requirements](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_session-tags.html).

T-052 handles rollout; T-053 handles EKS association/configuration. These files
do not create a cluster, access keys or a Pod Identity association. Creating the
roles alone does not grant a pod credentials; the Pod Identity agent and
association are also required in the deployment task.

Validate without credentials or cloud changes, from the repository root:

```sh
uvx cfn-lint deploy/aws/hub-role.yaml deploy/aws/readonly-role.yaml
cd backend
uv run pytest tests/test_aws_templates.py
```
