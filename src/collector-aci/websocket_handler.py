"""
WebSocket client for CrowdMonitor occupancy API.

Provides a thin async context-manager wrapper around websockets.connect()
and a message parser that extracts occupancy for a given target UID.
"""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import websockets

_TZ = ZoneInfo("Europe/Zurich")
logger = logging.getLogger(__name__)


class WebSocketClient:
    """Manages connection and message parsing for CrowdMonitor WebSocket."""

    def __init__(self, url: str, target_uid: str) -> None:
        self.url = url
        self.target_uid = target_uid

    @asynccontextmanager
    async def connect(self):
        """
        Async context manager that yields a connected WebSocket.

        Sends the initial "all" command and handles clean close.
        """
        ws = await websockets.connect(
            self.url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        )
        try:
            await ws.send("all")
            logger.debug("Sent 'all' command to WebSocket")
            yield ws
        finally:
            try:
                await ws.close()
            except Exception as e:
                logger.debug(f"WebSocket close: {e}")

    def parse_message(self, message: str) -> dict | None:
        """
        Parse a CrowdMonitor WebSocket message.

        Expected format — JSON array:
            [
                {"uid": "SSD-7", "currentfill": 45, ...},
                {"uid": "SSD-3", "currentfill": 12, ...},
                ...
            ]

        Returns:
            {"occupancy": int, "timestamp": str}  or  None
        """
        try:
            data_array = json.loads(message)

            if not isinstance(data_array, list):
                logger.warning(f"Unexpected message type: {type(data_array)}")
                return None

            for element in data_array:
                if element.get("uid") == self.target_uid:
                    occupancy = element.get("currentfill")
                    if occupancy is None:
                        logger.warning(
                            f"No 'currentfill' for {self.target_uid}"
                        )
                        return None
                    return {
                        "occupancy": int(float(occupancy)),
                        "timestamp": datetime.now(_TZ).isoformat(),
                    }

            # Target UID not in this message (e.g. a heartbeat/refresh)
            return None

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Message parse error: {e}")
            return None
