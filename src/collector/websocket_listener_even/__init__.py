"""Azure Function: Leap-frog WebSocket listener (EVEN intervals).

Schedule: 0 0,10,20,30,40,50 * * * * (every 10 min at :00)
useMonitor disabled to prevent catch-up cascade.
Shared logic lives in utils/websocket_collector.py.
"""

import azure.functions as func
from utils.websocket_collector import run_collection


def main(mytimer: func.TimerRequest) -> None:
    run_collection("even", mytimer)
