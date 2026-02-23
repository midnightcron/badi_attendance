"""
Azure Function: Listen to BADI Oerlikon WebSocket for occupancy data.

This function connects to the CrowdMonitor WebSocket API and collects
occupancy readings for 4 minutes, then saves to Azure Blob Storage.

Timer Trigger: Every 5 minutes (cron: 0 */5 * * * *)
Expected: ~60-80 updates per window (one every 3-4 seconds from API)
"""

import azure.functions as func
import asyncio
import json
import logging
import os
import time
from datetime import datetime
from .websocket_handler import WebSocketListener


def main(mytimer: func.TimerRequest) -> None:
    """
    Azure Function: Listen to BADI Oerlikon WebSocket for ~4 minutes.

    Timer: Runs every 5 minutes
    Collection: 240 seconds (4 min) to leave buffer before next trigger
    Expected: ~60-80 occupancy updates per window (API updates every 3-4s)

    Args:
        mytimer: Timer trigger object
    """
    try:
        asyncio.run(_async_main(mytimer))
    except Exception as e:
        logging.error(f"Fatal error in timer trigger: {e}", exc_info=True)
        raise


async def _async_main(mytimer: func.TimerRequest) -> None:
    """Async implementation of the WebSocket listener.

    Collects for 240 seconds (4 minutes), then writes to blob storage.
    Leaves 1-minute buffer before the next 5-minute trigger fires.
    """
    logger = logging.getLogger("websocket_listener")
    window_start = datetime.utcnow()
    start_time = time.time()

    if mytimer.past_due:
        logger.warning("Timer is past due")

    logger.info(f"WebSocket listener started at {window_start.isoformat()}")

    try:
        websocket_url = os.getenv(
            "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
        )
        target_uid = os.getenv("TARGET_UID", "SSD-7")

        logger.info(
            f"Connecting to: {websocket_url}, "
            f"monitoring UID: {target_uid}"
        )

        # Collect for 240 seconds (4 min), leaving 1-min buffer
        listener = WebSocketListener(
            url=websocket_url, target_uid=target_uid, duration_seconds=240
        )
        updates = await listener.collect_updates()

        elapsed = time.time() - start_time
        logger.info(
            f"Collected {len(updates)} updates in {elapsed:.1f}s"
        )

        if updates:
            occupancies = [u["occupancy"] for u in updates]
            stats = {
                "count": len(updates),
                "min": min(occupancies),
                "max": max(occupancies),
                "avg": round(sum(occupancies) / len(occupancies), 1),
                "median": sorted(occupancies)[len(occupancies) // 2],
            }

            logger.info(
                f"Stats: count={stats['count']}, min={stats['min']}, "
                f"max={stats['max']}, avg={stats['avg']}, "
                f"median={stats['median']}"
            )

            # Write to blob storage
            try:
                await _write_to_blob(logger, updates, stats, window_start)
            except Exception as blob_error:
                logger.warning(f"Could not write to blob: {blob_error}")

            logger.info(f"Sample: {json.dumps(updates[:3])}")
        else:
            logger.warning("No updates received in collection window")

    except Exception as e:
        logger.error(f"Error in websocket listener: {e}", exc_info=True)
        raise


async def _write_to_blob(logger, updates, stats, window_start):
    """Write occupancy readings to blob storage as CSV with stats."""
    try:
        from azure.storage.blob import BlobServiceClient

        # Use AZURE_STORAGE_CONNECTION_STRING (real conn string)
        # Fall back to AzureWebJobsStorage only if it's a real connection string
        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not conn_str:
            aws = os.getenv("AzureWebJobsStorage", "")
            if aws and aws != "UseDevelopmentStorage=true":
                conn_str = aws

        container_name = os.getenv("BLOB_CONTAINER_NAME", "occupancy-data")

        if not conn_str:
            logger.warning(
                "No storage connection string configured, skipping blob write. "
                "Set AZURE_STORAGE_CONNECTION_STRING."
            )
            return

        # Organize by date: YYYY-MM-DD/occupancy_HH_MM.csv
        date_folder = window_start.strftime("%Y-%m-%d")
        blob_name = f"{date_folder}/{window_start.strftime('occupancy_%H_%M.csv')}"

        # Build CSV content
        csv_lines = ["timestamp,occupancy"]
        for update in updates:
            csv_lines.append(f"{update['timestamp']},{update['occupancy']}")

        # Add stats as a comment at the end
        csv_lines.append("")
        csv_lines.append(f"# stats: {json.dumps(stats)}")

        csv_content = "\n".join(csv_lines)

        # Create container if it doesn't exist, then upload
        blob_service_client = BlobServiceClient.from_connection_string(conn_str)
        container_client = blob_service_client.get_container_client(container_name)
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
        # Don't raise - don't fail entire function if blob write fails
