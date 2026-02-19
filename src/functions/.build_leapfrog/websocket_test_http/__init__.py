"""Test WebSocket listener via HTTP to diagnose issues."""

import azure.functions as func
import asyncio
import json
import logging
import os
from websocket_listener.websocket_handler import WebSocketListener


async def run_collection():
    """Run WebSocket collection for diagnostics."""
    logger = logging.getLogger("websocket_test")
    logger.info("Test function starting")

    try:
        # Get configuration
        websocket_url = os.getenv(
            "WEBSOCKET_URL", "wss://badi-public.crowdmonitor.ch:9591/api"
        )
        target_uid = os.getenv("TARGET_UID", "SSD-7")

        logger.info(
            f"Connecting to WebSocket: {websocket_url}, "
            f"UID: {target_uid}"
        )

        # Create listener for 30 seconds (test)
        listener = WebSocketListener(
            url=websocket_url,
            target_uid=target_uid,
            duration_seconds=30
        )

        logger.info("Starting collection...")
        updates = await listener.collect_updates()
        logger.info(f"Collection complete: {len(updates)} updates")

        if updates:
            occupancies = [u["occupancy"] for u in updates]
            stats = {
                "count": len(updates),
                "min": min(occupancies),
                "max": max(occupancies),
                "avg": sum(occupancies) / len(occupancies),
                "median": sorted(occupancies)[len(occupancies) // 2],
            }
            return {
                "status": "success",
                "stats": stats,
                "sample": updates[:3]
            }
        else:
            return {
                "status": "success",
                "message": "No updates received"
            }

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
        }


def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP endpoint for testing."""
    try:
        result = asyncio.run(run_collection())
        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "status": "fatal_error",
                "error": str(e),
                "type": type(e).__name__
            }),
            status_code=500,
            mimetype="application/json"
        )
