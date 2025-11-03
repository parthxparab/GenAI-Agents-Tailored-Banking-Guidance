// Centralize knobs with safe defaults that keep the cluster inexpensive until explicitly scaled.
variable "region" {
  description = "AWS region for all resources. Default stays in us-east-1 for cheapest multi-AZ pricing."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name used for tagging and kubeconfig."
  type        = string
  default     = "genai-devops-eks"
}

variable "kubernetes_version" {
  description = "Kubernetes control plane version; update intentionally to avoid surprise upgrades."
  type        = string
  default     = "1.34"
}

variable "create_vpc" {
  description = "Set to false to reuse an existing VPC and subnets instead of creating new networking."
  type        = bool
  default     = true
}

variable "vpc_cidr" {
  description = "CIDR block for the minimal VPC; sized just large enough for dev workloads."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Two public subnets across AZs to avoid NAT costs while keeping multi-AZ control plane."
  type        = list(string)
  default     = ["10.20.0.0/20", "10.20.16.0/20"]

  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Exactly two public subnet CIDR blocks are required."
  }
}

variable "private_subnet_cidrs" {
  description = "Two private subnets for Fargate workloads so pods launch without public IPs."
  type        = list(string)
  default     = ["10.20.32.0/20", "10.20.48.0/20"]

  validation {
    condition     = length(var.private_subnet_cidrs) == 2
    error_message = "Exactly two private subnet CIDR blocks are required."
  }
}

variable "existing_vpc_id" {
  description = "If create_vpc is false, supply an existing VPC ID to avoid provisioning new networking."
  type        = string
  default     = null

  validation {
    condition     = var.create_vpc || var.existing_vpc_id != null
    error_message = "existing_vpc_id must be provided when create_vpc is false."
  }
}

variable "existing_public_subnet_ids" {
  description = "If create_vpc is false, supply two public subnet IDs that map to separate AZs."
  type        = list(string)
  default     = []

  validation {
    condition     = var.create_vpc || length(var.existing_public_subnet_ids) == 2
    error_message = "Provide exactly two public subnets when reusing networking."
  }
}

variable "existing_private_subnet_ids" {
  description = "If create_vpc is false, supply two private subnets for Fargate workloads."
  type        = list(string)
  default     = []

  validation {
    condition     = var.create_vpc || length(var.existing_private_subnet_ids) == 2
    error_message = "Provide exactly two private subnets when reusing networking."
  }
}

variable "enable_fargate" {
  description = "Enable Fargate so pods run serverless with pay-per-pod pricing and no idle nodes."
  type        = bool
  default     = true
}

variable "fargate_namespaces" {
  description = "Namespaces scheduled onto Fargate; default covers control plane critical pods."
  type        = list(string)
  default     = ["default", "kube-system"]
}

variable "enable_spot_node_group" {
  description = "Optionally add a managed node group running on SPOT to burst cheaply."
  type        = bool
  default     = false
}

variable "spot_instance_types" {
  description = "Preferred instance types in priority order. Values containing 'g' are treated as Graviton; others as x86."
  type        = list(string)
  default     = ["t4g.small", "t3.small"]
}

variable "node_min_size" {
  description = "Minimum node count; keep at 0 so nothing runs (and costs nothing) at idle."
  type        = number
  default     = 0
}

variable "node_desired_size" {
  description = "Desired nodes; default 0 means SPOT nodes only appear when workloads need them."
  type        = number
  default     = 0
}

variable "node_max_size" {
  description = "Cap the autoscaler at 1 node to avoid surprise scale-ups in personal accounts."
  type        = number
  default     = 1
}

variable "node_architecture" {
  description = "Preferred CPU architecture for SPOT nodes; arm64 is cheapest but requires matching container images."
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["arm64", "x86"], var.node_architecture)
    error_message = "node_architecture must be either arm64 or x86."
  }
}

variable "ssh_key_name" {
  description = "Existing EC2 key pair to allow SSH into managed nodes; leave null to disable remote access."
  type        = string
  default     = null
}

variable "cluster_log_types" {
  description = "Opt-in control plane logs; left empty to avoid CloudWatch ingestion charges."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Optional tags applied to all resources for tracking."
  type        = map(string)
  default     = {}
}

variable "redis_image_repository" {
  description = "Redis image repository override if you prefer a private build."
  type        = string
  default     = ""
}

variable "redis_image_tag" {
  description = "Redis image tag to deploy."
  type        = string
  default     = ""
}

variable "create_helm_bucket" {
  description = "Set to false to skip creating the S3 bucket used for storing Helm charts."
  type        = bool
  default     = true
}

variable "helm_bucket_name" {
  description = "Optional explicit name for the Helm chart S3 bucket. Leave blank to auto-generate."
  type        = string
  default     = "helm_chart"
}

variable "helm_bucket_force_destroy" {
  description = "Allow Terraform to delete the Helm bucket even if it still contains objects."
  type        = bool
  default     = false
}

variable "helm_bucket_enable_versioning" {
  description = "Enable object versioning on the Helm chart bucket to keep historical chart releases."
  type        = bool
  default     = true
}

variable "helm_bucket_add_random_suffix" {
  description = "Append a random suffix to the Helm bucket name for global uniqueness."
  type        = bool
  default     = true
}

variable "enable_remote_state" {
  description = "Set to true to migrate from local state to S3 + DynamoDB for collaboration."
  type        = bool
  default     = false
}

variable "remote_state_bucket" {
  description = "Remote state S3 bucket name when enable_remote_state is true."
  type        = string
  default     = ""
}

variable "remote_state_key" {
  description = "State file key path inside the bucket."
  type        = string
  default     = "terraform.tfstate"
}

variable "remote_state_dynamodb_table" {
  description = "Optional DynamoDB table for state locking."
  type        = string
  default     = ""
}
