"""
WebSocket client for CrowdMonitor occupancy API.

Identical to collector-aci/websocket_handler.py except the parsed dict
carries a datetime `ts` key instead of a raw ISO string, which asyncpg
can bind directly to TIMESTAMPTZ.
"""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import websockets

_TZ = ZoneInfo("Europe/Zurich")
logger = logging.getLogger(__name__)

_OERLIKON_UID = "SSD-7"
_CITY_UID = "SSD-4"


class WebSocketClient:
    def __init__(self, url: str) -> None:
        self.url = url

    @asynccontextmanager
    async def connect(self):
        ws = await websockets.connect(
            self.url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        )
        try:
            await ws.send("all")
            yield ws
        finally:
            try:
                await ws.close()
            except Exception as e:
                logger.debug(f"WebSocket close: {e}")

    def parse_message(self, message: str) -> dict | None:
        """
        Parse a CrowdMonitor message into a reading dict.

        Returns:
            {"ts": datetime, "occupancy_oerlikon": int|None, "occupancy_city": int|None}
            or None if neither location was found.
        """
        try:
            data_array = json.loads(message)
            if not isinstance(data_array, list):
                return None

            oerlikon = None
            city = None
            raw_ts = None

            for element in data_array:
                uid = element.get("uid")
                if uid == _OERLIKON_UID:
                    oerlikon = element.get("currentfill")
                    raw_ts = element.get("timestamp") or raw_ts
                elif uid == _CITY_UID:
                    city = element.get("currentfill")
                    raw_ts = raw_ts or element.get("timestamp")

            if oerlikon is None and city is None:
                return None

            if raw_ts:
                try:
                    ts = datetime.fromisoformat(raw_ts)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=_TZ)
                except ValueError:
                    ts = datetime.now(_TZ)
            else:
                ts = datetime.now(_TZ)

            return {
                "ts": ts,
                "occupancy_oerlikon": int(float(oerlikon)) if oerlikon is not None else None,
                "occupancy_city": int(float(city)) if city is not None else None,
            }

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Message parse error: {e}")
            return None
