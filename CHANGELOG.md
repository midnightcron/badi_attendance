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

### Alternatives considered

| Service                        | Est. cost/month | Stays in Azure | Why rejected / chosen                                      |
| ------------------------------ | --------------- | -------------- | ---------------------------------------------------------- |
| **Azure Container Instances**  | ~$1.20          | Yes            | **Chosen** — simplest path, Terraform-native, same RG      |
| Azure Container Apps           | ~$5–10          | Yes            | Overkill for a single listener; free tier limited          |
| Azure VM B1s                   | ~$3.80          | Yes            | More overhead than needed                                  |
| Fly.io                         | Free–$1.94      | No             | Would leave Azure ecosystem                                |
| Hetzner VPS                    | ~€3.29          | No             | No native Azure Storage integration                        |

ACI at 0.25 vCPU / 0.5 GB RAM is more than sufficient for a single WebSocket listener.
`restart_policy = "Always"` handles crashes automatically. `azurerm_container_group`
slots into the existing Terraform setup with no friction.

### Migration approach (minimal downtime)

The Functions collector was kept running throughout — it was never stopped until the ACI
collector had been validated:

- **Phase 0** — annotated the existing Terraform config as production (no rename, to avoid
  resource recreation and downtime)
- **Phase 1** — built the ACI collector against a separate dev storage account; the prod
  collector continued undisturbed
- **Phase 2** — validated ACI for 24–48 hours via `az container logs`; confirmed no gaps
- **Phase 3** — pointed ACI at the prod storage account; both collectors wrote in parallel
  briefly (same row keys = harmless overwrites); then disabled the Functions collector
- **Phase 4** — removed Functions collector from Terraform; cleaned up workflows and code

### Why Table Storage instead of Blob CSV

The previous approach wrote one CSV file per 5-minute window to Blob Storage:

| Operation          | Blob CSV (old)                          | Table Storage (new)                      |
| ------------------ | --------------------------------------- | ---------------------------------------- |
| Write              | Buffer 5 min, flush entire file         | One row per reading, immediate (~3 ms)   |
| Data loss on crash | Up to 5 minutes                         | Zero                                     |
| Read 1 day         | List + download ~288 blobs              | Single range query                       |
| Read 7 days        | ~2,000 blob downloads                   | Single range query                       |
| Indexing           | None — full scan                        | PartitionKey (date) + RowKey (timestamp) |
| Cost               | ~$0.10/month                            | ~$0.01/month                             |

Table Storage uses the same underlying technology as Cosmos DB at a fraction of the cost.
PartitionKey = date, RowKey = `HH:MM:SS.ffffff` gives native range queries with no
client-side iteration.

### Added

- `src/collector-aci/` — persistent Python process running in ACI with `restart=Always`
  - `websocket_handler.py` — subscribes to CrowdMonitor API and extracts both locations per message
  - `table_writer.py` — writes one row to Azure Table Storage every ~4 seconds
  - `aggregator.py` — daily 02:00 CET job computing per-weekday / 15-min-slot averages
  - `main.py` — asyncio entry point; runs collector and aggregator as concurrent tasks; handles `SIGTERM`
- `azure/collector-aci/` — separate Terraform root (independent lifecycle from the API app)
  - Creates resource group, storage account, `occupancy` and `occupancypatterns` tables, ACR, ACI
- `scripts/deploy-collector-aci.sh` — full redeploy: Terraform → Docker build → ACR push → ACI recreate
- Dual-location columns: `occupancy_oerlikon` (SSD-7) and `occupancy_city` (SSD-4) written in every row

### Removed

- Azure Functions collector (`src/collector/`) — replaced by ACI; directory kept for historical reference
- Blob CSV storage as the collector output format (Table Storage is now the primary store)
- `deploy-collector.yml` GitHub Actions workflow — ACI is deployed manually via script

---

## [2026-02-24] — Durable Functions orchestrator (short-lived; replaced by ACI)

### Changed

- Replaced the two leap-frog timer triggers with a single Durable Functions orchestrator.
  The orchestrator scheduled itself for consecutive 5-minute collection windows, eliminating
  split state across two timer functions.

### How the leap-frog pattern worked (now fully removed)

Two Azure Timer Functions fired at staggered offsets:

