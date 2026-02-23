"""
Quick connectivity test for the CrowdMonitor WebSocket API.

Connects, sends "all", and prints the current occupancy for SSD-7.
Requires: pip install websocket-client

Usage:
    python tests/test_websocket_connectivity.py
"""
import json
from websocket import create_connection, WebSocketTimeoutException

WS_URL = "wss://badi-public.crowdmonitor.ch:9591/api"
TARGET_UID = "SSD-7"  # uid used in the page for the site


def fetch_once(timeout=5):
    ws = create_connection(WS_URL, timeout=timeout)
    try:
        # server expects the string "all" (page JS sends this after open)
        ws.send("all")
        msg = ws.recv()  # JSON array
        data = json.loads(msg)
        # data is an array of objects; find the matching uid
        for element in data:
            if element.get("uid") == TARGET_UID:
                # currentfill is the visitor count
                occupied = element.get("currentfill")
                print(int(float(occupied)))  # prints e.g. 70
                return int(float(occupied))
        print("UID not found in message")
        return None
    finally:
        ws.close()


if __name__ == "__main__":
    try:
        fetch_once()
    except WebSocketTimeoutException:
        print("WebSocket timeout")
