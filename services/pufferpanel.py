"""
PufferPanel API client for Discord Bot.
Handles OAuth2 authentication and server operations.
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiohttp

from utils.config import get_config


class ServerStatus(Enum):
    """Server status from PufferPanel."""
    OFFLINE = "offline"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    UNKNOWN = "unknown"


@dataclass
class TokenInfo:
    """OAuth2 token information."""
    access_token: str
    expires_at: float  # Unix timestamp
    token_type: str = "Bearer"
    
    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 60s margin)."""
        return time.time() >= (self.expires_at - 60)


class PufferPanelError(Exception):
    """Base exception for PufferPanel API errors."""
    pass


class AuthenticationError(PufferPanelError):
    """Authentication failed."""
    pass


class APIError(PufferPanelError):
    """API request failed."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class PufferPanelClient:
    """
    PufferPanel API client with OAuth2 authentication.
    Uses /proxy/daemon/... endpoints for PufferPanel 2.x.
    """
    
    def __init__(self):
        self._config = get_config().pufferpanel
        self._token: Optional[TokenInfo] = None
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def start(self) -> None:
        """Initialize the client and authenticate."""
        self._session = aiohttp.ClientSession()
        await self.authenticate()
    
    async def close(self) -> None:
        """Close the client session."""
        if self._session:
            await self._session.close()
            self._session = None
    
    async def authenticate(self) -> None:
        """
        Authenticate with PufferPanel using OAuth2 client_credentials.
        """
        if self._session is None:
            self._session = aiohttp.ClientSession()
        
        url = f"{self._config.base_url}{self._config.oauth2.token_endpoint}"
        
        data = {
            "grant_type": "client_credentials",
            "client_id": self._config.oauth2.client_id,
            "client_secret": self._config.oauth2.client_secret,
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        
        try:
            async with self._session.post(url, data=data, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise AuthenticationError(
                        f"OAuth2 authentication failed: {resp.status} - {text}"
                    )
                
                result = await resp.json()
                
                expires_in = result.get("expires_in", 3600)
                self._token = TokenInfo(
                    access_token=result["access_token"],
                    expires_at=time.time() + expires_in,
                    token_type=result.get("token_type", "Bearer"),
                )
        except aiohttp.ClientError as e:
            raise AuthenticationError(f"Failed to connect to PufferPanel: {e}")
    
    async def _ensure_token(self) -> str:
        """Ensure we have a valid token, refreshing if needed."""
        if self._token is None or self._token.is_expired:
            await self.authenticate()
        return self._token.access_token
    
    def _get_headers(self) -> dict:
        """Get headers with authorization."""
        if self._token is None:
            raise AuthenticationError("Not authenticated")
        return {
            "Authorization": f"{self._token.token_type} {self._token.access_token}",
            "Content-Type": "application/json",
        }
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> Optional[dict]:
        """
        Make an authenticated API request.
        Automatically refreshes token on 401.
        """
        await self._ensure_token()
        
        url = f"{self._config.base_url}{endpoint}"
        headers = self._get_headers()
        
        async with self._session.request(method, url, headers=headers, **kwargs) as resp:
            # Handle 401 - token expired
            if resp.status == 401:
                await self.authenticate()
                headers = self._get_headers()
                async with self._session.request(method, url, headers=headers, **kwargs) as retry_resp:
                    if retry_resp.status >= 400:
                        text = await retry_resp.text()
                        raise APIError(f"API request failed: {text}", retry_resp.status)
                    return await self._parse_response(retry_resp)
            
            if resp.status >= 400:
                text = await resp.text()
                raise APIError(f"API request failed: {text}", resp.status)
            
            return await self._parse_response(resp)
    
    async def _parse_response(self, resp: aiohttp.ClientResponse) -> Optional[dict]:
        """Parse response, handling empty bodies."""
        # 202 Accepted, 204 No Content - no body expected
        if resp.status in (202, 204):
            return None
        
        # Check if there's content
        content_length = resp.headers.get("Content-Length", "0")
        if content_length == "0":
            return None
        
        # Check content type
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            # Not JSON, return None
            return None
        
        try:
            return await resp.json()
        except Exception:
            return None
    
    async def get_server_status(self) -> ServerStatus:
        """Get current server status."""
        try:
            result = await self._request(
                "GET",
                f"/proxy/daemon/server/{self._config.server_id}/status",
            )
            
            if result is None:
                return ServerStatus.UNKNOWN
            
            running = result.get("running", False)
            return ServerStatus.RUNNING if running else ServerStatus.OFFLINE
            
        except APIError:
            return ServerStatus.UNKNOWN
    
    async def start_server(self) -> bool:
        """
        Start the server.
        Returns True if successful.
        """
        try:
            await self._request(
                "POST",
                f"/proxy/daemon/server/{self._config.server_id}/start",
            )
            return True
        except APIError as e:
            print(f"Failed to start server: {e}")
            return False
    
    async def stop_server(self) -> bool:
        """
        Stop the server.
        Returns True if successful.
        """
        try:
            await self._request(
                "POST",
                f"/proxy/daemon/server/{self._config.server_id}/stop",
            )
            return True
        except APIError as e:
            print(f"Failed to stop server: {e}")
            return False
    
    async def get_server_stats(self) -> Optional[dict]:
        """Get server statistics (CPU, memory, etc.)."""
        try:
            return await self._request(
                "GET",
                f"/proxy/daemon/server/{self._config.server_id}/stats",
            )
        except APIError:
            return None
    
    async def send_command(self, command: str) -> bool:
        """
        Send a console command to the server.
        Returns True if successful.
        """
        try:
            await self._request(
                "POST",
                f"/proxy/daemon/server/{self._config.server_id}/console",
                data=command,  # PufferPanel expects raw command string
            )
            return True
        except APIError as e:
            print(f"Failed to send command: {e}")
            return False
    
    @property
    def base_url(self) -> str:
        """Get base URL for WebSocket connection."""
        return self._config.base_url
    
    @property
    def server_id(self) -> str:
        """Get server ID."""
        return self._config.server_id
    
    @property
    def access_token(self) -> Optional[str]:
        """Get current access token (if valid)."""
        if self._token and not self._token.is_expired:
            return self._token.access_token
        return None


# Global instance
_client: Optional[PufferPanelClient] = None


async def init_pufferpanel_client() -> PufferPanelClient:
    """Initialize the global PufferPanel client."""
    global _client
    _client = PufferPanelClient()
    await _client.start()
    return _client


def get_pufferpanel_client() -> PufferPanelClient:
    """Get the global PufferPanel client."""
    if _client is None:
        raise RuntimeError("PufferPanelClient not initialized. Call init_pufferpanel_client() first.")
    return _client
