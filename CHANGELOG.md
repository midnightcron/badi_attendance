# Changelog

All notable changes to this project are documented here.

## [2026-03-02] — Parquet export & API improvements

### Added
- Nightly Parquet export of occupancy data to Blob Storage (`occupancy-parquet/year=YYYY/month=MM/day=DD/`)
- `15min` resolution option for the `/api/occupancy` endpoint
- Location-aware opening hours in dashboard (Oerlikon and City have different weekly schedules)
- Location toggle on dashboard to switch between Hallenbad Oerlikon and Hallenbad City

### Changed
- API data source switched from Blob CSV downloads to Azure Table Storage queries.
  The previous approach fetched up to ~8,928 CSV blobs per dashboard request (~90–120 s).
  Table Storage queries return the same data in ~30 indexed lookups (<5 s).

### Infrastructure
- Pinned function runtime storage account name; removed `random_string` dependency
- Removed Azure Functions collector resources from Terraform (ACI is now the sole collector)

---

## [2026-02-27] — ACI collector replaces Azure Functions collector

The persistent WebSocket collector was rewritten as an Azure Container Instance (ACI).
The Azure Functions-based collector (both the leap-frog and Durable Functions variants)
is retired.

### Added
- `src/collector-aci/` — persistent Python process running in ACI with `restart=Always`
  - `websocket_handler.py` — subscribes to CrowdMonitor API and extracts both locations per message
  - `table_writer.py` — writes one row to Azure Table Storage every ~4 seconds
  - `aggregator.py` — daily 02:00 CET job computing per-weekday / 15-min-slot averages
  - `main.py` — asyncio entry point; runs collector and aggregator as concurrent tasks; handles `SIGTERM`
- `azure/collector-aci/` — separate Terraform root (independent lifecycle from the API app)
  - Creates resource group, storage account, `occupancy` and `occupancypatterns` tables, ACR, ACI
- `scripts/deploy-collector-aci.sh` — full redeploy: Terraform → Docker build → ACR push → ACI recreate
- Dual-location columns: `occupancy_oerlikon` and `occupancy_city` written in every row

### Removed
- Azure Functions collector (`src/collector/`) — replaced by ACI; directory kept for historical reference
- Blob CSV storage as the collector output format (Table Storage is now the primary store)
- `deploy-collector.yml` GitHub Actions workflow — ACI is deployed manually via script

### Why ACI instead of Azure Functions
Azure Functions run in discrete invocation windows (max 296 s on Consumption). The
leap-frog pattern worked around this, but any deployment restarted the Function App host,
causing a collection gap. An ACI container holds a single long-lived WebSocket connection
and automatically restarts without data loss.

---

## [2026-02-24] — Durable Functions orchestrator (short-lived; replaced by ACI)

### Changed
- Replaced the two leap-frog timer triggers with a single Durable Functions orchestrator.
  The orchestrator scheduled itself for consecutive 5-minute collection windows, eliminating
  split state across two timer functions.

### How the leap-frog pattern worked (now fully removed)
Two Azure Timer Functions fired at staggered offsets:

```
Time:   :00   :05   :10   :15   :20   :25   :30
EVEN:   |=====|     |=====|     |=====|     |=====|
ODD:          |=====|     |=====|     |=====|
```

Each function opened a WebSocket connection and collected for ~4.5 minutes, overlapping
slightly with the other so that no readings were missed. The approach hit the Azure Functions
execution limit (five-minute window) and caused data gaps on every Function App deployment.
The Durable Functions orchestrator consolidated this into one self-scheduling unit, but
still suffered from the deployment-restart problem — which the ACI migration solved
definitively.

---

## [2026-02-24] — Collector/API split and major cleanup

### Added
- Two independent Azure Function Apps: one for the collector, one for the HTTP API
- Pure-Python Plotly dashboard replacing the static HTML file with hardcoded JavaScript
- `health_check`, `get_occupancy`, `serve_dashboard` HTTP endpoints
- Dark-mode dashboard (GitHub palette) with resolution slider and best 30-min window marker
- Separate Terraform roots for collector and API (independent lifecycle management)
- OIDC-based GitHub Actions deployment (no long-lived secrets)

### Removed
- Monolithic single Function App that combined WebSocket collection and HTTP endpoints.
  Any dashboard change restarted the host and interrupted data collection.
- Static HTML dashboard with hardcoded JavaScript
- Legacy Flask web application (`src/api/`, `src/main.py`)
- Old Bicep IaC files (Terraform is the sole infrastructure-as-code)
- Deprecated scraper modules, legacy shell scripts, and tracked build artefacts
- 15+ obsolete documentation files consolidated into README / QUICKSTART / ARCHITECTURE

---

## Earlier history

Initial versions of this project used a scraper-based approach (HTTP polling rather than
WebSocket) and a Flask web application served as a Docker container. Both were abandoned
in favour of the Azure Functions architecture described above.
