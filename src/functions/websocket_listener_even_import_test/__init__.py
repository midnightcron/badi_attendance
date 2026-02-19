"""
Test: Check if critical imports succeed in Azure Functions environment.
"""

import azure.functions as func  
import logging
from datetime import datetime

def main(mytimer: func.TimerRequest) -> None:
    """Test function - verify imports work."""
    
    logger = logging.getLogger("websocket_listener_even_test")
    logger.info("[TEST] Starting import verification")
    
    try:
        logger.info("[TEST] Importing asyncio...")
        import asyncio
        logger.info("[TEST] ✓ asyncio imported")
        
        logger.info("[TEST] Importing websockets...")
        import websockets
        logger.info("[TEST] ✓ websockets imported")
        
        logger.info("[TEST] Importing json...")
        import json
        logger.info("[TEST] ✓ json imported")
        
        logger.info("[TEST] Importing websocket_handler...")
        from .websocket_handler import WebSocketListener
        logger.info("[TEST] ✓ websocket_handler imported")
        
        logger.info("[TEST] Importing blob client...")
        try:
            from azure.storage.blob import BlobClient
            logger.info("[TEST] ✓ BlobClient imported")
        except ImportError as e:
            logger.warning(f"[TEST] BlobClient import failed: {e}")
        
        logger.info("[TEST] All imports completed successfully at " + datetime.utcnow().isoformat())
        
    except Exception as e:
        logger.error(
            f"[TEST] Import failed: {e}", exc_info=True
        )
        raise
