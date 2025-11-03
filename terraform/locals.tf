// Shared service metadata so the same list drives ECR repos and Helm release values.
locals {
  service_names = [
    "gateway",
    "orchestrator",
    "conversation",
    "kyc",
    "advisor",
    "audit",
  ]

  service_default_replicas = {
    gateway      = 1
    orchestrator = 1
    conversation = 1
    kyc          = 1
    advisor      = 1
    audit        = 1
  }
}

