// EKS control plane with only essentials enabled so we pay for what we use and nothing more.
resource "aws_security_group" "cluster" {
  name        = "${var.cluster_name}-cluster-sg"
  description = "Control plane communication with worker nodes"
  vpc_id      = local.selected_vpc_id

  // Allow the control plane to reach out to pods/nodes; ingress is handled by managed resources.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.cluster_name}-cluster-sg" })
}

resource "aws_eks_cluster" "this" {
  name                      = var.cluster_name
  role_arn                  = aws_iam_role.eks_cluster.arn
  version                   = var.kubernetes_version
  enabled_cluster_log_types = var.cluster_log_types

  vpc_config {
    subnet_ids              = concat(local.selected_private_subnet_ids, local.selected_public_subnet_ids)
    security_group_ids      = [aws_security_group.cluster.id]
    endpoint_public_access  = true
    endpoint_private_access = false
  }

  // Ensures IAM policies are ready so the control plane can manage networking.
  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_iam_role_policy_attachment.eks_cluster_vpc_resource_controller
  ]
}

// Fargate profile keeps baseline cost minimal; pods only bill for CPU/memory used.
resource "aws_eks_fargate_profile" "this" {
  count = var.enable_fargate ? 1 : 0

  cluster_name           = aws_eks_cluster.this.name
  fargate_profile_name   = "${var.cluster_name}-fargate"
  pod_execution_role_arn = aws_iam_role.fargate_pod_execution.arn
  subnet_ids             = local.selected_private_subnet_ids

  dynamic "selector" {
    for_each = var.fargate_namespaces
    content {
      namespace = selector.value
    }
  }

  depends_on = [
    aws_eks_cluster.this,
    aws_iam_role_policy_attachment.fargate_execution
  ]
}
