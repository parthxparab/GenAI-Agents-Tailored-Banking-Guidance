// Helm provider configuration and optional S3 bucket for chart storage.
locals {
  helm_bucket_random_suffix = var.helm_bucket_add_random_suffix ? try(random_id.helm_bucket[0].hex, null) : null
  helm_bucket_base_name     = var.helm_bucket_name != "" ? var.helm_bucket_name : format("%s-helm", var.cluster_name)
  helm_bucket_candidate     = local.helm_bucket_random_suffix != null ? format("%s-%s", local.helm_bucket_base_name, local.helm_bucket_random_suffix) : local.helm_bucket_base_name
  helm_bucket_segments      = regexall("[a-z0-9]+", lower(local.helm_bucket_candidate))
  helm_bucket_joined        = join("-", local.helm_bucket_segments)
  helm_bucket_shortened     = substr(local.helm_bucket_joined, 0, min(length(local.helm_bucket_joined), 63))
  helm_bucket_name_final    = length(local.helm_bucket_shortened) >= 3 ? local.helm_bucket_shortened : format("helm-%s", coalesce(local.helm_bucket_random_suffix, "bucket"))
}

resource "random_id" "helm_bucket" {
  count = var.create_helm_bucket && var.helm_bucket_add_random_suffix ? 1 : 0

  byte_length = 4
}

resource "aws_s3_bucket" "helm" {
  provider = aws.use1
  count = var.create_helm_bucket ? 1 : 0

  bucket        = local.helm_bucket_name_final
  force_destroy = var.helm_bucket_force_destroy

  tags = merge(var.tags, { Name = "${var.cluster_name}-helm" })
}

resource "aws_s3_bucket_versioning" "helm" {
  provider = aws.use1
  count = var.create_helm_bucket && var.helm_bucket_enable_versioning ? 1 : 0

  bucket = aws_s3_bucket.helm[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "helm" {
  provider = aws.use1
  count = var.create_helm_bucket ? 1 : 0

  bucket = aws_s3_bucket.helm[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "helm" {
  provider = aws.use1
  count = var.create_helm_bucket ? 1 : 0

  bucket = aws_s3_bucket.helm[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}
