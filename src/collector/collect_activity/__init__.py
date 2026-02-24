"""Durable Functions activity: run one ~296 s WebSocket collection cycle."""

import logging

from utils.websocket_collector import run_collection

logger = logging.getLogger("collect_activity")


def main(input: str) -> str:
    """Activity function — performs a single data-collection cycle.

    The orchestrator calls this every 5 minutes.  The activity connects
    to CrowdMonitor, collects occupancy readings for ~296 s, writes a
    CSV to blob storage, and returns a JSON status summary.
    """
    import json

    logger.info("Activity started")
    result = run_collection()
    logger.info(f"Activity finished: {result}")
    return json.dumps(result)
