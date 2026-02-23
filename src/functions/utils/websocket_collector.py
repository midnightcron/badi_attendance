"""
Shared WebSocket collection logic for leap-frog timer functions.

Both websocket_listener_even and websocket_listener_odd call
`run_collection(label, mytimer)` with their respective label.
This avoids duplicating ~150 lines of identical Python code.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

import azure.functions as func


def run_collection(label: str, mytimer: func.TimerRequest) -> None:
    """
    Entry point called by each Azure Function's main().

    Args:
        label: "even" or "odd" — used for log prefixes and blob paths.
        mytimer: The Azure Functions TimerRequest object.
    """
    tag = label.upper()
    logger = logging.getLogger(f"websocket_listener_{label}_main")
    logger.info(f"[{tag}] Function invoked")

    try:
        asyncio.run(_async_collect(label, mytimer))
        logger.info(f"[{tag}] Collection completed successfully")
    except Exception as e:
        logger.error(f"[{tag}] Fatal error: {e}", exc_info=True)
        raise


async def _async_collect(label: str, mytimer: func.TimerRequest) -> None:
    """
    Async implementation: connect to WebSocket, collect 5 minutes of
    occupancy data, compute stats, and persist to blob storage.
    """
    tag = label.upper()
    logger = logging.getLogger(f"websocket_listener_{label}")
    window_start = datetime.now(timezone.utc)
    start_time = time.time()

    if mytimer.past_due:
        logger.warning(f"websocket_listener_{label} timer is past due")

    logger.info(
        f"[{tag}] WebSocket listener ({label}) started at "
        f"{window_start.isoformat()}"
    )

    try:
        websocket_url = os.getenv(
            "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
        )
        target_uid = os.getenv("TARGET_UID", "SSD-7")

        logger.info(
            f"[{tag}] Connecting to: {websocket_url}, UID: {target_uid}"
        )

        # Lazy import to avoid init-time issues
        from utils.websocket_handler import WebSocketListener

        # Collect for ~5 minutes (298 s). Slightly under 300 s to avoid
        # capturing a duplicate data point at the leap-frog boundary.
        listener = WebSocketListener(
            url=websocket_url, target_uid=target_uid, duration_seconds=298
        )
        updates = await listener.collect_updates()

        elapsed = time.time() - start_time
        logger.info(
            f"[{tag}] Collected {len(updates)} updates in 5-minute window "
            f"(actual time: {elapsed:.1f}s)"
        )

        if updates:
            occupancies = [u["occupancy"] for u in updates]
            stats = {
                "count": len(updates),
                "min": min(occupancies),
                "max": max(occupancies),
                "avg": sum(occupancies) / len(occupancies),
                "median": sorted(occupancies)[len(occupancies) // 2],
            }

            logger.info(
                f"[{tag}] Stats: count={stats['count']}, min={stats['min']}, "
                f"max={stats['max']}, avg={stats['avg']:.1f}, "
                f"median={stats['median']}"
            )
            logger.info(
                f"[{tag}] Sample updates: {json.dumps(updates[:5])}"
            )

            # Write to blob storage as CSV (if available)
            try:
                await _write_to_blob(logger, updates, window_start, label)
            except Exception as blob_error:
                logger.warning(
                    f"[{tag}] Could not write to blob: {blob_error}"
                )
        else:
            logger.warning(
                f"[{tag}] No updates received in 5-minute window"
            )

    except Exception as e:
        logger.error(
            f"[{tag}] Error in websocket_listener_{label}: {e}",
            exc_info=True,
        )
        raise


async def _write_to_blob(logger, updates, window_start, label):
    """Write occupancy readings to blob storage as CSV."""
    tag = label.upper()
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
                f"[{tag}] No storage connection string configured, "
                f"skipping blob write. Set AZURE_STORAGE_CONNECTION_STRING."
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
            logger.info(f"[{tag}] Created container: {container_name}")
        except Exception:
            pass  # Container already exists

        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(csv_content, overwrite=True)

        logger.info(
            f"[{tag}] Wrote {len(updates)} occupancy readings "
            f"to blob: {container_name}/{blob_name}"
        )

    except Exception as e:
        logger.error(
            f"[{tag}] Error writing to blob storage: {e}",
            exc_info=True,
        )
        # Don't raise — don't fail entire function if blob write fails
