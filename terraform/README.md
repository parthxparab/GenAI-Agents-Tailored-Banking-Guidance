# Cost-Aware EKS Terraform Stack

This Terraform configuration stands up a development-grade Amazon EKS cluster that defaults to Fargate so you only pay when pods run. All resources are scoped to the `us-east-1` region and choose the cheapest options that remain practical for personal projects.

## Prerequisites

- Terraform >= 1.5
- AWS CLI with credentials capable of creating EKS, IAM, and VPC resources
- An AWS account in `us-east-1`
- Optional: existing EC2 key pair name if you plan to enable the SPOT node group

## Quick Start

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

Once `apply` completes, run the `kubeconfig_command` output, e.g.:

```bash
aws eks --region us-east-1 update-kubeconfig --name genai-devops-eks
kubectl get nodes
kubectl get pods -A
```

## Configuration

All knobs live in `variables.tf`. Consider overriding the following through `terraform.tfvars` or `-var` flags:

- `cluster_name` – rename the cluster.
- `kubernetes_version` – stay current by bumping intentionally.
- `fargate_namespaces` – add namespaces to schedule on Fargate.
- `enable_spot_node_group` – set to `true` for hybrid Fargate + SPOT.
- `ssh_key_name` – AWS key pair to enable SSH when the node group is active.
- `node_architecture` – defaults to `arm64` for cheaper Graviton pricing; switch to `x86` if your images lack arm builds.
- `private_subnet_cidrs` / `public_subnet_cidrs` – adjust network ranges if they overlap with existing CIDRs.
- `existing_private_subnet_ids` / `existing_public_subnet_ids` – supply these when reusing organization-managed networks.
- `tags` – add account or cost-center tags.
- `service_images` – map each microservice (`gateway`, `orchestrator`, `conversation`, `kyc`, `advisor`, `audit`) to the ECR image (repository:tag) you have pushed.
- `create_helm_bucket` / `helm_bucket_name` – control creation of an S3 bucket to host packaged Helm charts; provide a custom name if you already picked one.
- `helm_bucket_enable_versioning` – keep historical chart versions (enabled by default); `helm_bucket_force_destroy` lets Terraform delete the bucket even with objects inside.
- `helm_bucket_add_random_suffix` – leave true to append a random suffix for global uniqueness (S3 bucket names must be unique across AWS); set false only if you supply a unique name yourself.

This repo includes `terraform.tfvars` that keeps one SPOT node online (`node_min_size = node_desired_size = 1`). Delete or edit that file if you prefer Fargate-only operation.
## Fargate-Only (Default)

By default `enable_fargate = true` and `enable_spot_node_group = false`, which means:

- No worker nodes run idle, so the only continuous charge is the EKS control plane (~$0.10/hour).
- Fargate only incurs cost when pods are scheduled.
- Public subnets remain available for load balancers, while pods stay on private subnets with no NAT Gateway fees.
- Fargate pods launch in those private subnets. If workloads must reach public registries or AWS APIs, add interface VPC endpoints (ECR API, ECR DKR, Logs, STS) or temporarily enable a NAT Gateway before scheduling pods.

To keep workloads compatible with Fargate, run pods in one of the namespaces listed in `fargate_namespaces`. You can migrate an existing deployment by patching its namespace:

```bash
kubectl create namespace apps
kubectl patch deployment my-app -n default -p '{"metadata":{"namespace":"apps"}}'
```

Then add `"apps"` to `fargate_namespaces` and re-apply Terraform.

## Publishing Application Images

Terraform creates an ECR repository for each microservice. Build the Docker images (targeting `linux/amd64` for the default `t3` worker nodes) and push them before running `terraform apply` so the Helm release has something to deploy:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)
AWS_REGION=us-east-1
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

for svc in gateway orchestrator conversation kyc advisor audit; do
  IMAGE="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/genai/$svc:$(date +%Y%m%d%H%M%S)"
  case $svc in
    gateway)       docker build --platform linux/amd64 -t "$IMAGE" gateway ;;
    orchestrator)  docker build --platform linux/amd64 -t "$IMAGE" agents/orchestrator ;;
    conversation)  docker build --platform linux/amd64 -t "$IMAGE" agents/conversation ;;
    kyc)           docker build --platform linux/amd64 -t "$IMAGE" agents/kyc ;;
    advisor)       docker build --platform linux/amd64 -t "$IMAGE" agents/advisor ;;
    audit)         docker build --platform linux/amd64 -t "$IMAGE" agents/audit ;;
  esac
  docker push "$IMAGE"
  echo "$svc=$IMAGE"
