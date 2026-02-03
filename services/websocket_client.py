"""
WebSocket client for PufferPanel console log streaming.
Receives real-time server logs via WebSocket connection.
"""

import asyncio
import json
import ssl
from typing import Callable, Optional
from urllib.parse import urlparse

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from services.pufferpanel import get_pufferpanel_client
from utils.config import get_config


class WebSocketLogClient:
    """
    WebSocket client for receiving real-time console logs from PufferPanel.
    Handles authentication, reconnection, and log message parsing.
    """
    
    def __init__(self):
        self._config = get_config().pufferpanel
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._log_callback: Optional[Callable[[str], None]] = None
        self._connected = False
        
        # Reconnection settings
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
    
    def on_log(self, callback: Callable[[str], None]) -> None:
        """Set callback for log messages."""
        self._log_callback = callback
    
    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._connected
    
    def _get_websocket_url(self, token: str) -> str:
        """Build WebSocket URL from PufferPanel config with token."""
        base = self._config.base_url
        parsed = urlparse(base)
        
        # Convert http(s) to ws(s)
        if parsed.scheme == "https":
            ws_scheme = "wss"
        else:
            ws_scheme = "ws"
        
        # PufferPanel 2.x expects token as query parameter
        return f"{ws_scheme}://{parsed.netloc}/proxy/daemon/socket/{self._config.server_id}?token={token}"
    
    async def connect(self) -> bool:
        """
        Connect to WebSocket and authenticate.
        Returns True if successful.
        """
        client = get_pufferpanel_client()
        token = client.access_token
        
        if not token:
            # Try to get a fresh token
            await client.authenticate()
            token = client.access_token
        
        if not token:
            print("WebSocket: No valid token available")
            return False
        
        url = self._get_websocket_url(token)
        
        try:
            # Create SSL context for wss connections
            ssl_context = None
            if url.startswith("wss"):
                ssl_context = ssl.create_default_context()
            
            # Add Authorization header as backup
            extra_headers = {
                "Authorization": f"Bearer {token}",
            }
            
            self._websocket = await websockets.connect(
                url,
                ssl=ssl_context,
                ping_interval=30,
                ping_timeout=10,
                additional_headers=extra_headers,
            )
            
            # PufferPanel 2.x authenticates via URL token, wait for ready message
            try:
                response_raw = await asyncio.wait_for(
                    self._websocket.recv(),
                    timeout=10.0,
                )
                response = json.loads(response_raw)
                
                if response.get("type") == "error":
                    print(f"WebSocket auth failed: {response.get('message', 'Unknown error')}")
                    await self._websocket.close()
                    return False
                
                # Log initial message type for debugging
                print(f"WebSocket: Initial message type: {response.get('type', 'unknown')}")
                
            except asyncio.TimeoutError:
                # No initial message might be okay - connection established
                print("WebSocket: No initial message (may be normal)")
            except json.JSONDecodeError:
                # Non-JSON response might be a log line
                print("WebSocket: Received non-JSON initial message")
            
            self._connected = True
            print(f"WebSocket: Connected to server {self._config.server_id}")
            return True
            
        except asyncio.TimeoutError:
            print("WebSocket: Connection timeout")
            return False
        except WebSocketException as e:
            print(f"WebSocket: Connection failed: {e}")
            return False
        except Exception as e:
            print(f"WebSocket: Unexpected error: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        self._running = False
        self._connected = False
        
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None
        
        print("WebSocket: Disconnected")
    
    async def start(self) -> bool:
        """Start WebSocket connection and message handling."""
        self._running = True
        self._reconnect_delay = 1.0
        
        success = await self.connect()
        if success:
            self._receive_task = asyncio.create_task(self._receive_loop())
        else:
            # Start reconnection loop
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        
        return success
    
    async def _receive_loop(self) -> None:
        """Receive and process messages from WebSocket."""
        while self._running and self._websocket:
            try:
                message_raw = await self._websocket.recv()
                await self._process_message(message_raw)
                
            except ConnectionClosed:
                print("WebSocket: Connection closed")
                self._connected = False
                if self._running:
                    self._reconnect_task = asyncio.create_task(self._reconnect_loop())
                break
                
            except Exception as e:
                print(f"WebSocket: Receive error: {e}")
                if self._running:
                    await asyncio.sleep(1)
    
    async def _process_message(self, message_raw: str) -> None:
        """Process a received WebSocket message."""
        try:
            message = json.loads(message_raw)
            msg_type = message.get("type", "")
            
            if msg_type == "console":
                # Log message from console
                data = message.get("data", "")
                log_line = self._extract_log_line(data)
                if log_line and self._log_callback:
                    self._log_callback(log_line)
            
            elif msg_type == "logs":
                # Batch of log messages (alternative format)
                logs = message.get("logs", message.get("data", []))
                if isinstance(logs, list):
                    for entry in logs:
                        log_line = self._extract_log_line(entry)
                        if log_line and self._log_callback:
                            self._log_callback(log_line)
                    
            elif msg_type == "status":
                # Server status update
                pass  # Could add status callback if needed
                
            elif msg_type == "error":
                print(f"WebSocket: Server error: {message.get('message', '')}")
                
        except json.JSONDecodeError:
            # Non-JSON message (might be raw log)
            if self._log_callback:
                self._log_callback(message_raw)
    
    def _extract_log_line(self, data) -> str:
        """Extract log line from various data formats."""
        if isinstance(data, str):
            return data
        elif isinstance(data, dict):
            # Try common field names for log content
            for key in ("message", "msg", "log", "line", "text", "data"):
                if key in data and isinstance(data[key], str):
                    return data[key]
            # Fallback: convert dict to string
            return json.dumps(data)
        elif data is None:
            return ""
        else:
            return str(data)
    
    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        while self._running and not self._connected:
            print(f"WebSocket: Reconnecting in {self._reconnect_delay:.1f}s...")
            await asyncio.sleep(self._reconnect_delay)
            
            if not self._running:
                break
            
            success = await self.connect()
            if success:
                self._reconnect_delay = 1.0
                self._receive_task = asyncio.create_task(self._receive_loop())
                break
            else:
                # Exponential backoff
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay,
                )


# Global instance
_ws_client: Optional[WebSocketLogClient] = None


def init_websocket_client() -> WebSocketLogClient:
    """Initialize the global WebSocket client."""
    global _ws_client
    _ws_client = WebSocketLogClient()
    return _ws_client


def get_websocket_client() -> WebSocketLogClient:
    """Get the global WebSocket client."""
    if _ws_client is None:
        raise RuntimeError("WebSocketLogClient not initialized. Call init_websocket_client() first.")
    return _ws_client
