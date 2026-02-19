"""Minimal test version - find where it fails."""

import azure.functions as func
import asyncio
import logging
from datetime import datetime


def main(mytimer: func.TimerRequest) -> None:
    """Minimal test function."""
    logger = logging.getLogger("minimal_test")
    logger.info("[TEST] main() called")
    
    try:
        logger.info("[TEST] About to call asyncio.run()")
        asyncio.run(_async_main(mytimer))
        logger.info("[TEST] asyncio.run() completed")
    except Exception as e:
        logger.error(f"[TEST] Error in main: {e}", exc_info=True)
        raise


async def _async_main(mytimer: func.TimerRequest) -> None:
    """Minimal async function."""
    logger = logging.getLogger("minimal_test")
    logger.info("[TEST] _async_main() started")
    
    try:
        logger.info("[TEST] Creating datetime")
        window_start = datetime.utcnow()
        logger.info(f"[TEST] Window start: {window_start.isoformat()}")
        
        logger.info("[TEST] Checking mytimer")
        if mytimer.past_due:
            logger.warning("[TEST] Timer is past due")
        logger.info("[TEST] Timer check complete")
        
        logger.info("[TEST] _async_main() completed successfully")
    except Exception as e:
        logger.error(f"[TEST] Error in _async_main: {e}", exc_info=True)
        raise