```text
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

21 commits (`1c591ca`..`3817089`). 156 files changed, 1,770 insertions, 55,688 deletions.

### Starting state

The project was a monolithic Azure Function App (`src/functions/`) that combined
WebSocket data collection and HTTP dashboard endpoints in a single deployment:

- Two leap-frog timer functions (`websocket_listener_even`, `websocket_listener_odd`)
  sharing collection logic that had been copy-pasted between them
- Three HTTP functions (`serve_dashboard`, `get_occupancy`, `health_check`)
- A static HTML dashboard with hardcoded JavaScript
- Accumulated dead code: unused Flask web app, old Bicep IaC, legacy scraper modules,
  obsolete shell scripts, tracked `.zip` build artefacts
- A single CI/CD workflow deploying everything together
- Scattered, outdated documentation across 15+ markdown files

### Root cause: deployment restarts interrupted collection

Five rapid deployments between 22:56–23:27 UTC caused the Function App host to restart
after each push, evicting the always-ready timer triggers and producing collection gaps.
Any dashboard change — however small — restarted the collector.

### What changed

**Phase 1 — Code deduplication** (`1c591ca`)

Extracted shared WebSocket logic from the two leap-frog functions into
`utils/websocket_collector.py` and `utils/websocket_handler.py`. Both timer functions
became thin wrappers.

**Phase 2 — HTTP endpoints** (`bf4a65a`, `b76bdb4`)

Added `serve_dashboard`, `get_occupancy`, and `health_check` as proper Azure Functions.

**Phase 3 — Repository cleanup** (`a87f5ba`..`5cdc1b0`, 11 commits)

- Moved test files to `tests/`
- Removed tracked `.zip` deployment artefacts
- Deleted the legacy Flask app (`src/api/`, `src/main.py`), scraper modules, services
- Removed obsolete scripts (`scrape_once.py`, `scraped_data.csv`)
- Deleted superseded Bicep IaC files (Terraform is the source of truth)
- Cleaned unused Python modules and deprecated test files
- Removed 7 obsolete documentation files and the legacy CI workflow

Result: −55,688 lines. The repo went from a cluttered multi-approach project to a
focused Azure Functions codebase.

**Phase 4 — Documentation rewrite** (`1417978`)

Rewrote `README.md`, `QUICKSTART.md`, and `ARCHITECTURE.md` from scratch.

**Phase 5 — Plotly dashboard** (`fafb96a`, `9338a50`, `4343752`, `c98fcf9`)

Replaced the static HTML/JS dashboard with pure-Python Plotly (server-side rendered,
timezone-aware, no static file serving).

**Phase 6 — CI/CD fixes** (`5ba851f`, `edda44c`)

Removed `SCM_DO_BUILD_DURING_DEPLOYMENT` / `ENABLE_ORYX_BUILD` settings incompatible
with Flex Consumption. Added deployment status badge.

**Phase 7 — Two-app split** (`3817089`)

Split the monolithic app into two independent Function Apps:

| App                           | Functions                                           | Scaling                    |
| ----------------------------- | --------------------------------------------------- | -------------------------- |
| `badi-oerlikon-dev-collector` | `websocket_listener_even`, `websocket_listener_odd` | Always-ready (2 instances) |
| `badi-oerlikon-dev-api`       | `serve_dashboard`, `get_occupancy`, `health_check`  | Scale to zero              |

Each got its own `host.json`, `requirements.txt`, `local.settings.json`, `.funcignore`,
and a path-filtered CI/CD workflow. Terraform updated to two `azurerm_function_app_flex_consumption`
resources sharing one service plan.

**Key property:** Deploying a dashboard change only restarts the API app. The collector
keeps running uninterrupted. (This property was later strengthened further by moving the
collector to ACI — see [2026-02-27].)

### Lessons learned

- **Start with _why_, not _what_.** "My timer triggers miss invocations after deployments"
  immediately points toward isolation. "Clean up my repo" leads to incremental work.
- **Diagnose architectural problems before writing code.** Half the cleanup work was
  tangential to the actual problem.
- **Batch related changes.** The 11 cleanup commits could have been one.

---

## Earlier history

Initial versions used HTTP scraping (polling rather than WebSocket) and a Flask web
application served as a Docker container. Both were abandoned in favour of the Azure
Functions architecture described above.
