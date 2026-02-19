"""Test WebSocket listener via HTTP endpoint."""

import azure.functions as func
import asyncio
import json
import logging
import os
from datetime import datetime
from websocket_listener.websocket_handler import WebSocketListener


async def run_collection():
    """Run WebSocket collection for 30 seconds (test)."""
    logger = logging.getLogger("websocket_test")
    window_start = datetime.utcnow()

    logger.info(
        f"Test WebSocket collection started at {window_start.isoformat()}"
    )

    try:
        # Get configuration from environment variables
        websocket_url = os.getenv(
            "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
        )
        target_uid = os.getenv("TARGET_UID", "SSD-7")

        logger.info(
            f"Connecting to: {websocket_url}, "
            f"monitoring UID: {target_uid}"
        )

        # Listen for 30 seconds (test, not 5min production)
        listener = WebSocketListener(
            url=websocket_url,
            target_uid=target_uid,
            duration_seconds=30
        )
        updates = await listener.collect_updates()

        logger.info(f"Collected {len(updates)} updates")

        if updates:
            occupancies = [u["occupancy"] for u in updates]
            stats = {
                "count": len(updates),
                "min": min(occupancies),
                "max": max(occupancies),
                "avg": sum(occupancies) / len(occupancies),
                "median": sorted(occupancies)[len(occupancies) // 2],
            }

            result = {
                "status": "success",
                "collected": len(updates),
                "stats": stats,
                "sample_updates": updates[:3]
            }
        else:
            result = {
                "status": "success",
                "collected": 0,
                "stats": None,
                "sample_updates": []
            }

        logger.info(f"Test result: {json.dumps(result)}")
        return result

    except Exception as e:
        logger.error(f"Error in websocket test: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP endpoint for testing WebSocket listener."""
    try:
        result = asyncio.run(run_collection())
        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"status": "error", "error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
