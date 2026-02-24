"""
Shared WebSocket collection logic.

Called by the Durable Functions activity to perform a single ~296 s
collection cycle: connect to CrowdMonitor → gather occupancy readings →
write CSV to blob storage.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Zurich")


def run_collection() -> dict:
    """
    Entry point called by the collect_activity Durable Function.

    Returns:
        dict with collection stats (count, min, max, avg, duration_s).
    """
    logger = logging.getLogger("collector")
    logger.info("Collection cycle started")

    try:
        result = asyncio.run(_async_collect())
        logger.info("Collection cycle completed successfully")
        return result
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise


async def _async_collect() -> dict:
    """
    Async implementation: connect to WebSocket, collect ~296 s of
    occupancy data, compute stats, and persist to blob storage.

    Returns:
        dict with collection stats.
    """
    logger = logging.getLogger("collector")
    window_start = datetime.now(_TZ)
    start_time = time.time()

    logger.info(f"WebSocket collection started at {window_start.isoformat()}")

    try:
        websocket_url = os.getenv(
            "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
        )
        target_uid = os.getenv("TARGET_UID", "SSD-7")

        logger.info(f"Connecting to: {websocket_url}, UID: {target_uid}")

        # Lazy import to avoid init-time issues
        from utils.websocket_handler import WebSocketListener

        # Collect for ~296 s.  The orchestrator schedules the next cycle
        # 300 s after the start, so there is a ~4 s gap — short enough
        # that no data is lost (API pushes every ~3-4 s).
        listener = WebSocketListener(
            url=websocket_url, target_uid=target_uid, duration_seconds=296
        )
        updates = await listener.collect_updates()

        elapsed = time.time() - start_time
        logger.info(
            f"Collected {len(updates)} updates in {elapsed:.1f}s"
        )

        result = {"count": 0, "duration_s": round(elapsed, 1)}

        if updates:
            occupancies = [u["occupancy"] for u in updates]
            result.update({
                "count": len(updates),
                "min": min(occupancies),
                "max": max(occupancies),
                "avg": round(sum(occupancies) / len(occupancies), 1),
                "median": sorted(occupancies)[len(occupancies) // 2],
            })

            logger.info(
                f"Stats: count={result['count']}, min={result['min']}, "
                f"max={result['max']}, avg={result['avg']}, "
                f"median={result['median']}"
            )

            # Write to blob storage as CSV
            try:
                await _write_to_blob(logger, updates, window_start)
            except Exception as blob_error:
                logger.warning(f"Could not write to blob: {blob_error}")
        else:
            logger.warning("No updates received in collection window")

        return result

    except Exception as e:
        logger.error(f"Error during collection: {e}", exc_info=True)
        raise


async def _write_to_blob(logger, updates, window_start):
    """Write occupancy readings to blob storage as CSV."""
    try:
        from azure.storage.blob import BlobServiceClient

        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not conn_str:
            aws = os.getenv("AzureWebJobsStorage", "")
            if aws and aws != "UseDevelopmentStorage=true":
                conn_str = aws

        container_name = os.getenv("BLOB_CONTAINER_NAME", "occupancy-data")

        if not conn_str:
            logger.warning(
                "No storage connection string configured, "
                "skipping blob write. Set AZURE_STORAGE_CONNECTION_STRING."
            )
            return

        date_folder = window_start.strftime("%Y-%m-%d")
        blob_name = (
            f"{date_folder}/"
            f"{window_start.strftime('occupancy_%H_%M.csv')}"
        )

        csv_lines = ["timestamp,occupancy"]
        for update in updates:
            csv_lines.append(f"{update['timestamp']},{update['occupancy']}")

        csv_content = "\n".join(csv_lines)

        blob_service_client = BlobServiceClient.from_connection_string(conn_str)
        container_client = blob_service_client.get_container_client(
            container_name
        )
        try:
            container_client.create_container()
            logger.info(f"Created container: {container_name}")
        except Exception:
            pass  # Container already exists

        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(csv_content, overwrite=True)

        logger.info(
            f"Wrote {len(updates)} readings to blob: "
            f"{container_name}/{blob_name}"
        )

    except Exception as e:
        logger.error(f"Error writing to blob storage: {e}", exc_info=True)
        # Don't raise — don't fail entire function if blob write fails
