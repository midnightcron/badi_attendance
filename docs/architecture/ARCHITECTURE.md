# Architecture Overview

## System Design

The Badi Oerlikon Occupancy Monitor is a serverless data-collection pipeline built on Azure Functions. It continuously ingests real-time occupancy data from a public WebSocket API and persists it as CSV files in Azure Blob Storage.

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    Azure Resource Group                          │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         Function App (Flex Consumption, FC1)              │   │
│  │         Python 3.11, always_ready instances                │   │
│  │                                                            │   │
│  │  Timer Triggers (leap-frog):                               │   │
│  │    websocket_listener_even  :00,:10,:20,:30,:40,:50        │   │
│  │    websocket_listener_odd   :05,:15,:25,:35,:45,:55        │   │
│  │                                                            │   │
│  │  HTTP Triggers:                                            │   │
│  │    GET /api/health_check    Runtime health                 │   │
│  │    GET /api/occupancy       Query historical data          │   │
│  │    GET /api/dashboard       Self-contained HTML dashboard  │   │
│  └────────────────────┬─────────────────────────────────────┘   │
│                       │                                          │
│          ┌────────────▼────────────┐                             │
│          │   Storage Account       │                             │
│          │   (Standard LRS)        │                             │
│          │                         │                             │
│          │  occupancy-data/        │                             │
│          │    YYYY-MM-DD/          │                             │
│          │      occupancy_HH_MM.csv│                             │
│          └─────────────────────────┘                             │
│                                                                  │
│  ┌─────────────────────────┐                                    │
│  │  Application Insights   │  Traces, exceptions, live metrics  │
│  └─────────────────────────┘                                    │
└─────────────────────────────────────────────────────────────────┘
         ▲
         │ WebSocket (wss://)
         │
┌────────┴────────────────────────────┐
│  CrowdMonitor Public API            │
│  wss://badi-public.crowdmonitor.ch  │
│  :9591/api                          │
│  Updates every ~3-4 seconds         │
│  ~32 Swiss swimming pool locations  │
└─────────────────────────────────────┘
```

## Leap-Frog Pattern

### Problem
A single timer-triggered function collecting for 5 minutes (300 s) blocks the next scheduled invocation. Azure Functions' singleton lock prevents overlapping executions of the same function.

### Solution
Two independent timer functions with staggered 10-minute schedules:

```
Time:   :00   :05   :10   :15   :20   :25   :30   :35
EVEN:   |=298s=|     |=298s=|     |=298s=|     |=298s=|
ODD:          |=298s=|     |=298s=|     |=298s=|
```

- **Even** fires at minutes 0, 10, 20, 30, 40, 50
- **Odd** fires at minutes 5, 15, 25, 35, 45, 55
- Each collects for 298 seconds (2 s under 5 min to avoid boundary overlap)
- Together they produce a CSV file every 5 minutes with no gaps

### useMonitor: false
Both triggers set `useMonitor: false` in `function.json`. Without this, Azure's timer monitor tracks missed invocations and fires catch-up executions. When a function runs long (298 s), the catch-up mechanism holds the singleton lock and cascades into blocking subsequent invocations.

### always_ready Instances
The Terraform config provisions `always_ready` instances for both timer functions (`always_ready { name = "function:websocket_listener_even", instance_count = 1 }`). Without this, Flex Consumption may not wake up cold instances fast enough for timer triggers.

## Data Flow

```
1. Timer fires (e.g., :00)
2. websocket_listener_even main() → run_collection("even", mytimer)
3. Connect to wss://badi-public.crowdmonitor.ch:9591/api
4. Send "all" command
5. Receive JSON array every ~3-4 seconds
6. Extract SSD-7 currentfill → {timestamp, occupancy}
7. Collect for 298 seconds (~75 readings)
8. Compute stats: min, max, avg, median
9. Write CSV to blob: occupancy-data/YYYY-MM-DD/occupancy_HH_MM.csv
```

## Code Structure

```
src/functions/
├── utils/                          # Shared modules
│   ├── websocket_collector.py      # run_collection() → _async_collect() → _write_to_blob()
│   ├── websocket_handler.py        # WebSocketListener.collect_updates()
│   └── logger.py                   # Logging configuration
│
├── websocket_listener_even/        # 13-line wrapper → run_collection("even")
│   ├── __init__.py
│   └── function.json               # cron: 0 0,10,20,30,40,50 * * * *
│
├── websocket_listener_odd/         # 13-line wrapper → run_collection("odd")
│   ├── __init__.py
│   └── function.json               # cron: 0 5,15,25,35,45,55 * * * *
│
├── get_occupancy/                  # HTTP API for querying stored data
├── serve_dashboard/                # Serves dashboard.html
├── health_check/                   # Runtime health endpoint
├── host.json                       # functionTimeout: 10 min
└── requirements.txt                # Python dependencies
```

## Infrastructure as Code

Terraform (azurerm ~4.0) in `azure/`:

| Resource | Type | Notes |
|----------|------|-------|
| Resource Group | `azurerm_resource_group` | `badi-oerlikon-dev-rg` |
| Data Storage | `azurerm_storage_account` | Standard LRS, occupancy-data container |
| Function Storage | `azurerm_storage_account` | Separate account for function runtime |
| Service Plan | `azurerm_service_plan` | FC1 (Flex Consumption), Linux |
| Function App | `azurerm_function_app_flex_consumption` | Python 3.11, always_ready |
| App Insights | `azurerm_application_insights` | 30-day retention |

## CI/CD

GitHub Actions workflow (`.github/workflows/main_badi-oerlikon-func-01.yml`):

1. **Build:** Checkout → Python 3.11 → pip install to `.python_packages` → verify critical imports → zip
2. **Deploy:** Download artifact → Azure login (OIDC) → deploy via `Azure/functions-action`

## WebSocket API Protocol

- **Endpoint:** `wss://badi-public.crowdmonitor.ch:9591/api`
- **Handshake:** Standard WebSocket upgrade
- **Command:** Send `"all"` after connect
- **Response:** JSON array of ~32 location objects, broadcast every 3-4 seconds
- **Target field:** `currentfill` (string, needs `int(float(...))` conversion)
- **Target UID:** `SSD-7` (Hallenbad Oerlikon)
