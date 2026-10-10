# Mocked provider: validation and tests require no cloud credentials or API calls.
mock_provider "alicloud" {}

variables {
  central_account_id = "1111111111111111"
}

run "readonly_policy_and_trust" {
  command = plan

  assert {
    condition     = alicloud_ram_role.readonly.role_name == "cloudscope-readonly"
    error_message = "The collector role name must match accounts configuration."
  }

  assert {
    condition = jsondecode(alicloud_ram_role.readonly.assume_role_policy_document) == jsondecode(jsonencode({
      Version = "1"
      Statement = [{
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { RAM = ["acs:ram::1111111111111111:root"] }
      }]
    }))
    error_message = "Only the configured central account may assume the role."
  }

  assert {
    condition = (
      toset(keys(alicloud_ram_role_policy_attachment.readonly)) == toset(["AliyunECSReadOnlyAccess", "AliyunVPCReadOnlyAccess"]) &&
      alltrue([for name, attachment in alicloud_ram_role_policy_attachment.readonly :
        attachment.policy_name == name && attachment.policy_type == "System" && attachment.role_name == "cloudscope-readonly"
      ])
    )
    error_message = "Attach exactly the ECS and VPC system read-only policies."
  }
}

run "reject_non_account_principal" {
  command = plan
  variables {
    central_account_id = "*"
  }
  expect_failures = [var.central_account_id]
}
