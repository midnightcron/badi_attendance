"""
Azure Function: Listen to BADI Oerlikon WebSocket for occupancy data.

This function connects to the CrowdMonitor WebSocket API and collects
occupancy readings for 5 minutes, then logs to Application Insights.

Timer Trigger: Every 5 minutes (cron: 0 */5 * * * *)
Expected: ~40-80 updates per window (one every 3-4 seconds from API)
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
    Azure Function: Listen to BADI Oerlikon WebSocket for 5 minutes.

    Timer: Runs every 5 minutes
    Expected: ~40-80 occupancy updates per window (API updates every 3-4s)

    Args:
        mytimer: Timer trigger object
    """
    # Run async function in event loop
    asyncio.run(_async_main(mytimer))


async def _async_main(mytimer: func.TimerRequest) -> None:
    """Async implementation of the WebSocket listener."""
    logger = logging.getLogger("websocket_listener")
    window_start = datetime.utcnow()
    start_time = time.time()

    if mytimer.past_due:
        logger.warning("Timer is past due")

    logger.info(f"WebSocket listener started at {window_start.isoformat()}")

    try:
        # Get configuration from environment variables
        websocket_url = os.getenv(
            "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
        )
        target_uid = os.getenv("TARGET_UID", "SSD-7")

        logger.info(f"Connecting to: {websocket_url}, " f"monitoring UID: {target_uid}")

        # Listen to WebSocket for exactly 5 minutes
        listener = WebSocketListener(
            url=websocket_url, target_uid=target_uid, duration_seconds=300
        )
        updates = await listener.collect_updates()

        elapsed = time.time() - start_time
        logger.info(
            f"Collected {len(updates)} updates in 5-minute window "
            f"(actual time: {elapsed:.1f}s)"
        )

        if updates:
            # Calculate statistics
            occupancies = [u["occupancy"] for u in updates]
            stats = {
                "count": len(updates),
                "min": min(occupancies),
                "max": max(occupancies),
                "avg": sum(occupancies) / len(occupancies),
                "median": sorted(occupancies)[len(occupancies) // 2],
            }

            # Log statistics to Application Insights
            logger.info(f"Collected {len(updates)} updates in 5-minute window")
            logger.info(
                f"Stats: count={stats['count']}, min={stats['min']}, "
                f"max={stats['max']}, avg={stats['avg']:.1f}, "
                f"median={stats['median']}"
            )
            
            # Log all updates
            logger.info(f"Updates: {json.dumps(updates[:5])}...")  # First 5
        else:
            logger.warning("No updates received in 5-minute window")

    except Exception as e:
        logger.error(f"Error in websocket listener: {e}", exc_info=True)
        raise
