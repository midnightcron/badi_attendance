#!/bin/bash
set -e

RG="badi-oerlikon-dev-rg"
FUNC_NAME="badi-oerlikon-dev-func"
PLAN_NAME="badi-oerlikon-dev-func-plan"

echo "🔧 Fixing Azure Function App runtime configuration..."
echo ""

# Step 1: Delete the existing app service plan and create a new one with reserved=true
echo "Step 1: Recreating app service plan with reserved=true (Linux)..."
az appservice plan delete -g "$RG" -n "$PLAN_NAME" --yes 2>&1 || echo "Plan doesn't exist, proceeding..."
sleep 5

az appservice plan create \
  -g "$RG" \
  -n "$PLAN_NAME" \
  --sku Dynamic \
  --is-linux \
  2>&1 | grep -E "ID|Succeeded" || echo "Plan created"

sleep 10

# Step 2: Delete and recreate the function app with correct settings
echo ""
echo "Step 2: Recreating function app with Linux runtime..."
az functionapp delete -g "$RG" -n "$FUNC_NAME" --yes 2>&1 || echo "Function app doesn't exist, proceeding..."
sleep 5

az functionapp create \
  --resource-group "$RG" \
  --consumption-plan-location westeurope \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --name "$FUNC_NAME" \
  --storage-account badisa3t67 \
  2>&1 | grep -E "Succeeded|HostNames"

sleep 10

# Step 3: Configure app settings
echo ""
echo "Step 3: Configuring app settings..."
az functionapp config appsettings set \
  -g "$RG" \
  -n "$FUNC_NAME" \
  --settings \
  WEBSITES_ENABLE_APP_SERVICE_STORAGE=false \
  FUNCTIONS_WORKER_RUNTIME=python \
  FUNCTIONS_WORKER_RUNTIME_VERSION=3.11 \
  APPINSIGHTS_INSTRUMENTATIONKEY="$(az resource show -g "$RG" --resource-type "Microsoft.Insights/components" -n "badi-oerlikon-dev-insights" --query 'properties.InstrumentationKey' -o tsv)" \
  AZURE_STORAGE_ACCOUNT_NAME=badisa3t67 \
  AZURE_STORAGE_ACCOUNT_KEY="$(az storage account keys list -g "$RG" -n badisa3t67 --query '[0].value' -o tsv)" \
  AZURE_STORAGE_CONNECTION_STRING="$(az storage account show-connection-string -g "$RG" -n badisa3t67 -o tsv)" \
  BLOB_CONTAINER_NAME=scraped-data \
  WEBSOCKET_URL="wss://badi-public.crowdmonitor.ch:9591/api" \
  TARGET_UID="SSD-7" \
  AzureWebJobsStorage="$(az storage account show-connection-string -g "$RG" -n badfuncsa3t67 -o tsv)" \
  AzureWebJobsDashboard="$(az storage account show-connection-string -g "$RG" -n badfuncsa3t67 -o tsv)" \
  2>&1 | grep -E "Name.*FUNCTIONS\|Succeeded" | head -5

echo ""
echo "✅ Function app runtime configuration complete!"
echo "Function URL: https://$FUNC_NAME.azurewebsites.net"
echo ""
echo "🔄 Testing health check endpoint..."
sleep 10
curl -s "https://$FUNC_NAME.azurewebsites.net/api/health_check" | head -100
