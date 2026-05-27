# Badi Occupancy Monitor

[![API Deploy](https://github.com/midnightcron/badi_attendance/actions/workflows/deploy-api.yml/badge.svg?branch=main)](https://github.com/midnightcron/badi_attendance/actions/workflows/deploy-api.yml)

Real-time occupancy monitoring for Zurich swimming pools using WebSocket data collection on Azure.

## What It Does

- Connects to the CrowdMonitor WebSocket API (`wss://badi-public.crowdmonitor.ch:9591/api`)
- Monitors two locations simultaneously:
  - **SSD-7** — Hallenbad Oerlikon
  - **SSD-4** — Hallenbad City
- Collects ~75 readings per 5-minute window (one every ~4 seconds)
- Saves readings to Azure Table Storage with dual-location columns
- Computes daily per-weekday patterns (avg ± σ per 15-min slot)
- Exports daily Parquet snapshots for ML/analytics use
- Serves a dashboard and REST API for querying historical data

## Architecture

The system uses two separate Azure deployments so that API/dashboard changes never interrupt data collection:

| Component     | Deployment                                               | Role                                           |
| ------------- | -------------------------------------------------------- | ---------------------------------------------- |
| **Collector** | Azure Container Instance (`badi-oerlikon-dev-collector`) | Persistent process — WebSocket → Table Storage |
| **API**       | Azure Function App (`badi-oerlikon-dev-api`)             | HTTP endpoints + daily Parquet export          |

The collector runs as a persistent ACI container with `restart=Always`. It maintains a continuous WebSocket connection and writes raw readings every ~4 seconds. A concurrent background task runs nightly at 02:00 CET to aggregate patterns.

The API Function App scales to zero when idle and reads exclusively from Table Storage (fast, indexed queries — no blob downloads).

**Infrastructure overview:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  badi-oerlikon-dev-aci-rg                                           │
│                                                                      │
│  ┌──────────────────────────────┐   ┌────────────────────────────┐  │
│  │  ACI Collector               │   │  Storage Account           │  │
│  │  badi-oerlikon-dev-collector │──▶│  badiacidevyb1a            │  │
│  │  Python 3.11, restart=Always │   │                            │  │
│  │  • WebSocket listener        │   │  Tables:                   │  │
│  │    - SSD-7 (Oerlikon)        │   │    occupancy               │  │
│  │    - SSD-4 (City)            │   │    occupancypatterns        │  │
│  │  • Daily aggregator (02:00)  │   │  Containers:               │  │
│  └──────────────────────────────┘   │    occupancy-parquet        │  │
│                                      └────────────────────────────┘  │
│  ┌──────────────────────────────┐                                    │
│  │  ACR (badiacidevyb1a)        │  ← Docker images for ACI         │
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
│  │         GET /api/occupancy?days=7&resolution=15min&location=.. │   │
│  │         GET /api/dashboard?days=30&location=oerlikon           │   │
│  │  Timer: export_parquet  (daily 02:00 UTC)                      │   │
│  └────────────────────────────────────────────────────────────────┘  │
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

## Project Structure

```
badi_oerlikon_attendence/
├── src/
│   ├── collector-aci/                  # ACI collector (current)
│   │   ├── main.py                     # Entry point: asyncio loop + graceful shutdown
│   │   ├── websocket_handler.py        # WebSocketClient — dual-location listener
│   │   ├── table_writer.py             # Azure Table Storage writes
│   │   ├── aggregator.py               # Daily pattern aggregation (weekday × 15-min slot)
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── collector/                      # Azure Durable Functions collector (legacy, kept for reference)
│   │
│   └── api/                            # Azure Function App — HTTP + timer
│       ├── serve_dashboard/            # HTTP: GET /api/dashboard (Plotly, pure Python)
│       ├── get_occupancy/              # HTTP: GET /api/occupancy (Table Storage query)
│       ├── health_check/               # HTTP: GET /api/health_check
│       ├── export_parquet/             # Timer: daily 02:00 UTC → Parquet blob
│       ├── utils/
│       │   └── dashboard_builder.py    # Plotly chart generation (4 chart types)
│       ├── host.json
│       └── requirements.txt
│
├── azure/                              # Terraform: API Function App infra
│   ├── main.tf                         # API app, service plan, function storage, App Insights
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars
│
├── azure/collector-aci/                # Terraform: ACI collector infra (separate root)
│   ├── main.tf                         # RG, storage account, tables, ACR, Log Analytics, ACI
│   ├── variables.tf
│   └── outputs.tf
│
├── .github/workflows/
│   └── deploy-api.yml                  # Deploys on src/api/** changes
│
├── scripts/
│   └── deploy-collector-aci.sh         # Full ACI redeploy (Terraform + Docker + push + restart)
│
├── tests/
│   └── test_websocket_connectivity.py
├── docker-compose.functions.yml        # Local dev (Azurite + Functions runtime)
└── docs/
```

## Quick Start

### Local Development (Docker Compose)

```bash
docker-compose -f docker-compose.functions.yml up
```

Starts Azurite (local storage emulator) and the Functions runtime. HTTP endpoints at `http://localhost:7071/api/`.

### Deploy to Azure

```bash
# 1. Provision API infrastructure
cd azure && terraform init && terraform apply

# 2. Provision ACI collector infrastructure
cd azure/collector-aci && terraform init && terraform apply

# 3. Build and deploy the ACI collector
./scripts/deploy-collector-aci.sh

# 4. Push to main — GitHub Actions deploys API automatically
git push origin main
```

See [QUICKSTART.md](QUICKSTART.md) for detailed steps.

## HTTP Endpoints

| Endpoint             | Method | Params                                   | Description                    |
| -------------------- | ------ | ---------------------------------------- | ------------------------------ |
| `/api/health_check`  | GET    | —                                        | Runtime health + config status |
| `/api/occupancy`     | GET    | `days`, `resolution`, `date`, `location` | Query occupancy data as JSON   |
| `/api/dashboard`     | GET    | `days`, `location`                       | Interactive Plotly dashboard   |

**`location`** values: `oerlikon` (default) or `city`

**`resolution`** values: `raw`, `5min`, `15min` (default), `1hour`, `1day`

## Configuration

### ACI Collector

| Variable                          | Description                                              |
| --------------------------------- | -------------------------------------------------------- |
| `AZURE_STORAGE_CONNECTION_STRING` | Table Storage connection string                          |
| `WEBSOCKET_URL`                   | WebSocket endpoint; defaults to CrowdMonitor public API  |

### API Function App

| Variable                          | Description                                      |
| --------------------------------- | ------------------------------------------------ |
| `AZURE_STORAGE_CONNECTION_STRING` | Same storage account as collector                |
| `AZURE_STORAGE_ACCOUNT_NAME`      | Storage account name (for Managed Identity auth) |

## Data Format

### Table Storage: `occupancy`

| Field                | Type   | Description                               |
| -------------------- | ------ | ----------------------------------------- |
| `PartitionKey`       | string | Date (`YYYY-MM-DD`)                       |
| `RowKey`             | string | Time (`HH:MM:SS.ffffff`)                  |
| `occupancy_oerlikon` | int    | Current fill — Hallenbad Oerlikon (SSD-7) |
| `occupancy_city`     | int    | Current fill — Hallenbad City (SSD-4)     |

### Table Storage: `occupancypatterns`

| Field                          | Type   | Description                            |
| ------------------------------ | ------ | -------------------------------------- |
| `PartitionKey`                 | string | Weekday (`0`=Monday … `6`=Sunday)      |
| `RowKey`                       | string | Time slot (`HH:MM`, 15-min resolution) |
| `avg_oerlikon`, `std_oerlikon` | float  | Mean ± σ for Oerlikon                  |
| `avg_city`, `std_city`         | float  | Mean ± σ for City                      |

### Parquet exports (`occupancy-parquet/year=YYYY/month=MM/day=DD/occupancy.parquet`)

Schema: `timestamp (UTC)`, `occupancy_oerlikon`, `occupancy_city`, `hour`, `minute`, `day_of_week`, `is_open_oerlikon`, `is_open_city`

## Documentation

| Path                                                                    | Contents                                |
| ----------------------------------------------------------------------- | --------------------------------------- |
| [QUICKSTART.md](QUICKSTART.md)                                          | Local dev + Azure deployment steps      |
| [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) | System design, data flow, infra details |

## License

MIT — see [LICENSE](LICENSE).
