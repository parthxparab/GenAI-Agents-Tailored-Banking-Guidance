// Helpful outputs to interact with the cluster without keeping extra tooling running.
output "cluster_name" {
  description = "EKS cluster name for kubectl contexts."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "Public API server endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_certificate_authority" {
  description = "Base64 encoded cluster CA; required for manual kubeconfig generation."
  value       = aws_eks_cluster.this.certificate_authority[0].data
  sensitive   = true
}

output "kubeconfig_command" {
  description = "Run after terraform apply to create/update a kubeconfig entry."
  value       = "aws eks --region ${var.region} update-kubeconfig --name ${aws_eks_cluster.this.name}"
}

output "helm_bucket_name" {
  description = "S3 bucket ready to host packaged Helm charts."
  value       = coalesce(try(aws_s3_bucket.helm[0].bucket, null), var.helm_bucket_name != "" ? var.helm_bucket_name : null)
}

