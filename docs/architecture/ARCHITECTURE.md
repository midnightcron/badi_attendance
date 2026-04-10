# Architecture Overview

## System Design

The Badi Oerlikon Occupancy Monitor is a data-collection pipeline that continuously ingests
real-time occupancy data from a public WebSocket API and persists it in Azure Table Storage.
Two locations are monitored simultaneously: Hallenbad Oerlikon (SSD-7) and Hallenbad City (SSD-4).

### Components

```text
┌─────────────────────────────────────────────────────────────────────┐
│  badi-oerlikon-dev-aci-rg                                           │
│                                                                      │
│  ┌──────────────────────────────┐   ┌────────────────────────────┐  │
│  │  ACI Collector               │   │  Storage Account           │  │
│  │  badi-oerlikon-dev-collector │──▶│  badiacidevyb1a            │  │
│  │  Python 3.11, restart=Always │   │                            │  │
│  │                              │   │  Tables:                   │  │
│  │  • WebSocket listener        │   │    occupancy (raw)         │  │
│  │    - SSD-7 Oerlikon          │   │    occupancypatterns       │  │
│  │    - SSD-4 City              │   │  Containers:               │  │
│  │  • Aggregator (02:00 CET)    │   │    occupancy-parquet       │  │
│  └──────────────────────────────┘   └────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────┐                                    │
│  │  ACR (badiacidevyb1a)        │  Docker image registry            │
│  └──────────────────────────────┘                                    │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  badi-oerlikon-dev-rg                                               │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  API Function App (Flex Consumption, scales to zero)          │   │
│  │  Python 3.11 · badi-oerlikon-dev-api                          │   │
│  │                                                                │   │
│  │  HTTP:  GET /api/health_check                                  │   │
│  │         GET /api/occupancy                                     │   │
│  │         GET /api/dashboard                                     │   │
│  │  Timer: export_parquet (daily 02:00 UTC)                       │   │
│  └───────────────────────────────┬────────────────────────────────┘  │
│                                  │ reads                              │
│                                  ▼                                    │
│             badiacidevyb1a storage account (shared)                  │
│                                                                      │
│  ┌─────────────────────────┐                                        │
│  │  Application Insights   │  Traces, exceptions, live metrics      │
│  └─────────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────────┘
         ▲
         │ WebSocket (wss://)
         │
┌────────┴────────────────────────────┐
│  CrowdMonitor Public API            │
│  wss://badi-public.crowdmonitor.ch  │
│  :9591/api · ~32 Swiss locations    │
└─────────────────────────────────────┘
```

### Why Two Separate Deployments?

Deploying any code change to a Function App causes host restarts. With a single app,
pushing a dashboard tweak would interrupt the collector. By using a separate ACI container
for collection and a Function App for the API, changes are fully independent.

The ACI container also suits the collector better than Functions: it's a persistent
process that holds a single long-lived WebSocket connection rather than running in
discrete invocation windows.

## ACI Collector

### Process Model

`src/collector-aci/main.py` runs two concurrent asyncio tasks:

1. **WebSocket listener** — maintains a continuous connection, writes one row per
   received message (~every 4 seconds)
2. **Aggregator** — sleeps until 02:00 CET each day, then builds daily pattern statistics

Graceful shutdown handles `SIGTERM` (sent by ACI on container stop).

### Data Flow

```text
1. Connect to wss://badi-public.crowdmonitor.ch:9591/api
2. Send "all" command
3. Receive JSON array every ~3-4 seconds (~32 locations)
4. Extract SSD-7 currentfill → occupancy_oerlikon
   Extract SSD-4 currentfill → occupancy_city
5. Write row to Table Storage:
     PartitionKey = YYYY-MM-DD
     RowKey       = HH:MM:SS.ffffff
     occupancy_oerlikon = int
     occupancy_city     = int
```

### Daily Aggregation

At 02:00 CET each day the aggregator reads the previous day's rows from the `occupancy`
table and writes summary statistics to `occupancypatterns`:

```text
PartitionKey = weekday (0=Monday … 6=Sunday)
RowKey       = HH:MM  (15-minute slot)
avg_oerlikon, std_oerlikon
avg_city,     std_city
```

448 rows total (7 weekdays × 64 slots). Each run upserts (merge) so re-runs are safe.

### Deployment

ACI does **not** pull a new image on `az container restart`. Full redeploy required:

```bash
./scripts/deploy-collector-aci.sh        # Terraform + build + push + delete + recreate
./scripts/deploy-collector-aci.sh --image  # Build + push + delete + recreate only
```

## API Function App

### Endpoints

#### GET /api/dashboard

- Query params: `days` (default 30, max 90), `location` (`oerlikon` | `city`)
- Renders a fully self-contained Plotly HTML page (no JS framework, pure Python)
- Four charts: occupancy timeline, best time to visit (15-min bins), weekly heatmap,
  today/tomorrow forecast with ±1σ bands from `occupancypatterns`
- Location-aware opening hours (different schedules for Oerlikon vs City)
- Dark mode (GitHub palette), timezone Europe/Zurich

