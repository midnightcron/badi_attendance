"""
Debug version: Minimal timer function to test invocation.
No async, no complex operations - just logging.
"""

import azure.functions as func
import logging
from datetime import datetime

def main(mytimer: func.TimerRequest) -> None:
    """Minimal debug function - just log and return."""
    
    # Use built-in logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("websocket_listener_even_debug")
    
    logger.info("[EVEN-DEBUG] Function invoked at " + datetime.utcnow().isoformat())
    
    if mytimer.past_due:
        logger.warning("[EVEN-DEBUG] Timer is past due")
    
    logger.info("[EVEN-DEBUG] Function completing successfully")