done
```

Copy the printed `service=image` pairs into `terraform/service-images.auto.tfvars` (there is an example at `terraform/service-images.example.tfvars`) or supply them via `-var service_images=...` so Terraform can update the Helm release with those tags.

## Optional SPOT Node Group

The bundled `terraform.tfvars` already enables the SPOT node group with a single always-on instance. Adjust those values if you need different scaling. To customize manually, set:

```hcl
enable_spot_node_group = true
ssh_key_name           = "my-ec2-keypair"
node_architecture      = "arm64" # switch to x86 if necessary
```

- Module defaults keep `desired_size`, `min_size`, and `max_size` at 0/0/1, but the provided `terraform.tfvars` pins them to 1/1/1 to maintain a ready node.
- Instance types in `spot_instance_types` are automatically filtered to match the selected `node_architecture`. Provide several options (e.g., `t4g.large`, `m7g.large`, `c7g.large`, `t3.large`, `m6i.large`) so SPOT can find capacity; if the filtered list is empty, Terraform falls back to `t4g.small` for arm64 or `t3.small` for x86.
- AMI type switches to Amazon Linux 2023 images when `kubernetes_version` is 1.30 or newer (covering upcoming 1.34), and stays on Amazon Linux 2 for older clusters.
- Node groups attach to the public subnets so instances obtain public IPs and can reach the EKS API/SSM endpoints without a NAT Gateway. If you require private-only nodes, add either a NAT Gateway or the necessary VPC interface endpoints before switching the subnet list.
- Ensure your container images support arm64. Verify quickly with:

```bash
docker buildx imagetools inspect myrepo/myimage:tag
```

If the architecture list does not include `linux/arm64`, switch `node_architecture` to `x86`.

## Remote State (Optional)

The stack uses local state for simplicity. To switch to S3:

1. Create the bucket and (optionally) DynamoDB table.
2. Populate `remote_state_bucket`, `remote_state_key`, and `remote_state_dynamodb_table`.
3. Set `enable_remote_state = true`.
4. Uncomment the backend block in `provider.tf`, then re-run `terraform init -migrate-state`.

## Ongoing Cost Notes

- **EKS control plane:** ~$72/month if left running. Shut down when idle to avoid charges.
- **Fargate pods:** billed per vCPU/memory-second only while pods run.
- **SPOT node:** with the shipped `terraform.tfvars`, you keep one `t4g.large` (or fallback `t3.large`/`m6i.large`) SPOT instance running continuously; expect ~$12–$18/month depending on spot price and instance choice.
- **Network:** public subnets with Internet Gateway plus private subnets for workloads; no NAT Gateway created by default.
- **VPC interface endpoints (optional):** each endpoint costs < $0.02/hour; only create the ones your workloads require if you stay NAT-free.
- **EBS:** only the 20 GiB node root volume is created when the SPOT node runs; delete PVCs before destroy to avoid orphaned volumes.
- **CloudWatch logs:** disabled by default to avoid ingestion/storage fees.
- **Helm bucket:** a single S3 bucket stores packaged charts; versioning is on by default, so empty it before destroy or set `helm_bucket_force_destroy = true`. Bucket names must be globally unique—by default Terraform appends a random suffix to avoid collisions.
- **Application images:** publishing Docker images to the ECR repositories is your responsibility; Terraform deploys them once you set `service_images` to the matching repository:tag values.

Monitor usage with `aws ce get-cost-and-usage` or the AWS console if you run the cluster for long periods.

## Clean Up

Destroy everything when finished to stop control-plane billing:

```bash
terraform destroy
```

Confirm deletion of:

- EKS cluster and Fargate profile
- IAM roles and instance profiles
- VPC, subnets, and Internet Gateway
- SPOT node group (if enabled) and any associated EBS volumes

## Troubleshooting

- **Pods stuck in ImagePullBackOff:** confirm every entry in `service_images` references a pushed ECR image (`aws ecr describe-images --repository-name genai/<service>`).
- **IAM errors:** rerun `terraform apply`; policies sometimes require propagation time.
- **Cluster not reachable:** ensure your local AWS CLI is pointed at the same `region` value and rerun the kubeconfig command.
- **Pod scheduling on Fargate:** confirm the namespace is listed in `fargate_namespaces`.
- **SPOT node pending:** if `t4g.small` capacity is unavailable, AWS automatically falls back to `t3.small`.
