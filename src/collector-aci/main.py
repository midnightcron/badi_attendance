"""
ACI-based WebSocket collector for BADI Oerlikon occupancy data.

Runs as a persistent process (no timer triggers, no function restarts).
Connects to the CrowdMonitor WebSocket and writes each occupancy
reading immediately to Azure Table Storage — zero buffering, zero
data loss on crash.

A periodic summary log is emitted every STATS_INTERVAL_SECONDS
so operators can confirm healthy throughput.

Environment variables:
    WEBSOCKET_URL               WebSocket endpoint
                                (default: wss://…crowdmonitor…)
    TARGET_UID                  Location UID to track (default: SSD-7)
    AZURE_STORAGE_CONNECTION_STRING   Storage connection string
    TABLE_NAME                  Table Storage table (default: occupancy)
    STATS_INTERVAL_SECONDS      How often to log a stats line (default: 300)
    LOG_LEVEL                   Logging level (default: INFO)
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from table_writer import get_table_client, write_reading
from websocket_handler import WebSocketClient

_TZ = ZoneInfo("Europe/Zurich")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WEBSOCKET_URL = os.getenv(
    "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
)
TARGET_UID = os.getenv("TARGET_UID", "SSD-7")
STATS_INTERVAL = int(os.getenv("STATS_INTERVAL_SECONDS", "300"))
TABLE_NAME = os.getenv("TABLE_NAME", "occupancy")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Reconnection back-off
INITIAL_BACKOFF = 2      # seconds
MAX_BACKOFF = 120         # seconds
BACKOFF_FACTOR = 2

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    stream=sys.stdout,
)
logger = logging.getLogger("collector-aci")

# Silence verbose Azure SDK HTTP logging (every request/response)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
    logging.WARNING
)

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown_event = asyncio.Event()


def _request_shutdown(sig, _frame):
    logger.info(f"Received signal {signal.Signals(sig).name} — shutting down")
    _shutdown_event.set()


# ---------------------------------------------------------------------------
# Main collection loop
# ---------------------------------------------------------------------------
async def collection_loop() -> None:
    """Infinite loop: connect → write each reading immediately."""
    backoff = INITIAL_BACKOFF
    client = WebSocketClient(url=WEBSOCKET_URL, target_uid=TARGET_UID)

    # Initialise Table Storage client once
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    if not conn_str:
        logger.error("AZURE_STORAGE_CONNECTION_STRING not set — exiting")
        return

    table_client = get_table_client(conn_str, TABLE_NAME)
    logger.info(f"Table Storage client ready (table={TABLE_NAME})")

    while not _shutdown_event.is_set():
        # Stats counters for the current connection session
        writes_since_log = 0
        errors_since_log = 0
        last_log_time = datetime.now(_TZ)

        try:
            async with client.connect() as ws:
                logger.info(
                    f"Connected to {WEBSOCKET_URL} — "
                    f"tracking {TARGET_UID}"
                )
                backoff = INITIAL_BACKOFF

                while not _shutdown_event.is_set():
                    # Periodic stats log
                    now = datetime.now(_TZ)
                    since = (now - last_log_time).total_seconds()
                    if since >= STATS_INTERVAL:
                        logger.info(
                            f"Stats: {writes_since_log} writes, "
                            f"{errors_since_log} errors "
                            f"in last {int(since)}s"
                        )
                        writes_since_log = 0
                        errors_since_log = 0
                        last_log_time = now

                    # Wait for next message
                    try:
                        message = await asyncio.wait_for(
                            ws.recv(), timeout=10.0
                        )
                        data = client.parse_message(message)
                        if data:
                            # Always write both columns, even if one is None
                            try:
                                write_reading(table_client, data)
                                writes_since_log += 1
                            except Exception as we:
                                errors_since_log += 1
                                logger.error(
                                    f"Table write failed: {we}",
                                    exc_info=True,
                                )

                    except asyncio.TimeoutError:
                        continue

        except asyncio.CancelledError:
            logger.info("Task cancelled — exiting")
            return

        except Exception as e:
            logger.error(f"WebSocket error: {e}", exc_info=True)

            if _shutdown_event.is_set():
                return

            logger.info(f"Reconnecting in {backoff}s …")
            await asyncio.sleep(backoff)
            backoff = min(backoff * BACKOFF_FACTOR, MAX_BACKOFF)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    # Register signal handlers before entering the event loop
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_shutdown)

    logger.info("=== BADI Oerlikon ACI Collector starting ===")
    logger.info(f"  WebSocket : {WEBSOCKET_URL}")
    logger.info(f"  Target UID: {TARGET_UID}")
    logger.info(f"  Storage   : Table Storage (table={TABLE_NAME})")
    logger.info(f"  Stats log : every {STATS_INTERVAL}s")
    logger.info(f"  Timezone  : {_TZ}")

    try:
        asyncio.run(collection_loop())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting")

    logger.info("=== Collector stopped ===")


if __name__ == "__main__":
    main()
