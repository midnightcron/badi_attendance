"""
WebSocket handler for BADI Oerlikon occupancy monitoring.

Connects to CrowdMonitor WebSocket API and collects occupancy updates.
"""

import asyncio
import json
import logging
import websockets
from datetime import datetime


class WebSocketListener:
    """Connects to CrowdMonitor WebSocket and collects occupancy updates."""
    
    def __init__(self, url, target_uid, duration_seconds=300,
                 timeout_per_message=1.0):
        """
        Initialize WebSocket listener.
        
        Args:
            url: WebSocket URL (wss://badi-public.crowdmonitor.ch:9591/api)
            target_uid: UID to monitor (e.g., 'SSD-7' for BADI Oerlikon)
            duration_seconds: How long to listen (default 5 min)
            timeout_per_message: Max wait for each message (default 1 sec)
        """
        self.url = url
        self.target_uid = target_uid
        self.duration_seconds = duration_seconds
        self.timeout_per_message = timeout_per_message
        self.logger = logging.getLogger(__name__)
    
    async def collect_updates(self):
        """
        Connect to WebSocket and collect updates for duration.
        
        Flow:
        1. Connect to WebSocket
        2. Send "all" command (as expected by API)
        3. Receive JSON array of occupancy data (API sends every 3-4 sec)
        4. Extract target UID data
        5. Continue collecting for 5 minutes
        
        Note: API updates every ~3-4 seconds, not on demand.
        In a 5-minute window (~300 sec), expect 75-100 messages.
        
        Returns:
            List of {'occupancy': int, 'timestamp': str} dicts
        """
        updates = []
        start_time = datetime.utcnow()
        
        try:
            async with websockets.connect(self.url) as websocket:
                self.logger.info(f"Connected to WebSocket: {self.url}")
                
                # Send the "all" command (API expects this)
                await websocket.send("all")
                self.logger.info("Sent 'all' command to WebSocket")
                
                while True:
                    elapsed = (datetime.utcnow() - start_time).total_seconds()
                    
                    if elapsed >= self.duration_seconds:
                        self.logger.info(
                            f"5-minute window complete. "
                            f"Collected {len(updates)} updates."
                        )
                        break
                    
                    try:
                        # Wait for next message (with timeout)
                        message = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=self.timeout_per_message
                        )
                        
                        # Parse message and extract target UID
                        data = self._parse_message(message)
                        
                        if data:
                            updates.append(data)
                            self.logger.debug(
                                f"Update {len(updates)}: "
                                f"occupancy={data['occupancy']} "
                                f"at {data['timestamp']}"
                            )
                        
                    except asyncio.TimeoutError:
                        # No message in timeout period, keep listening
                        continue
                        
                    except json.JSONDecodeError:
                        self.logger.warning(
                            f"Failed to parse message: {message[:100]}"
                        )
                        continue
                        
                    except Exception as e:
                        self.logger.warning(f"Error processing message: {e}")
                        continue
        
        except asyncio.TimeoutError:
            self.logger.error("WebSocket connection timeout")
            raise
        except ConnectionRefusedError:
            self.logger.error(f"Failed to connect to {self.url}")
            raise
        except Exception as e:
            self.logger.error(f"WebSocket error: {e}")
            raise
        
        return updates
    
    def _parse_message(self, message):
        """
        Parse WebSocket message and extract occupancy for target UID.
        
        Message format from CrowdMonitor API:
        [
            {
                "uid": "SSD-7",
                "name": "Badi Oerlikon",
                "currentfill": 45,
                "capacity": 100,
                "timestamp": "2026-02-17T10:00:00Z"
            },
            ... (other locations)
        ]
        
        Args:
            message: Raw WebSocket message (JSON string)
        
        Returns:
            {'occupancy': int, 'timestamp': str} or None if not our UID
        """
        try:
            data_array = json.loads(message)
            
            # Data is an array; find the matching UID
            if not isinstance(data_array, list):
                self.logger.warning(
                    f"Unexpected message format: {type(data_array)}"
                )
                return None
            
            for element in data_array:
                if element.get("uid") == self.target_uid:
                    # Found our target location
                    occupancy = element.get("currentfill")
                    
                    if occupancy is None:
                        self.logger.warning(
                            f"No 'currentfill' for {self.target_uid}: "
                            f"{element}"
                        )
                        return None
                    
                    return {
                        'occupancy': int(float(occupancy)),
                        'timestamp': datetime.utcnow().isoformat()
                    }
            
            # Target UID not found in this message (not an error,
            # might be a refresh message)
            return None
            
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            self.logger.warning(f"Error parsing message: {e}")
            return None
