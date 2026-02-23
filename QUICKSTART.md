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
- **Azurite** — local Azure Blob Storage emulator on ports 10000–10002
- **Azure Functions runtime** — Python 3.11, exposed on port 7071

### 2. Verify

```bash
# Health check
curl http://localhost:7071/api/health_check

# Dashboard
open http://localhost:7071/api/dashboard
```

Timer triggers fire automatically on schedule. Check the Docker logs to see WebSocket collection in action:

```bash
docker logs -f badi_oerlikon_attendence-functions-1
```

### 3. Stop

```bash
docker-compose -f docker-compose.functions.yml down
```

## Azure Deployment

### 1. Provision Infrastructure

```bash
cd azure
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set your subscription_id

terraform init
terraform plan    # Review what will be created
terraform apply   # Deploy resources
```

This creates:
- Resource Group (`badi-oerlikon-dev-rg`)
- Function App on Flex Consumption (FC1) with Python 3.11
- Two Storage Accounts (data + function runtime)
- Application Insights
- Always-ready instances for both timer functions

### 2. Deploy Code

Push to `main` — GitHub Actions builds and deploys automatically:

```bash
git push origin main
```

Or deploy manually:

```bash
cd src/functions
zip -r ../../release.zip . -x '__pycache__/*' '*.pyc' 'deploy/*'
az functionapp deployment source config-zip \
  --resource-group badi-oerlikon-dev-rg \
  --name badi-oerlikon-dev-func \
  --src ../../release.zip
```

### 3. Verify Deployment

```bash
# Health check
curl https://badi-oerlikon-dev-func.azurewebsites.net/api/health_check

# Dashboard
open https://badi-oerlikon-dev-func.azurewebsites.net/api/dashboard

# Query data
curl "https://badi-oerlikon-dev-func.azurewebsites.net/api/occupancy?days=1"
```

### 4. Monitor

- **Application Insights** — traces, exceptions, live metrics
- **Blob Storage** — check `occupancy-data` container for new CSV files every 5 minutes
- **Function App logs** — `az functionapp log tail -g badi-oerlikon-dev-rg -n badi-oerlikon-dev-func`

## Project Layout

| Path | Purpose |
|------|---------|
| `src/functions/` | Azure Functions application |
| `azure/` | Terraform infrastructure code |
| `.github/workflows/` | CI/CD pipeline |
| `docker-compose.functions.yml` | Local development environment |
| `docs/` | Extended documentation |

## Troubleshooting

### Functions not triggering locally
Check that the Azurite container is running and accessible. The Functions runtime needs storage for timer trigger state.

### No data in blob storage
Verify `AZURE_STORAGE_CONNECTION_STRING` is set. Check function logs for `"No storage connection string configured"` warnings.

### WebSocket connection fails
The API at `wss://badi-public.crowdmonitor.ch:9591/api` must be reachable. Test with:
```bash
python scripts/scrape_websocket.py
```
