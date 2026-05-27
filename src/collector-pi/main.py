"""
Pi WebSocket collector — writes to PostgreSQL (TimescaleDB).

Replaces the Azure ACI collector (src/collector-aci/main.py).
No aggregation loop — TimescaleDB continuous aggregate handles that.

Environment variables:
    DATABASE_URL               postgresql://badi@postgres/badi  (no password)
    WEBSOCKET_URL              CrowdMonitor endpoint
    STATS_INTERVAL_SECONDS     How often to log throughput (default: 300)
    LOG_LEVEL                  default: INFO
"""

import asyncio
import logging
import os
import signal
import sys

import structlog

from db import create_pool, write_reading
from websocket_handler import WebSocketClient

WEBSOCKET_URL = os.getenv("WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api")
STATS_INTERVAL = int(os.getenv("STATS_INTERVAL_SECONDS", "300"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

INITIAL_BACKOFF = 2
MAX_BACKOFF = 120
BACKOFF_FACTOR = 2

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    stream=sys.stdout,
)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(LOG_LEVEL)),
)
log = structlog.get_logger("collector-pi")

_shutdown_event = asyncio.Event()


def _request_shutdown(sig, _frame) -> None:
    log.info("shutdown requested", signal=signal.Signals(sig).name)
    _shutdown_event.set()


async def collection_loop(pool) -> None:
    client = WebSocketClient(url=WEBSOCKET_URL)
    backoff = INITIAL_BACKOFF
    writes = errors = 0
    last_stats = asyncio.get_event_loop().time()

    while not _shutdown_event.is_set():
        try:
            async with client.connect() as ws:
                log.info("connected", url=WEBSOCKET_URL)
                backoff = INITIAL_BACKOFF

                while not _shutdown_event.is_set():
                    now = asyncio.get_event_loop().time()
                    if now - last_stats >= STATS_INTERVAL:
                        log.info("stats", writes=writes, errors=errors)
                        writes = errors = 0
                        last_stats = now

                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=10.0)
                        reading = client.parse_message(message)
                        if reading:
                            try:
                                await write_reading(pool, reading)
                                writes += 1
                            except Exception as e:
                                errors += 1
                                log.error("write failed", exc_info=e)
                    except asyncio.TimeoutError:
                        continue

        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error("websocket error", exc_info=e)
            if _shutdown_event.is_set():
                return
            log.info("reconnecting", delay=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * BACKOFF_FACTOR, MAX_BACKOFF)


async def _main() -> None:
    pool = await create_pool()
    log.info("collector starting", url=WEBSOCKET_URL, stats_interval=STATS_INTERVAL)
    try:
        await collection_loop(pool)
    finally:
        await pool.close()


def main() -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_shutdown)

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass

    log.info("collector stopped")


if __name__ == "__main__":
    main()
