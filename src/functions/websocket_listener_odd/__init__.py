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
from .websocket_handler import WebSocketListener


def main(mytimer: func.TimerRequest) -> None:
    """
    Azure Function: Leap-frog WebSocket listener (ODD).

    Timer: Fires every 10 minutes at :05 seconds
    Collection: 5 minutes of continuous data
    Data: Occupancy readings to Application Insights

    Args:
        mytimer: Timer trigger object
    """
    try:
        asyncio.run(_async_main(mytimer))
    except Exception as e:
        logging.error(
            f"Fatal error in websocket_listener_odd: {e}", exc_info=True
        )
        raise


async def _async_main(mytimer: func.TimerRequest) -> None:
    """
    Async implementation: Collect 5 minutes of occupancy data.

    This function collects for the full 5-minute window, then returns
    quickly to avoid blocking the next leap-frog function. While this
    function runs 22:05-22:10, websocket_listener_even is idle.
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

        # Collect for full 5 minutes (300 seconds)
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
        else:
            logger.warning("[ODD] No updates received in 5-minute window")

    except Exception as e:
        logger.error(
            f"[ODD] Error in websocket_listener_odd: {e}", exc_info=True
        )
        raise
