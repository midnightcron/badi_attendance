#!/usr/bin/env python3
"""
Local test of the fixed Azure Function code.
This simulates a 30-second collection window to verify it works.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime

# Add to path
sys.path.insert(0, '/home/worreby/Documents/python_toy_projects/badi_oerlikon_attendence/src/functions/websocket_listener')

from websocket_handler import WebSocketListener

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_local_function")


async def test_function():
    """Test the WebSocket listener for 30 seconds."""
    logger.info("=" * 70)
    logger.info("LOCAL TEST: WebSocket Listener Function (30 sec)")
    logger.info("=" * 70)
    
    window_start = datetime.utcnow()
    start_time = time.time()
    
    try:
        target_uid = 'SSD-7'
        websocket_url = 'wss://badi-public.crowdmonitor.ch:9591/api'
        
        logger.info(f"Connecting to: {websocket_url}")
        logger.info(f"Target UID: {target_uid}")
        logger.info("Collection window: 30 seconds (production uses 300s)")
        logger.info("")
        
        # Create listener with 30 second test window
        listener = WebSocketListener(
            url=websocket_url,
            target_uid=target_uid,
            duration_seconds=30  # Test with 30 seconds
        )
        
        updates = await listener.collect_updates()
        
        elapsed = time.time() - start_time
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"✅ Collection complete!")
        logger.info(f"Collected {len(updates)} updates in {elapsed:.1f}s")
        logger.info("")
        
        if updates:
            occupancies = [u['occupancy'] for u in updates]
            logger.info(f"Occupancy values: {occupancies[:10]}...")
            logger.info(f"Min: {min(occupancies)}")
            logger.info(f"Max: {max(occupancies)}")
            logger.info(f"Avg: {sum(occupancies) / len(occupancies):.1f}")
            logger.info(f"Median: {sorted(occupancies)[len(occupancies) // 2]}")
            logger.info("")
            logger.info("Sample data that would be saved:")
            logger.info(json.dumps(updates[:2], indent=2))
        else:
            logger.error("❌ No updates received!")
        
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(test_function())
