// Configure AWS provider with regional override and default tags so every resource stays traceable.
provider "aws" {
  region = var.region

  default_tags {
    tags = merge(
      {
        ManagedBy = "terraform"
        Project   = var.cluster_name
      },
      var.tags
    )
  }
}

# Alias provider pinned to us-east-1 for resources that must live there (e.g., S3 bucket for Helm charts)
provider "aws" {
  alias  = "use1"
  region = "us-east-1"
}

// Local state keeps things simple (and free) for solo use. Uncomment the block below and set enable_remote_state=true
// along with the remote_state_* variables if you later promote to a shared S3 backend.
/*
terraform {
  backend "s3" {
    bucket         = var.remote_state_bucket
    key            = var.remote_state_key
    region         = var.region
    dynamodb_table = var.remote_state_dynamodb_table
    encrypt        = true
  }
}
*/
