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
        self.oerlikon_uid = "SSD-7"
        self.city_uid = "SSD-4"

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
                {"occupancy_oerlikon": int, "occupancy_city": int, "timestamp": str}  or  None
        """
        try:
            data_array = json.loads(message)

            if not isinstance(data_array, list):
                logger.warning(f"Unexpected message type: {type(data_array)}")
                return None

            occupancy_oerlikon = None
            occupancy_city = None
            timestamp = None
            for element in data_array:
                uid = element.get("uid")
                if uid == self.oerlikon_uid:
                    occupancy_oerlikon = element.get("currentfill")
                    timestamp = element.get("timestamp") or datetime.now(_TZ).isoformat()
                elif uid == self.city_uid:
                    occupancy_city = element.get("currentfill")
                    if not timestamp:
                        timestamp = element.get("timestamp") or datetime.now(_TZ).isoformat()
            if occupancy_oerlikon is None and occupancy_city is None:
                logger.warning(f"No 'currentfill' for Oerlikon ({self.oerlikon_uid}) or City ({self.city_uid})")
                return None
            return {
                "occupancy_oerlikon": int(float(occupancy_oerlikon)) if occupancy_oerlikon is not None else None,
                "occupancy_city": int(float(occupancy_city)) if occupancy_city is not None else None,
                "timestamp": timestamp or datetime.now(_TZ).isoformat(),
            }

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Message parse error: {e}")
            return None
