# genai-stack Helm Chart

This chart packages the Redis cache, API gateway, and agent workloads that were previously run via `docker-compose.yml`. Use it to deploy the platform into Amazon EKS (or any Kubernetes cluster). It exposes a single configurable chart with per-service image tags, replica counts, and optional Services.

## Prerequisites

- Docker images for each service pushed to a registry EKS can reach (e.g., Amazon ECR).
- Helm 3.9+.
- Kubernetes 1.24+ (aligned with the Terraform EKS cluster defaults).
- (Optional) AWS Load Balancer Controller if you keep the gateway Service as `LoadBalancer`.

## Images

By default the chart references placeholder repositories (`REPLACE_WITH_ECR/...`). Update the `values.yaml` (or provide your own override file) with the correct image repositories and tags for each service.

```yaml
components:
  gateway:
    image:
      repository: 123456789012.dkr.ecr.us-east-1.amazonaws.com/gateway
      tag: v1.0.0
  orchestrator:
    image:
      repository: 123456789012.dkr.ecr.us-east-1.amazonaws.com/orchestrator
      tag: v1.0.0
  # ...repeat for other services
```

## Installing

Create a namespace if needed:

```bash
kubectl create namespace genai || true
```

Install the chart using your overrides:

```bash
helm install genai helm/genai-stack \
  --namespace genai \
  --values my-values.yaml
```

Where `my-values.yaml` captures image repositories, replica counts, environment variables, and any Service tweaks.

## Values Overview

- `redis.*`: Configure the bundled Redis Deployment and Service. Persistence is disabled by default to avoid extra storage costs.
- `components.*`: One entry per microservice. Each block controls replicas, container port, optional Service exposure, and resource requests/limits.
- `components.gateway.service.type`: Defaults to `LoadBalancer` so the API is reachable outside the cluster. Switch to `ClusterIP` if you’ll front it with an Ingress.
- `components.<name>.env`: Provide an array of `name`/`value` objects for environment variables.
- `nodeSelector`, `tolerations`, `affinity`: Apply cluster-level scheduling constraints across all pods.

## Uninstalling

```bash
helm uninstall genai --namespace genai
```

Redis data is ephemeral by default. If you enable persistence, make sure to delete the PVCs after uninstalling to avoid stray storage charges.

## Next Steps

- Add Horizontal Pod Autoscalers (HPAs) if you need automatic scaling for any microservice.
- Layer an Ingress resource (or AWS ALB ingress) in front of the gateway for TLS termination and routing.
- Wire Prometheus/Grafana using the chart’s pod labels (`app.kubernetes.io/component`) to scrape component-level metrics once the applications expose them.
