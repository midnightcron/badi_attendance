# Quick Start Guide

Get the Badi Oerlikon Occupancy Monitor running locally or deployed to Azure.

## Prerequisites

- Docker & Docker Compose (for local development)
- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5 (for Azure deployment)
- Azure CLI (`az login`) with an active subscription

## Local Development

### 1. Start Services

```bash
docker-compose -f docker-compose.functions.yml up
```

This starts:

- **Azurite** — local Azure Storage emulator on ports 10000–10002
- **Azure Functions runtime** — Python 3.11, API endpoints on port 7071

### 2. Verify

```bash
# Health check
curl http://localhost:7071/api/health_check

# Dashboard
open http://localhost:7071/api/dashboard
```

Check Docker logs for activity:

```bash
docker logs -f badi_oerlikon_attendence-api-1
```

### 3. Stop

```bash
docker-compose -f docker-compose.functions.yml down
```

## Azure Deployment

There are two independent Terraform roots and two deployment methods.

### 1. Provision ACI Collector Infrastructure

```bash
cd azure/collector-aci
cp terraform.tfvars.example terraform.tfvars   # set subscription_id
terraform init
terraform plan
terraform apply
```

This creates in `badi-oerlikon-dev-aci-rg`:

- Storage account (`badiacidevyb1a`) with `occupancy` and `occupancypatterns` tables, `occupancy-parquet` container
- Azure Container Registry (ACR) for Docker images
- Log Analytics workspace
- Azure Container Instance (ACI) — initially using a placeholder image

### 2. Build and Deploy the ACI Collector

```bash
./scripts/deploy-collector-aci.sh
```

This script:

1. Runs `terraform apply` (idempotent)
2. Builds the Docker image from `src/collector-aci/`
3. Pushes to ACR
4. Deletes and recreates the ACI container (to pull the new image)

For image-only redeployment (skip Terraform):

```bash
./scripts/deploy-collector-aci.sh --image
```

### 3. Provision API Infrastructure

```bash
cd azure
cp terraform.tfvars.example terraform.tfvars   # set subscription_id
terraform init
terraform plan
terraform apply
```

This creates in `badi-oerlikon-dev-rg`:

- Function App (`badi-oerlikon-dev-api`) on Flex Consumption (FC1), Python 3.11
- Shared service plan, function runtime storage, Application Insights

### 4. Deploy API Code

Push to `main` — GitHub Actions deploys automatically when `src/api/**` changes:

```bash
git push origin main
```

Or deploy manually:

```bash
cd src/api
zip -r ../../api.zip . -x '__pycache__/*' '*.pyc'
az functionapp deployment source config-zip \
  --resource-group badi-oerlikon-dev-rg \
  --name badi-oerlikon-dev-api \
  --src ../../api.zip
```

### 5. Verify Deployment

```bash
# Health check
curl https://badi-oerlikon-dev-api.azurewebsites.net/api/health_check

# Dashboard (Oerlikon)
open https://badi-oerlikon-dev-api.azurewebsites.net/api/dashboard

# Dashboard (City)
open "https://badi-oerlikon-dev-api.azurewebsites.net/api/dashboard?location=city"

# Query last 7 days at 15-min resolution
curl "https://badi-oerlikon-dev-api.azurewebsites.net/api/occupancy?days=7&resolution=15min"
```

### 6. Monitor

- **Application Insights** — traces, exceptions, live metrics (API app)
- **Table Storage** — check `occupancy` table for new rows every ~4 seconds
- **ACI logs:**

```bash
az container logs \
  --resource-group badi-oerlikon-dev-aci-rg \
  --name badi-oerlikon-dev-collector \
  --follow
```

- **Function App logs:**

```bash
az functionapp log tail -g badi-oerlikon-dev-rg -n badi-oerlikon-dev-api
```

## Redeploying the ACI Collector

`az container restart` does **not** pull a new image. Always delete and recreate:

```bash
./scripts/deploy-collector-aci.sh --image
```

Or manually:

```bash
az container delete \
  --resource-group badi-oerlikon-dev-aci-rg \
  --name badi-oerlikon-dev-collector --yes
cd azure/collector-aci && terraform apply -auto-approve
```

## Project Layout

| Path                               | Purpose                                      |
| ---------------------------------- | -------------------------------------------- |
| `src/collector-aci/`               | ACI persistent collector (WebSocket → Table) |
| `src/api/`                         | HTTP endpoints: dashboard, occupancy, health |
| `azure/`                           | Terraform: API Function App infra            |
| `azure/collector-aci/`             | Terraform: ACI, storage, ACR infra           |
| `.github/workflows/`               | CI/CD pipeline (API only, path-filtered)     |
| `scripts/deploy-collector-aci.sh`  | Full ACI redeploy script                     |
| `docker-compose.functions.yml`     | Local development environment                |
| `docs/`                            | Extended documentation                       |

## Troubleshooting

### No data appearing in Table Storage

Check ACI collector is running:

```bash
az container show \
  --resource-group badi-oerlikon-dev-aci-rg \
  --name badi-oerlikon-dev-collector \
  --query "instanceView.state"
```

Check logs for WebSocket errors:

```bash
az container logs \
  --resource-group badi-oerlikon-dev-aci-rg \
  --name badi-oerlikon-dev-collector
```

### WebSocket connection fails

Test connectivity directly:

```bash
python tests/test_websocket_connectivity.py
```

### API cold start slow

The API Function App scales to zero. First request after idle may take 10–20 seconds.
Always-ready instances can be enabled in `azure/main.tf` if needed.

### Functions not triggering locally

Check that the Azurite container is running and accessible. The Functions runtime needs storage for timer trigger state.
