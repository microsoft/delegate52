# <img src="../assets/domain_icons/infra.svg" width="28" height="28" style="vertical-align: middle;"> Infra

**Category:** Code &amp; Configuration
**File format:** `.tf`
**Summary:** Terraform HCL infrastructure-as-code files with AWS resources (VPC, subnets, security groups, ASG, ALB, IAM, CloudWatch)
**Work environments released:** 6 / 6

Terraform infrastructure-as-code files use [HashiCorp Configuration Language (HCL)](https://developer.hashicorp.com/terraform/language) to define cloud infrastructure declaratively. Each file contains resource blocks, data sources, variables, outputs, and provider configuration that describe an AWS deployment stack. This domain tests an LLM's ability to manipulate structured infrastructure definitions — splitting monolithic configs into layers, converting between formats, refactoring iteration patterns, and annotating resources with metadata like costs and dependencies.

**Domain implementation:** [`domain_infra.py`](../domains/domain_infra.py)

---

## Evaluation

The infra domain evaluator parses HCL files using `python-hcl2` and scores reconstruction quality across five dimensions:

- **Block coverage** — Are all original blocks present? (Jaccard on block fingerprints keyed by `(block_type, type_label, name_label)`)
- **Body accuracy** — Are attribute values preserved correctly? (Recursive dict/list comparison with string SequenceMatcher and numeric ratio similarity)
- **Resource type distribution** — Is the mix of resource types correct? (Jaccard + count similarity on block type categories)
- **Reference integrity** — Are cross-resource references preserved? (Jaccard on extracted references like `aws_vpc.main.id`, `local.name`, `var.environment`)
- **Comment preservation** — Are inline comments intact? (Jaccard on extracted comment sets from `#`, `//`, and `/* */` comments)

**Score formula:** `coverage² × body_accuracy × √(mean(type_distribution, reference_integrity, comment_preservation))`

---

## Example Work Environment: `infra1`

**Document:** AWS API Auto-Scaling Stack
**Source:** [moreandres/api](https://github.com/moreandres/api/blob/master/classic.tf) (MIT License)
**Size:** 330 lines · 2,042 tokens

### Seed Document Excerpt (`main.tf`)

```hcl
# Copyright (c) 2021 Andres More

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 3.0"
    }
  }
}

provider "aws" {}

locals {
  name = "api-${random_string.suffix.result}"
}

resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"

  enable_dns_hostnames = true

  tags = {
    Name = local.name
  }
}

resource "aws_eip" "nat" {
  count      = 2
  vpc        = true
  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${local.name}-${count.index}"
  }
}

resource "aws_nat_gateway" "main" {
  count         = 2
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  depends_on    = [aws_internet_gateway.main]
  tags = {
    Name = "${local.name}-${count.index}"
  }
}
```
<sup>Showing 55 of 330 lines. The full config defines 26 resources across 18 types: networking (VPC, subnets, EIPs, NAT gateways, internet gateway, route tables), compute (launch template, autoscaling group), security (security groups, IAM role, instance profile), load balancing (ALB, listener, target group), and monitoring (scaling policies, CloudWatch alarms).</sup>

---

### Edit Tasks (7 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Infrastructure Layer Split** | Split main.tf into separate files by infrastructure layer: networking.tf, compute.tf, security.tf, loadbalancing.tf, and monitoring.tf. Keep terraform/provider config, locals, and the random_string resource in main.tf. Add a short header comment to each file noting what layer it covers. Create a manifest.json that maps every resource block to its layer and line number. | Consolidate all the layer .tf files into a single main.tf, ordering blocks by their original_line from manifest.json. Drop the per-file layer header comments but keep the copyright comment. Delete manifest.json. | split & merge, classification, format knowledge, sorting |
| 2 | **JSON Format Conversion** | Convert main.tf to a structured JSON representation as infra.json and delete main.tf. Structure: `{"meta": {...}, "blocks": [...]}` where each block has block_type, resource_type, name, line number, and body with all attributes as key-value pairs. Nested HCL blocks become nested objects. Function calls like `jsonencode()` become `{"_fn": "jsonencode", "_arg": {...}}`. | Convert infra.json to standard HCL as main.tf. Reconstruct blocks from the blocks array ordered by the line field. Restore `_fn`/`_arg` objects as HCL function calls. Preserve the copyright comment. Delete infra.json. | format knowledge |
| 3 | **Environment Parameterization** | Refactor main.tf for multi-environment deployment. Extract all hardcoded config values into a locals block as an env_config map keyed by tier (dev, staging, prod). Add a variable "environment" with validation, and a `cfg = local.env_config[var.environment]` shorthand local. Prod tier values match current hardcoded values. Dev: t4g.micro, max ASG 2, VPC CIDR 10.20.0.0/16. Staging: t4g.small, max 4, CIDR 10.10.0.0/16. | Flatten the environment parameterization — inline all prod tier values from env_config directly into resource blocks, remove the environment variable, and collapse locals to just the name local. | numerical reasoning, string manipulation |
| 4 | **Security Hardening** | Harden the security groups — add a description field to every ingress and egress rule. Split the ASG blanket egress into three explicit rules: tcp/443 for AWS API endpoints, tcp/80 for package mirrors, and all traffic to VPC CIDR for internal comms. Add `# Security:` comments before each SG block. Move each SG before its first consumer. Create security_notes.md with a table of all open ports. | Consolidate the three ASG egress rules into a single allow-all outbound rule. Remove description fields and `# Security:` comment lines. Move both security groups together after the route table associations. Delete security_notes.md. | domain knowledge, sorting, context expansion |
| 5 | **Cost Annotation** | Add estimated monthly cost comments above every chargeable AWS resource, formatted as `# Cost: ~$X.XX/mo`. Reorder resource blocks by cost tier — free first, then low-cost, then high-cost. Keep terraform/provider/locals/data blocks at top. Create cost_summary.csv with resource address, type, unit cost, quantity, and estimated monthly total. | Remove all `# Cost:` comment lines. Reorganize resources into infrastructure dependency order: networking, then data/outputs, IAM, compute, security groups, load balancing, then scaling/alarms. Delete cost_summary.csv. | numerical reasoning, context expansion, sorting |
| 6 | **Dependency Graph Annotation** | Annotate resource dependencies and reorder topologically. Above each resource/data block add a comment like `# [pos:N] depends: <resource addresses>`. N is the block's current position (1-indexed). Generate a deps.dot in Graphviz DOT format with resource addresses as nodes. | Sort all blocks by the pos:N value in their `# [pos:N] depends:` comment, then strip those comments. Delete deps.dot. | context expansion, sorting |
| 7 | **for_each Refactoring** | Refactor count-based resources to for_each for better state addressing. Convert every resource with `count = 2` to `for_each = toset(local.az_keys)`. Add locals `az_keys` and `az_map`. Replace `count.index` with `each.key` in tags and `local.az_map[each.key]` for numeric indices. Update all external references from `[0]`/`[1]` to `["a"]`/`["b"]`. | Replace `for_each = toset(local.az_keys)` with `count = 2`. Replace `each.key` with `count.index` and `local.az_map[each.key]` with `count.index`. Change references from `["a"]`/`["b"]` to `[0]`/`[1]`. Remove `az_keys` and `az_map` from locals. | string manipulation |
