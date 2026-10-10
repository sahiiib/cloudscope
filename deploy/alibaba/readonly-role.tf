terraform {
  required_version = ">= 1.7.0, < 2.0.0"
  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = ">= 1.252.0, < 2.0.0"
    }
  }
}

variable "central_account_id" {
  description = "Alibaba Cloud account ID owning the cloudscope-collector RAM user."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{16}$", var.central_account_id))
    error_message = "central_account_id must be a 16-digit Alibaba Cloud account ID."
  }
}

resource "alicloud_ram_role" "readonly" {
  role_name   = "cloudscope-readonly"
  description = "Read-only ECS and VPC inventory for Cloudscope."
  force       = false
  assume_role_policy_document = jsonencode({
    Version = "1"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        RAM = ["acs:ram::${var.central_account_id}:root"]
      }
    }]
  })
}

resource "alicloud_ram_role_policy_attachment" "readonly" {
  for_each    = toset(["AliyunECSReadOnlyAccess", "AliyunVPCReadOnlyAccess"])
  policy_name = each.value
  policy_type = "System"
  role_name   = alicloud_ram_role.readonly.role_name
}

output "role_arn" {
  description = "Use this ARN as role_arn in the target account's collector configuration."
  value       = alicloud_ram_role.readonly.arn
}
