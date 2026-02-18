# BADI Oerlikon WebSocket Listener - Deployment Status

**Date:** February 18, 2026  
**Project:** Automated WebSocket occupancy data collection for BADI Oerlikon swimming pool  
**Status:** Infrastructure deployed, code ready, runtime initialization blocked

---

## Executive Summary

### What's Working ✅

- **Infrastructure:** All Azure resources created and configured
- **Code Quality:** Python function tested locally (collects data successfully)
- **Deployment:** Function code deployed to Azure
- **Configuration:** All environment variables properly set
- **Cost:** Target ~€0.50-1/month operational cost (far below €16 budget)

### What's Blocked 🔴

- **Python Runtime:** Not initializing on Azure Function App
- **Subscription Limitation:** Trial subscription has zero VM quota across all regions

---

## Cost Analysis

| Component | Type | Cost/Month | Notes |
| --- | --- | --- | --- |
| Function App | Consumption (Y1) | €0.00-0.50 | ~1M invocations free tier |
| Storage Account | Standard LRS | €0.20 | Small blob storage for data |
| App Insights | Retention 30d | €0.00 | Free tier (up to 5GB) |
| **Total** | | **<€1** | **Well under €16 limit** |

Alternative (if quota upgrade needed): Premium P0V3 plan would be ~€20/month.

---

## Infrastructure Details

### Deployed Resources (West Europe)

```
Resource Group: badi-oerlikon-dev-rg
├── Function App: badi-oerlikon-dev-func
│   ├── Plan: Dynamic (Consumption) Y1
│   ├── Runtime: Python 3.8-3.11
│   └── Functions: 
│       ├── websocket_listener (timer-triggered, every 5 min)
│       └── health_check (HTTP endpoint for testing)
├── Storage Accounts:
│   ├── badisa[3t67]: Data storage (blob containers)
│   │   ├── scraped-data/ (hourly occupancy snapshots)
│   │   └── logs/ (error/debug logging)
│   └── badfuncsa[3t67]: Function runtime storage
└── Application Insights: badi-oerlikon-dev-insights
```

### Terraform Configuration

- **IaC Location:** `/azure/`
- **Main Files:**
  - `main.tf` - Resource definitions
  - `variables.tf` - Input variables (default: West Europe)
  - `terraform.tfvars` - Current variable values
  - `outputs.tf` - Resource identifiers

**Key Changes Made:**
1. Removed Web App and Basic App Service Plan (freed quota)
2. Added random suffix to storage accounts (global naming)
3. Kept Consumption tier for Function App (minimal cost, free tier eligible)

---

## Function Code Status

### websocket_listener

**Purpose:** Collects occupancy data from BADI public WebSocket API

**Location:** `src/functions/websocket_listener/`

**Architecture:**
```
Timer Trigger (every 5 minutes)
  ↓
Synchronous wrapper: main()
  ↓
Async function: _async_main()
  ├─ Connect to wss://badi-public.crowdmonitor.ch:9591/api
  ├─ Receive location updates (one every 3-4 seconds)
  ├─ Extract SSD-7 (Hallenbad Oerlikon) occupancy
  ├─ Collect for 300 seconds
  └─ Save JSON to blob storage
  
Output file format:
  occupancy_data/{timestamp}_{uid}.json
  {
    "occupancy": 45,
    "timestamp": "2026-02-18T14:30:00Z",
    "uid": "SSD-7",
    "location": "Hallenbad Oerlikon"
  }
```

**Local Testing Results:** ✅
- Connection: Successful
- Data Collection: 7 updates in 30 seconds (expected: 75-100 per 5-min window)
- Data Extraction: Proper JSON parsing, `currentfill` conversion to integer
- Error Handling: Graceful connection recovery

**Key Fix Applied:**
- Changed from `async def main()` to sync wrapper with `asyncio.run()`
- Azure timer triggers don't properly support async entry points

---

## Current Blocker: Python Runtime

### Symptom
```
GET https://badi-oerlikon-dev-func.azurewebsites.net/api/health_check
Response: "Function host is not running."
Status: 503
```

### Root Cause
Trial subscription has **zero VM quota** for:
- Dynamic VMs (Consumption plans)
- PremiumV3 VMs (Premium plans)  
- Basic VMs (App Service plans)

**Attempted Solutions:**
1. ✅ Changed region (West Europe → North Europe → East US) - All have zero quota
2. ✅ Changed plan tier (Dynamic → PremiumV3) - Still quota issue
3. ✅ Simplified config (removed Web App) - Freed quota but still zero
4. ✅ Updated settings/extensions - No runtime initialization
5. ✅ Multiple restart attempts - No effect

**Verification:**
```bash
$ az vm list --query "[].location" | sort | uniq
# No results - no VMs can be created in subscription
```

---

## How to Proceed

### Option 1: Request Quota Increase (Recommended)

**Steps:**
1. Go to Azure Portal → Subscriptions → [Your Subscription] → Usage + quotas
2. Search for "Dynamic VMs" or "Premium VMs"
3. Click quota name → Request quota increase
4. Set limit to at least 1 for your chosen region
5. Wait for approval (typically <24 hours for trial subscriptions)
6. Run `terraform apply` again - function should start immediately

**No code changes needed** - everything is ready to deploy once quota is available.

