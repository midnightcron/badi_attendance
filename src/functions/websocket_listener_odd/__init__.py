"""
Azure Function: Leap-frog WebSocket listener (ODD intervals).

Fires at :05, :15, :25, :35, :45, :55 seconds of every hour.
Collects 5 minutes of continuous BADI Oerlikon occupancy data.
Logs to Application Insights.

Note: This is one of two leap-frog functions. The other
(websocket_listener_even) fires at :00, :10, :20, :30, :40, :50.
Together they provide continuous non-overlapping data collection.

Schedule: 5 */10 * * * * (every 10 minutes at :05 seconds)
Expected: ~30-40 updates per 5-minute collection window
          (~1 update every 8-10 seconds from API = ~30-40 per 5 min)
"""

import azure.functions as func
import asyncio
import json
import logging
import os
import time
from datetime import datetime


def main(mytimer: func.TimerRequest) -> None:
    """
    Azure Function: Leap-frog WebSocket listener (ODD).

    Timer: Fires every 10 minutes at :05 seconds
    Collection: 5 minutes of continuous data
    Data: Occupancy readings to Application Insights

    Args:
        mytimer: Timer trigger object
    """
    logger = logging.getLogger("websocket_listener_odd_main")
    logger.info("[ODD] Function invoked")
    
    try:
        asyncio.run(_async_main(mytimer))
        logger.info("[ODD] Collection completed successfully")
    except Exception as e:
        logger.error(
            f"[ODD] Fatal error: {e}", exc_info=True
        )
        raise


async def _async_main(mytimer: func.TimerRequest) -> None:
    """
    Async implementation: Collect 5 minutes of occupancy data.

    This function collects for the full 5-minute window. The 10-minute
    functionTimeout in host.json gives headroom for the blob write.
    While this function runs 22:05-22:10, websocket_listener_even is idle.
    When this returns at 22:10, websocket_listener_even fires at 22:10
    and collects 22:10-22:15, so there's no gap and no overlap.
    """
    logger = logging.getLogger("websocket_listener_odd")
    window_start = datetime.utcnow()
    start_time = time.time()

    if mytimer.past_due:
        logger.warning("websocket_listener_odd timer is past due")

    logger.info(
        f"[ODD] WebSocket listener (odd) started at "
        f"{window_start.isoformat()}"
    )

    try:
        websocket_url = os.getenv(
            "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
        )
        target_uid = os.getenv("TARGET_UID", "SSD-7")

        logger.info(
            f"[ODD] Connecting to: {websocket_url}, UID: {target_uid}"
        )

        # Import WebSocketListener here (lazy load) to avoid init-time issues
        from .websocket_handler import WebSocketListener

        # Collect for full 5 minutes (300s). The 10-minute functionTimeout
        # in host.json gives headroom for the blob write after collection.
        listener = WebSocketListener(
            url=websocket_url, target_uid=target_uid, duration_seconds=300
        )
        updates = await listener.collect_updates()

        elapsed = time.time() - start_time
        logger.info(
            f"[ODD] Collected {len(updates)} updates in 5-minute window "
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
                f"[ODD] Stats: count={stats['count']}, min={stats['min']}, "
                f"max={stats['max']}, avg={stats['avg']:.1f}, "
                f"median={stats['median']}"
            )
            logger.info(
                f"[ODD] Sample updates: {json.dumps(updates[:5])}"
            )

            # Write to blob storage as CSV (if available)
            try:
                await _write_to_blob(logger, updates, window_start, "odd")
            except Exception as blob_error:
                logger.warning(
                    f"[ODD] Could not write to blob: {blob_error}"
                )
        else:
            logger.warning("[ODD] No updates received in 5-minute window")

    except Exception as e:
        logger.error(
            f"[ODD] Error in websocket_listener_odd: {e}", exc_info=True
        )
        raise

async def _write_to_blob(logger, updates, window_start, label):
    """Write occupancy readings to blob storage as CSV."""
    try:
        # Local import to avoid module-level dependency issues
        from azure.storage.blob import BlobServiceClient

        # Use AZURE_STORAGE_CONNECTION_STRING (real conn string)
        # Fall back to AzureWebJobsStorage only if it's a real connection string
        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not conn_str:
            aws = os.getenv("AzureWebJobsStorage", "")
            if aws and aws != "UseDevelopmentStorage=true":
                conn_str = aws

        container_name = os.getenv(
            "BLOB_CONTAINER_NAME", "occupancy-data"
        )

        if not conn_str:
            logger.warning(
                f"[{label.upper()}] No storage connection string configured, "
                f"skipping blob write. Set AZURE_STORAGE_CONNECTION_STRING."
            )
            return

        # Generate blob name: YYYY-MM-DD/HH-MM.csv (organized by date)
        date_folder = window_start.strftime("%Y-%m-%d")
        blob_name = f"{date_folder}/{window_start.strftime('occupancy_%H_%M.csv')}"

        # Build CSV content: timestamp,occupancy
        csv_lines = ["timestamp,occupancy"]
        for update in updates:
            ts = update["timestamp"]
            occ = update["occupancy"]
            csv_lines.append(f"{ts},{occ}")

        csv_content = "\n".join(csv_lines)

        # Create container if it doesn't exist, then upload
        blob_service_client = BlobServiceClient.from_connection_string(conn_str)
        container_client = blob_service_client.get_container_client(container_name)
        try:
            container_client.create_container()
            logger.info(f"[{label.upper()}] Created container: {container_name}")
        except Exception:
            pass  # Container already exists

        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(csv_content, overwrite=True)

        logger.info(
            f"[{label.upper()}] Wrote {len(updates)} occupancy readings "
            f"to blob: {blob_name}"
        )

    except Exception as e:
        logger.error(
            f"[{label.upper()}] Error writing to blob storage: {e}",
            exc_info=True
        )
        # Don't raise - don't fail entire function if blob write fails