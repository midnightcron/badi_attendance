#!/usr/bin/env python3
"""
Local WebSocket test to verify API response format before deployment.
This will help us understand what data the CrowdMonitor API actually sends.
"""

import asyncio
import json
import websockets
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_websocket():
    """Connect to CrowdMonitor WebSocket and capture raw message."""
    url = "wss://badi-public.crowdmonitor.ch:9591/api"
    target_uid = "SSD-7"
    
    try:
        logger.info(f"Connecting to {url}")
        async with websockets.connect(url) as websocket:
            logger.info("✅ Connected!")
            
            # Send the "all" command
            logger.info("Sending 'all' command...")
            await websocket.send("all")
            
            # Receive first few messages
            for i in range(3):
                logger.info(f"\n--- Waiting for message {i+1} ---")
                try:
                    message = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=3.0
                    )
                    
                    logger.info(f"Raw message ({len(message)} chars): {message[:200]}")
                    
                    # Try to parse
                    data = json.loads(message)
                    logger.info(f"Parsed type: {type(data)}")
                    
                    if isinstance(data, list):
                        logger.info(f"Message is a list with {len(data)} items")
                        # Find our target
                        for item in data:
                            if isinstance(item, dict) and item.get("uid") == target_uid:
                                logger.info(f"✅ Found {target_uid}:")
                                logger.info(json.dumps(item, indent=2))
                                break
                        else:
                            logger.info(f"❌ {target_uid} not found in list")
                            logger.info(f"Available UIDs: {[item.get('uid') for item in data if isinstance(item, dict)]}")
                    
                    elif isinstance(data, dict):
                        logger.info(f"Message is a dict: {json.dumps(data, indent=2)}")
                    
                    else:
                        logger.info(f"Message is: {data}")
                
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for message")
                    break
                
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    break
    
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(test_websocket())
