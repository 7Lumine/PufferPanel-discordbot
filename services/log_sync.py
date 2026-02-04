"""
Log synchronization service for PufferPanel Discord Bot.
Manages log streaming, thread creation, and batch posting to Discord.
"""

import asyncio
from datetime import datetime
from typing import List, Optional

import discord
import pytz

from services.websocket_client import get_websocket_client, init_websocket_client
from utils.config import get_config
from utils.state import get_state_manager


class LogSyncService:
    """
    Manages log synchronization from PufferPanel to Discord.
    
    Features:
    - Creates daily private threads for logs
    - Invites allowed role members to threads
    - Batches log messages for rate limit compliance
    - Handles date change for new thread creation
    """
    
    def __init__(self, bot: discord.Bot):
        self._bot = bot
        self._config = get_config()
        self._state = get_state_manager()
        self._running = False
        self._log_buffer: List[str] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._current_thread: Optional[discord.Thread] = None
        self._current_date: Optional[str] = None
        self._tz = pytz.timezone(self._config.logs.timezone)
    
    @property
    def is_running(self) -> bool:
        """Check if log sync is running."""
        return self._running
    
    def _get_current_date(self) -> str:
        """Get current date in configured timezone (YYYY-MM-DD)."""
        now = datetime.now(self._tz)
        return now.strftime("%Y-%m-%d")
    
    def _get_thread_name(self, date: str) -> str:
        """Generate thread name from date."""
        return self._config.logs.thread.name_format.format(date=date)
    
    async def start(self) -> bool:
        """
        Start log synchronization.
        Creates/resumes thread and starts WebSocket connection.
        """
        if self._running:
            return True
        
        try:
            # Get current date
            self._current_date = self._get_current_date()
            
            # Check if we need to resume existing thread or create new one
            state = self._state.state
            if state.current_thread_id and state.current_date == self._current_date:
                # Try to resume existing thread
                thread = await self._get_thread(state.current_thread_id)
                if thread:
                    self._current_thread = thread
                else:
                    # Thread no longer exists, create new
                    self._current_thread = await self._create_daily_thread()
            else:
                # Create new thread for today
                self._current_thread = await self._create_daily_thread()
            
            if not self._current_thread:
                return False
            
            # Start WebSocket log streaming
            ws_client = init_websocket_client()
            ws_client.on_log(self._on_log_received)
            await ws_client.start()
            
            # Start flush task
            self._running = True
            self._flush_task = asyncio.create_task(self._flush_loop())
            
            # Update state
            self._state.update_logs(
                enabled=True,
                thread_id=self._current_thread.id,
                date=self._current_date,
            )
            
            print(f"LogSync: Started - Thread: {self._current_thread.name}")
            return True
            
        except Exception as e:
            print(f"LogSync: Failed to start: {e}")
            return False
    
    async def stop(self) -> None:
        """Stop log synchronization."""
        self._running = False
        
        # Stop flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        
        # Flush remaining logs
        await self._flush_buffer()
        
        # Stop WebSocket
        try:
            ws_client = get_websocket_client()
            await ws_client.disconnect()
        except RuntimeError:
            pass  # Not initialized
        
        # Update state
        self._state.update_logs(enabled=False)
        
        print("LogSync: Stopped")
    
    async def _get_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """Get existing thread by ID."""
        try:
            guild = self._bot.get_guild(self._config.discord.guild_id)
            if not guild:
                return None
            
            thread = guild.get_thread(thread_id)
            if thread:
                return thread
            
            # Thread might not be in cache, try to fetch
            try:
                thread = await guild.fetch_channel(thread_id)
                return thread if isinstance(thread, discord.Thread) else None
            except discord.NotFound:
                return None
                
        except Exception as e:
            print(f"LogSync: Error getting thread: {e}")
            return None
    
    async def _create_daily_thread(self) -> Optional[discord.Thread]:
        """Create a new private thread for today's logs."""
        try:
            guild = self._bot.get_guild(self._config.discord.guild_id)
            if not guild:
                print("LogSync: Guild not found")
                return None
            
            channel = guild.get_channel(self._config.discord.log_parent_channel_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                print("LogSync: Log parent channel not found")
                return None
            
            thread_name = self._get_thread_name(self._current_date)
            
            # Create public thread (channel permissions control access)
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.public_thread,
                auto_archive_duration=self._config.logs.thread.auto_archive_minutes,
            )
            
            print(f"LogSync: Created thread: {thread_name}")
            
            # No need to invite members - public thread inherits channel permissions
            
            return thread
            
        except discord.Forbidden:
            print("LogSync: Missing permissions to create thread")
            return None
        except Exception as e:
            print(f"LogSync: Error creating thread: {e}")
            return None
    
    async def _invite_members(self, thread: discord.Thread) -> None:
        """Invite all members with allowed role to the thread."""
        try:
            guild = self._bot.get_guild(self._config.discord.guild_id)
            if not guild:
                return
            
            role = guild.get_role(self._config.discord.allowed_role_id)
            if not role:
                print("LogSync: Allowed role not found")
                return
            
            invited = 0
            for member in role.members:
                try:
                    await thread.add_user(member)
                    invited += 1
                    # Rate limit: 1 second between invites
                    await asyncio.sleep(1)
                except discord.Forbidden:
                    print(f"LogSync: Cannot invite {member.name}")
                except Exception as e:
                    print(f"LogSync: Error inviting {member.name}: {e}")
            
            print(f"LogSync: Invited {invited} members to thread")
            
        except Exception as e:
            print(f"LogSync: Error inviting members: {e}")
    
    def _on_log_received(self, log_line: str) -> None:
        """Callback when log line is received from WebSocket."""
        # Skip empty lines
        if not log_line or not log_line.strip():
            return
        # Add to buffer (synchronously called from WebSocket handler)
        asyncio.create_task(self._add_to_buffer(log_line))
    
    async def _add_to_buffer(self, log_line: str) -> None:
        """Add log line to buffer."""
        # Debug: print first 100 chars of what we're buffering
        # print(f"LogSync: Buffering: {log_line[:100]}...")
        async with self._buffer_lock:
            self._log_buffer.append(log_line)
    
    async def _flush_loop(self) -> None:
        """Periodically flush log buffer to Discord."""
        while self._running:
            try:
                await asyncio.sleep(self._config.logs.batch_seconds)
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"LogSync: Flush error: {e}")
    
    async def _flush_buffer(self) -> None:
        """Flush buffered logs to Discord thread."""
        async with self._buffer_lock:
            if not self._log_buffer:
                return
            
            logs = self._log_buffer.copy()
            self._log_buffer.clear()
        
        if not self._current_thread:
            return
        
        # Check for date change
        current_date = self._get_current_date()
        if current_date != self._current_date:
            self._current_date = current_date
            self._current_thread = await self._create_daily_thread()
            if not self._current_thread:
                return
            
            # Update state with new thread
            self._state.update_logs(
                enabled=True,
                thread_id=self._current_thread.id,
                date=self._current_date,
            )
        
        # Combine logs and split by max chars
        combined = "\n".join(logs)
        chunks = self._split_message(combined)
        
        for chunk in chunks:
            try:
                await self._current_thread.send(f"```\n{chunk}\n```")
            except discord.Forbidden:
                print("LogSync: Cannot send to thread - missing permissions")
                break
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    retry_after = getattr(e, "retry_after", 5)
                    print(f"LogSync: Rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    try:
                        await self._current_thread.send(f"```\n{chunk}\n```")
                    except Exception:
                        pass
                else:
                    print(f"LogSync: HTTP error: {e}")
    
    def _split_message(self, text: str) -> List[str]:
        """Split text into chunks respecting max chars per post."""
        max_len = self._config.logs.max_chars_per_post - 10  # Reserve for code block markers
        
        if len(text) <= max_len:
            return [text] if text else []
        
        chunks = []
        lines = text.split("\n")
        current_chunk = ""
        
        for line in lines:
            if len(current_chunk) + len(line) + 1 > max_len:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                if current_chunk:
                    current_chunk += "\n" + line
                else:
                    current_chunk = line
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    async def get_thread_info(self) -> Optional[str]:
        """Get current thread info for dashboard display."""
        if not self._running or not self._current_thread:
            return None
        
        return f"#{self._current_thread.name}"


# Global instance
_log_sync: Optional[LogSyncService] = None


def init_log_sync(bot: discord.Bot) -> LogSyncService:
    """Initialize the global log sync service."""
    global _log_sync
    _log_sync = LogSyncService(bot)
    return _log_sync


def get_log_sync() -> LogSyncService:
    """Get the global log sync service."""
    if _log_sync is None:
        raise RuntimeError("LogSyncService not initialized. Call init_log_sync() first.")
    return _log_sync
