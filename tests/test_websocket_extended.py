#!/usr/bin/env python3
"""
Extended WebSocket test to understand the API behavior.
Does it send continuous updates or just one message?
"""

import asyncio
import json
import websockets
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_websocket_extended():
    """Test if WebSocket sends continuous updates."""
    url = "wss://badi-public.crowdmonitor.ch:9591/api"
    
    logger.info(f"Connecting to {url}")
    async with websockets.connect(url) as websocket:
        logger.info("✅ Connected!")
        
        # Send the "all" command
        logger.info("Sending 'all' command...")
        await websocket.send("all")
        
        # Wait for messages for 30 seconds to see if there are updates
        logger.info("Listening for 30 seconds...")
        message_count = 0
        start = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start < 30:
            try:
                message = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=2.0
                )
                message_count += 1
                
                data = json.loads(message)
                if isinstance(data, list):
                    first_item = data[0]
                    logger.info(
                        f"Message {message_count}: {len(data)} items, "
                        f"first UID: {first_item.get('uid')}, "
                        f"currentfill: {first_item.get('currentfill')}"
                    )
            
            except asyncio.TimeoutError:
                logger.warning("No message for 2 seconds...")
        
        logger.info(f"Total messages received: {message_count}")


if __name__ == "__main__":
    asyncio.run(test_websocket_extended())