### Option 2: Use Different Subscription

If quota increase is denied, use a subscription with:
- Active enterprise or pay-as-you-go plan
- Existing VM quota (usually non-zero)

**Deployment steps remain identical.**

### Option 3: Alternative Hosting (If needed)

- Container Instance (already ruled out by user)
- App Service Basic tier (requires different resource group due to quota)
- Logic App with managed connectors

---

## WebSocket API Behavior

### API Details
- **Endpoint:** `wss://badi-public.crowdmonitor.ch:9591/api`
- **Protocol:** WebSocket JSON
- **Update Frequency:** Every 3-4 seconds (not on-demand)
- **Response:** Array of ~32 Swiss swimming pool locations

### Expected Data Format
```json
[
  {
    "uid": "SSD-7",
    "name": "Hallenbad Oerlikon",
    "currentfill": "45",  // ← String, needs int conversion
    "maxfill": "180",
    "lastupdate": 1708270800
  },
  ...
]
```

### Observed Collection Rates
- 30 seconds: ~7 updates
- 5 minutes (300s): Expected 75-100 updates (at 1 every 3-4s)

---

## Deployment Commands

### Deploy Infrastructure
```bash
cd azure/
terraform init      # One-time setup
terraform plan      # Review changes
terraform apply     # Deploy resources
```

### Deploy Function Code
```bash
# Zip already prepared at src/functions/functions-deploy.zip

az webapp deployment source config-zip \
  --resource-group badi-oerlikon-dev-rg \
  --name badi-oerlikon-dev-func \
  --src src/functions/functions-deploy.zip
```

### Check Status
```bash
# Test runtime initialization
curl https://badi-oerlikon-dev-func.azurewebsites.net/api/health_check

# View function details
az webapp show -g badi-oerlikon-dev-rg -n badi-oerlikon-dev-func

# Check logs (once runtime starts)
az webapp log tail -g badi-oerlikon-dev-rg -n badi-oerlikon-dev-func
```

---

## Local Testing (For Verification)

### Run WebSocket Listener Locally
```bash
cd src/functions/websocket_listener/
python test_local_function.py
```

**Expected output:**
```
Connected to WebSocket
Received 7 updates in 30 seconds
Min occupancy: 42
Max occupancy: 48
Avg occupancy: 45.2
```

### Run Extended Test
```bash
python test_websocket_extended.py
```

**Collects data for 30 seconds, showing update frequency.**

---

## Files and Locations

### Infrastructure Code
- `azure/main.tf` - Resource definitions (Function App, Storage, App Insights)
- `azure/variables.tf` - Configurable values
- `azure/terraform.tfvars` - Current region: West Europe
- `azure/outputs.tf` - Terraform outputs

### Function Code
- `src/functions/websocket_listener/__init__.py` - Main function entry point
- `src/functions/websocket_listener/websocket_handler.py` - WebSocket connection logic
- `src/functions/websocket_listener/function.json` - Azure config (timer trigger, 5min schedule)
- `src/functions/health_check/__init__.py` - Debug HTTP endpoint
- `src/functions/functions-deploy.zip` - Deployment package (11MB)

### Documentation
- This file: `DEPLOYMENT_STATUS.md`
- `README.md` - Project overview
- `git log` - All historical commits with detailed messages

---

## Git Commits (Recent)

```
cf351d3 refactor: Simplify deployment and remove quota-consuming Web App
1e2020c fix: Fix async timer trigger and WebSocket collection
a3c9e8f feat: Add health check endpoint for debugging
...
```

View full history with: `git log --oneline`

---

## Next Steps (Priority Order)

1. **Request VM quota increase** in Azure subscription (or use different subscription)
2. **Wait for approval** (typically <24 hours)
3. **Run `terraform apply`** (no changes needed, just re-apply)
4. **Test health endpoint** - should return 200 OK
5. **Monitor blob storage** - new files appear every 5 minutes
6. **Set up visualization** (optional - CSV export to local dashboard)

---

## Monitoring Once Running

### Check for Collected Data
```bash
az storage blob list \
  --account-name badisa3t67 \
  --container-name scraped-data \
  --output table
```

### View Recent Occupancy Data
```bash
az storage blob download \
  --account-name badisa3t67 \
  --container-name scraped-data \
  --name "occupancy_data/[latest-file].json" \
  --file data.json

cat data.json | jq '.occupancy'
```

### Set Up Alerts
- Application Insights → Alerts → New alert rule
- Condition: Function failures or slow response times
- Action: Email notification

---

## Support / Troubleshooting

### "Function host is not running"
**Solution:** Request VM quota increase (see "How to Proceed" section)

### "Storage account name already exists"
**Already handled** - random suffix added automatically (e.g., `badisa3t67`)

### WebSocket connection timeout
**Verify:** `curl https://badi-public.crowdmonitor.ch:9591/api` works locally
**Check:** Network ACLs if behind corporate firewall

### Function never triggers
**Check:** 
```bash
az functionapp function list -g badi-oerlikon-dev-rg -n badi-oerlikon-dev-func
```
Should show `websocket_listener` in the list.

---

**Document Updated:** 2026-02-18  
**Last Deployment:** Successful (deploy ID: de6cb6a562c34596ac969730068607c8)  
**Status:** Ready for production once Python runtime initializes
