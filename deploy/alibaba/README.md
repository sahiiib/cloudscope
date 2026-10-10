# Alibaba inventory role module

This module creates `cloudscope-readonly` in one target account, trusts the
`central_account_id` root principal, and attaches exactly `AliyunECSReadOnlyAccess`
and `AliyunVPCReadOnlyAccess`, as specified in
[cloud-access.md](../../docs/specs/cloud-access.md). RAM roles are account-wide;
use one module instance per account, not per scan region.

The caller supplies the provider authenticated to the **target** account and the
16-digit ID of the **central** account. For example, in a separate rollout root:

```hcl
provider "alicloud" {
  alias  = "target"
  region = "eu-central-1"
  # Credentials come from the provider's environment/credential chain.
}

module "cloudscope_readonly" {
  source             = "./path/to/cloudscope/deploy/alibaba"
  providers          = { alicloud = alicloud.target }
  central_account_id = "1111111111111111" # placeholder
}
```

Use `module.cloudscope_readonly.role_arn` in the target account's `accounts.yaml`
entry. For multiple accounts use separate state/provider aliases and module
instances. Do not commit credential values, state or real account configuration.
If the named role already exists, plan its import rather than creating a duplicate.
The central API-only RAM user, its narrowly scoped `sts:AssumeRole` policy and
90-day key rotation remain rollout responsibilities (T-052); this module creates
no user or access key.

Requires Terraform >= 1.7 for mocked tests and Alibaba provider >= 1.252 for the
current role fields. The checked-in lockfile pins the standalone validation
provider. Provider schemas: [RAM role](https://registry.terraform.io/providers/aliyun/alicloud/latest/docs/resources/ram_role),
[policy attachment](https://registry.terraform.io/providers/aliyun/alicloud/latest/docs/resources/ram_role_policy_attachment).

Validation is credential-free and changes no cloud resources:

```sh
terraform -chdir=deploy/alibaba init -backend=false -input=false
terraform -chdir=deploy/alibaba fmt -check -recursive
terraform -chdir=deploy/alibaba validate
terraform -chdir=deploy/alibaba test
```

The native tests use a mock provider and `command = plan`; they check the central
trust principal, both read-only policies and rejection of a wildcard account ID.
Actual rollout belongs to T-052 and is not performed by validation.
