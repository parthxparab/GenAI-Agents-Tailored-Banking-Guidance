// Create an ECR repository per microservice so images can be published consistently.
resource "aws_ecr_repository" "services" {
  for_each = toset(local.service_names)

  name                 = "genai/${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(var.tags, { Component = each.key })
}

output "service_image_base_urls" {
  description = "Base ECR URLs for each microservice repository."
  value = {
    for svc, repo in aws_ecr_repository.services :
    svc => repo.repository_url
  }
}

