"""
Azure Function: Leap-frog WebSocket listener (EVEN intervals).

Fires at :00, :10, :20, :30, :40, :50 seconds of every hour.
Collects 5 minutes of continuous BADI Oerlikon occupancy data.
Logs to Application Insights.

Note: This is one of two leap-frog functions. The other
(websocket_listener_odd) fires at :05, :15, :25, :35, :45, :55.
Together they provide continuous non-overlapping data collection.

Schedule: 0 */10 * * * * (every 10 minutes at :00 seconds)
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
    Azure Function: Leap-frog WebSocket listener (EVEN).

    Timer: Fires every 10 minutes at :00 seconds
    Collection: 5 minutes of continuous data
    Data: Occupancy readings to Application Insights

    Args:
        mytimer: Timer trigger object
    """
    logger = logging.getLogger("websocket_listener_even_main")
    logger.info("[EVEN] Function invoked")
    
    try:
        asyncio.run(_async_main(mytimer))
        logger.info("[EVEN] Collection completed successfully")
    except Exception as e:
        logger.error(
            f"[EVEN] Fatal error: {e}", exc_info=True
        )
        raise


async def _async_main(mytimer: func.TimerRequest) -> None:
    """
    Async implementation: Collect 5 minutes of occupancy data.

    This function collects for the full 5-minute window, then returns
    quickly to avoid blocking the next leap-frog function. While this
    function runs 22:00-22:05, websocket_listener_odd is idle.
    When this returns at 22:05, websocket_listener_odd fires at 22:05
    and collects 22:05-22:10, so there's no gap and no overlap.
    """
    logger = logging.getLogger("websocket_listener_even")
    window_start = datetime.utcnow()
    start_time = time.time()

    if mytimer.past_due:
        logger.warning("websocket_listener_even timer is past due")

    logger.info(
        f"[EVEN] WebSocket listener (even) started at "
        f"{window_start.isoformat()}"
    )

    try:
        websocket_url = os.getenv(
            "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
        )
        target_uid = os.getenv("TARGET_UID", "SSD-7")

        logger.info(
            f"[EVEN] Connecting to: {websocket_url}, UID: {target_uid}"
        )

        # Import WebSocketListener here (lazy load) to avoid init-time issues
        from .websocket_handler import WebSocketListener

        # Collect for full 5 minutes (300 seconds)
        listener = WebSocketListener(
            url=websocket_url, target_uid=target_uid, duration_seconds=300
        )
        updates = await listener.collect_updates()

        elapsed = time.time() - start_time
        logger.info(
            f"[EVEN] Collected {len(updates)} updates in 5-minute window "
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
                f"[EVEN] Stats: count={stats['count']}, min={stats['min']}, "
                f"max={stats['max']}, avg={stats['avg']:.1f}, "
                f"median={stats['median']}"
            )
            logger.info(
                f"[EVEN] Sample updates: {json.dumps(updates[:5])}"
            )

            # Write to blob storage as CSV (if available)
            try:
                await _write_to_blob(logger, updates, window_start, "even")
            except Exception as blob_error:
                logger.warning(
                    f"[EVEN] Could not write to blob: {blob_error}"
                )
        else:
            logger.warning(
                "[EVEN] No updates received in 5-minute window"
            )

    except Exception as e:
        logger.error(
            f"[EVEN] Error in websocket_listener_even: {e}", exc_info=True
        )
        raise

async def _write_to_blob(logger, updates, window_start, label):
    """Write occupancy readings to blob storage as CSV."""
    try:
        # Local import to avoid module-level dependency issues
        from azure.storage.blob import BlobClient
        
        # Get blob storage connection details
        conn_str = os.getenv("AzureWebJobsStorage")
        container_name = os.getenv(
            "BLOB_CONTAINER_NAME", "occupancy-data"
        )

        if not conn_str:
            logger.warning(
                f"[{label.upper()}] AzureWebJobsStorage not configured, "
                f"skipping blob write"
            )
            return

        # Generate blob name: occupancy_2026-02-19_10_00.csv
        blob_name = window_start.strftime("occupancy_%Y-%m-%d_%H_%M.csv")

        # Build CSV content: timestamp,occupancy
        csv_lines = ["timestamp,occupancy"]
        for update in updates:
            ts = update["timestamp"]
            occ = update["occupancy"]
            csv_lines.append(f"{ts},{occ}")

        csv_content = "\n".join(csv_lines)

        # Write to blob
        blob_client = BlobClient.from_connection_string(
            conn_str, container_name, blob_name
        )
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