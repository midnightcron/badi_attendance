"""Azure Function: Leap-frog WebSocket listener (ODD intervals).

Schedule: 0 5,15,25,35,45,55 * * * * (every 10 min at :05)
useMonitor disabled to prevent catch-up cascade.
Shared logic lives in utils/websocket_collector.py.
"""

import azure.functions as func
from utils.websocket_collector import run_collection


def main(mytimer: func.TimerRequest) -> None:
    run_collection("odd", mytimer)
