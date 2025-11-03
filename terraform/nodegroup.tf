// Optional SPOT node group for bursty workloads while keeping idle cost at zero.
// Nodes sit in public subnets so they receive public IPs and can reach the EKS API without a NAT gateway.
locals {
  kube_version_parts   = split(".", var.kubernetes_version)
  kube_major           = length(local.kube_version_parts) > 0 ? tonumber(local.kube_version_parts[0]) : 1
  kube_minor           = length(local.kube_version_parts) > 1 ? tonumber(local.kube_version_parts[1]) : 0
  kube_version_value   = local.kube_major * 100 + local.kube_minor
  use_al2023           = local.kube_version_value >= 130
  node_ami_arm64       = local.use_al2023 ? "AL2023_ARM_64_STANDARD" : "AL2_ARM_64"
  node_ami_x86         = local.use_al2023 ? "AL2023_x86_64_STANDARD" : "AL2_x86_64"
  node_ami_type        = var.node_architecture == "arm64" ? local.node_ami_arm64 : local.node_ami_x86
  arm64_instance_types = [for t in var.spot_instance_types : t if length(regexall("g[\\.-]", t)) > 0]
  x86_instance_types   = [for t in var.spot_instance_types : t if length(regexall("g[\\.-]", t)) == 0]
  // Ensure we always end up with at least one instance type compatible with the selected architecture.
  node_instance_types = var.node_architecture == "arm64" ? coalescelist(local.arm64_instance_types, ["t4g.small"]) : coalescelist(local.x86_instance_types, ["t3.small"])
}

resource "aws_eks_node_group" "spot" {
  count = var.enable_spot_node_group ? 1 : 0

  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.cluster_name}-spot"
  node_role_arn   = aws_iam_role.node_group[0].arn
  subnet_ids      = local.selected_public_subnet_ids

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  capacity_type  = "SPOT"
  ami_type       = local.node_ami_type
  instance_types = local.node_instance_types
  disk_size      = 20 // Smallest supported EBS boot volume reduces unused storage charges.

  dynamic "remote_access" {
    for_each = var.ssh_key_name != null && var.ssh_key_name != "" ? [var.ssh_key_name] : []
    content {
      ec2_ssh_key = remote_access.value
    }
  }

  // Managed launch template keeps updates cheap and automatic without extra Terraform resources.
  update_config {
    max_unavailable = 1
  }

  tags = merge(var.tags, { Name = "${var.cluster_name}-spot" })

  depends_on = [
    aws_iam_role_policy_attachment.node_group_worker,
    aws_iam_role_policy_attachment.node_group_cni,
    aws_iam_role_policy_attachment.node_group_ecr
  ]
}
