# Badi Oerlikon Occupancy Monitor

[![Collector Deploy](https://github.com/rworreby/badi_oerlikon_attendence/actions/workflows/deploy-collector.yml/badge.svg?branch=main)](https://github.com/rworreby/badi_oerlikon_attendence/actions/workflows/deploy-collector.yml)
[![API Deploy](https://github.com/rworreby/badi_oerlikon_attendence/actions/workflows/deploy-api.yml/badge.svg?branch=main)](https://github.com/rworreby/badi_oerlikon_attendence/actions/workflows/deploy-api.yml)

Real-time occupancy monitoring for Badi Oerlikon swimming pool using WebSocket data collection on Azure Functions.

## What It Does

- Connects to the CrowdMonitor WebSocket API (`wss://badi-public.crowdmonitor.ch:9591/api`)
- Monitors **SSD-7** (Badi Oerlikon) occupancy in real time
- Collects ~75 readings per 5-minute window (one every ~4 seconds)
- Saves CSV files with timestamp + occupancy to Azure Blob Storage
- Serves a dashboard and REST API for querying historical data

## Architecture

The system is split into **two independent Azure Function Apps** so that dashboard
development never interrupts the data collectors:

| App | Functions | Deploys when |
|-----|-----------|--------------|
| **Collector** (`badi-oerlikon-dev-collector`) | `websocket_listener_even`, `websocket_listener_odd` | `src/collector/**` changes |
| **API** (`badi-oerlikon-dev-api`) | `serve_dashboard`, `get_occupancy`, `health_check` | `src/api/**` changes |

Both share the same blob storage account and App Insights instance. The
collector has `always_ready` instances; the API scales to zero when idle.

**Leap-frog collection pattern:**

```
Time:   :00   :05   :10   :15   :20   :25   :30
EVEN:   |=====|     |=====|     |=====|     |=====|
ODD:          |=====|     |=====|     |=====|
```

Each function collects for 298 seconds (just under 5 minutes), then hands off to the other. Both have `useMonitor: false` to prevent catch-up cascade from Azure's singleton lock.

**Infrastructure:**
- **Runtime:** Azure Functions, Python 3.11, v1 programming model
- **Plan:** Flex Consumption (FC1) — shared service plan, two apps
- **Storage:** Azure Blob Storage (CSV files in `occupancy-data/YYYY-MM-DD/occupancy_HH_MM.csv`)
- **IaC:** Terraform (azurerm ~4.0)
- **CI/CD:** GitHub Actions — separate path-filtered workflows per app

## Project Structure

```
badi_oerlikon_attendence/
├── src/
│   ├── collector/                      # Function App 1: data collection (timer triggers)
│   │   ├── websocket_listener_even/    # Timer: :00, :10, :20, :30, :40, :50
│   │   ├── websocket_listener_odd/     # Timer: :05, :15, :25, :35, :45, :55
│   │   ├── utils/                      # Shared modules
│   │   │   ├── websocket_collector.py  # Collection + stats + blob write
│   │   │   └── websocket_handler.py    # WebSocketListener class
│   │   ├── host.json                   # 10-min function timeout
│   │   └── requirements.txt            # websockets, azure-storage-blob, …
│   │
│   └── api/                            # Function App 2: HTTP endpoints
│       ├── serve_dashboard/            # HTTP: GET /api/dashboard (Plotly)
│       ├── get_occupancy/              # HTTP: GET /api/occupancy (JSON API)
│       ├── health_check/               # HTTP: GET /api/health_check
│       ├── utils/
│       │   └── dashboard_builder.py    # Plotly chart generation (pure Python)
│       ├── host.json
│       └── requirements.txt            # plotly, azure-storage-blob, …
│
├── azure/                              # Terraform infrastructure
│   ├── main.tf                         # Two Function Apps, Storage, App Insights
│   ├── variables.tf                    # Input variables
│   ├── outputs.tf                      # Terraform outputs
│   └── terraform.tfvars                # Variable values
│
├── .github/workflows/                  # CI/CD (path-filtered)
│   ├── deploy-collector.yml            # Deploys only on src/collector/** changes
│   └── deploy-api.yml                  # Deploys only on src/api/** changes
│
├── tests/                              # Manual test scripts
│   └── test_websocket_connectivity.py  # Quick CrowdMonitor WebSocket check
├── docker-compose.functions.yml        # Local dev (Azurite + Functions runtime)
├── pyproject.toml                      # Project metadata
└── docs/                               # Extended documentation
```

## Quick Start

### Local Development (Docker Compose)

```bash
docker-compose -f docker-compose.functions.yml up
```

This starts Azurite (local blob emulator) and the Azure Functions runtime. Timer triggers fire automatically; HTTP endpoints available at `http://localhost:7071/api/`.

### Deploy to Azure

```bash
# 1. Provision infrastructure
cd azure
terraform init
terraform plan
terraform apply

# 2. Push to main branch — GitHub Actions deploys automatically
git push origin main
```

See [docs/deployment/](docs/deployment/) for detailed deployment guides.

## HTTP Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health_check` | GET | Runtime health + config status |
| `/api/occupancy` | GET | Query occupancy data (params: `days`, `resolution`, `date`) |
| `/api/dashboard` | GET | Interactive Plotly dashboard (generated by Python) |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBSOCKET_URL` | `wss://badi-public.crowdmonitor.ch:9591/api` | CrowdMonitor WebSocket endpoint |
| `TARGET_UID` | `SSD-7` | Location UID to monitor |
| `AZURE_STORAGE_CONNECTION_STRING` | — | Blob storage connection string |
| `BLOB_CONTAINER_NAME` | `occupancy-data` | Container for CSV data |

## Data Format

Each 5-minute window produces a CSV file:

```
occupancy-data/
└── 2026-06-15/
    ├── occupancy_00_00.csv
    ├── occupancy_00_05.csv
    ├── occupancy_00_10.csv
    └── ...

# CSV contents:
timestamp,occupancy
2026-06-15T00:00:03.123456,45
2026-06-15T00:00:07.234567,46
...
```

## Documentation

| Path | Contents |
|------|----------|
| [docs/architecture/](docs/architecture/) | System design, leap-frog pattern, WebSocket protocol |
| [docs/deployment/](docs/deployment/) | Azure deployment guides, checklists, secrets setup |
| [docs/technical/](docs/technical/) | Timeout considerations, local testing, changelog |

## License

MIT — see [LICENSE](LICENSE).