#### GET /api/occupancy

- Query params: `days` (1–30, default 7), `resolution` (`raw`/`5min`/`15min`/`1hour`/`1day`),
  `date` (YYYY-MM-DD), `location` (`oerlikon` | `city`)
- Queries `occupancy` table by PartitionKey (date), aggregates to requested resolution
- Returns JSON with timestamp + occupancy + min/max bands
- CORS headers: `Access-Control-Allow-Origin: *`

#### GET /api/health_check

- Returns JSON: status, timestamp, configured env vars

#### Timer: export_parquet (daily 02:00 UTC)

- Reads previous day from `occupancy` table
- Feature-engineers columns: hour, minute, day_of_week, is_open_oerlikon, is_open_city
- Writes Parquet (snappy) to `occupancy-parquet/year=YYYY/month=MM/day=DD/occupancy.parquet`

## Storage Schema

### Table: `occupancy`

| Field                | Type   | Description                               |
| -------------------- | ------ | ----------------------------------------- |
| `PartitionKey`       | string | Date (`YYYY-MM-DD`)                       |
| `RowKey`             | string | Time (`HH:MM:SS.ffffff`, UTC)             |
| `occupancy_oerlikon` | int    | Current fill — Hallenbad Oerlikon (SSD-7) |
| `occupancy_city`     | int    | Current fill — Hallenbad City (SSD-4)     |

~12 rows/min, ~17,280 rows/day.

### Table: `occupancypatterns`

| Field                          | Type   | Description                            |
| ------------------------------ | ------ | -------------------------------------- |
| `PartitionKey`                 | string | Weekday (`0`=Monday … `6`=Sunday)      |
| `RowKey`                       | string | Time slot (`HH:MM`, 15-min resolution) |
| `avg_oerlikon`, `std_oerlikon` | float  | Mean ± σ for Oerlikon                  |
| `avg_city`, `std_city`         | float  | Mean ± σ for City                      |

448 rows total. Populated nightly at 02:00 CET by the ACI aggregator.

### Blob Container: `occupancy-parquet`

Path: `year=YYYY/month=MM/day=DD/occupancy.parquet`

Schema: `timestamp (UTC)`, `occupancy_oerlikon (Int32)`, `occupancy_city (Int32)`,
`hour`, `minute`, `day_of_week`, `is_open_oerlikon`, `is_open_city`

## Infrastructure as Code

Two separate Terraform roots to allow independent lifecycle management:

### `azure/collector-aci/`

| Resource          | Type                              | Notes                                 |
| ----------------- | --------------------------------- | ------------------------------------- |
| Resource Group    | `azurerm_resource_group`          | `badi-oerlikon-dev-aci-rg`            |
| Storage Account   | `azurerm_storage_account`         | `badiacidevyb1a`, Standard LRS        |
| Table: occupancy  | `azurerm_storage_table`           | Raw readings                          |
| Table: patterns   | `azurerm_storage_table`           | `occupancypatterns`                   |
| Parquet container | `azurerm_storage_container`       | `occupancy-parquet`                   |
| ACR               | `azurerm_container_registry`      | Basic SKU, admin enabled              |
| Log Analytics     | `azurerm_log_analytics_workspace` | 30-day retention                      |
| ACI               | `azurerm_container_group`         | Linux, `restart=Always`, no public IP |

### `azure/`

| Resource       | Type                                      | Notes                              |
| -------------- | ----------------------------------------- | ---------------------------------- |
| Resource Group | `azurerm_resource_group`                  | `badi-oerlikon-dev-rg`             |
| Func Storage   | `azurerm_storage_account`                 | `badfuncsa3yz1`, runtime only      |
| Service Plan   | `azurerm_service_plan`                    | FC1 (Flex Consumption), Linux      |
| API App        | `azurerm_linux_function_app`              | Python 3.11, scales to zero        |
| App Insights   | `azurerm_application_insights`            | 30-day retention                   |

The API app reads from `badiacidevyb1a` (the ACI storage account) via connection string
passed as an app setting. The two Terraform roots are linked only through this shared
storage account name.

## CI/CD

One path-filtered GitHub Actions workflow:

| Workflow   | File              | Triggers on              |
| ---------- | ----------------- | ------------------------ |
| Deploy API | `deploy-api.yml`  | `src/api/**` on `main`   |

Steps: checkout → Python 3.11 → pip install → verify packages → zip → OIDC login →
deploy via `Azure/functions-action`.

The ACI collector is **not** deployed via CI. Use `scripts/deploy-collector-aci.sh` directly.

## WebSocket API Protocol

- **Endpoint:** `wss://badi-public.crowdmonitor.ch:9591/api`
- **Command:** Send `"all"` after connect
- **Response:** JSON array of ~32 location objects, broadcast every 3–4 seconds
- **Target fields:** `uid` (to identify location), `currentfill` (string → int conversion)
- **Monitored UIDs:** `SSD-7` (Oerlikon), `SSD-4` (City)
