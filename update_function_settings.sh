#!/bin/bash
# Simple script to fix Azure Function App runtime

RG="badi-oerlikon-dev-rg"
FUNC_NAME="badi-oerlikon-dev-func"

APP_INSIGHTS_KEY="c3d9b157-7cb3-4ad1-bbac-5b8a1691b9e8"
STORAGE_KEY=$(az storage account keys list -g "$RG" -n badisa3t67 --query '[0].value' -o tsv 2>/dev/null)
STORAGE_CONN=$(az storage account show-connection-string -g "$RG" -n badisa3t67 -o tsv 2>/dev/null)
FUNC_STORAGE_CONN=$(az storage account show-connection-string -g "$RG" -n badfuncsa3t67 -o tsv 2>/dev/null)

echo "🔧 Updating Function App settings with explicit Python 3.11 runtime..."
echo ""

az functionapp config appsettings set \
  -g "$RG" \
  -n "$FUNC_NAME" \
  --settings \
  WEBSITES_ENABLE_APP_SERVICE_STORAGE=false \
  FUNCTIONS_EXTENSION_VERSION="~4" \
  FUNCTIONS_WORKER_RUNTIME=python \
  FUNCTIONS_WORKER_RUNTIME_VERSION=3.11 \
  APPINSIGHTS_INSTRUMENTATIONKEY="$APP_INSIGHTS_KEY" \
  AZURE_STORAGE_ACCOUNT_NAME=badisa3t67 \
  AZURE_STORAGE_ACCOUNT_KEY="$STORAGE_KEY" \
  AZURE_STORAGE_CONNECTION_STRING="$STORAGE_CONN" \
  BLOB_CONTAINER_NAME=scraped-data \
  WEBSOCKET_URL="wss://badi-public.crowdmonitor.ch:9591/api" \
  TARGET_UID="SSD-7" \
  AzureWebJobsStorage="$FUNC_STORAGE_CONN" \
  AzureWebJobsDashboard="$FUNC_STORAGE_CONN" \
  2>&1 | grep -E "FUNCTIONS_|WEBSOCKET_|TARGET_|Succeeded" | head -10

echo ""
echo "⏳ Waiting for app to restart..."
sleep 15

echo "✅ Restarting function app..."
az functionapp restart -g "$RG" -n "$FUNC_NAME"

sleep 10

echo ""
echo "🧪 Testing health check endpoint..."
RESPONSE=$(curl -s "https://$FUNC_NAME.azurewebsites.net/api/health_check")
echo "Response: $RESPONSE"

if [[ $RESPONSE == *"Function host is not running"* ]]; then
  echo "❌ Runtime still not initialized. The issue may be with the app service plan."
  echo ""
  echo "Checking plan details..."
  az appservice plan show -g "$RG" -n "badi-oerlikon-dev-func-plan"
else
  echo "✅ Function app appears to be responding!"
fi
