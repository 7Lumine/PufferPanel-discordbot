"""
Rate limiter and cooldown management for PufferPanel Discord Bot.
Prevents rapid repeated actions (Start/Stop/Restart).
"""

import asyncio
import time
from typing import Dict, Optional


class ActionLock:
    """
    Manages cooldowns for server actions.
    Prevents multiple rapid executions of the same action type.
    """
    
    def __init__(self, cooldown_sec: float = 10.0):
        self.cooldown_sec = cooldown_sec
        self._last_action: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
    
    def _get_lock(self, action: str) -> asyncio.Lock:
        """Get or create lock for an action."""
        if action not in self._locks:
            self._locks[action] = asyncio.Lock()
        return self._locks[action]
    
    async def acquire(self, action: str) -> bool:
        """
        Try to acquire lock for an action.
        Returns True if acquired, False if in cooldown.
        """
        lock = self._get_lock(action)
        
        # Try to acquire the lock (non-blocking check)
        if lock.locked():
            return False
        
        await lock.acquire()
        
        # Check cooldown
        last_time = self._last_action.get(action, 0)
        elapsed = time.time() - last_time
        
        if elapsed < self.cooldown_sec:
            lock.release()
            return False
        
        # Update last action time
        self._last_action[action] = time.time()
        return True
    
    def release(self, action: str) -> None:
        """Release lock for an action."""
        lock = self._locks.get(action)
        if lock and lock.locked():
            lock.release()
    
    def get_remaining(self, action: str) -> float:
        """Get remaining cooldown time in seconds."""
        last_time = self._last_action.get(action, 0)
        elapsed = time.time() - last_time
        remaining = self.cooldown_sec - elapsed
        return max(0, remaining)
    
    def is_locked(self, action: str) -> bool:
        """Check if an action is currently locked (in progress)."""
        lock = self._locks.get(action)
        return lock.locked() if lock else False


class GlobalActionLock:
    """
    Global lock that prevents any server action while another is in progress.
    Used to prevent Start while Stop is running, etc.
    """
    
    def __init__(self, cooldown_sec: float = 10.0):
        self.cooldown_sec = cooldown_sec
        self._lock = asyncio.Lock()
        self._last_action_time: float = 0
        self._current_action: Optional[str] = None
    
    async def acquire(self, action: str) -> tuple[bool, Optional[str]]:
        """
        Try to acquire global lock.
        Returns (success, blocking_action_name).
        """
        # Check if already locked
        if self._lock.locked():
            return False, self._current_action
        
        await self._lock.acquire()
        
        # Check cooldown
        elapsed = time.time() - self._last_action_time
        if elapsed < self.cooldown_sec:
            self._lock.release()
            return False, "cooldown"
        
        self._current_action = action
        self._last_action_time = time.time()
        return True, None
    
    def release(self) -> None:
        """Release the global lock."""
        self._current_action = None
        if self._lock.locked():
            self._lock.release()
    
    def get_remaining_cooldown(self) -> float:
        """Get remaining cooldown time."""
        elapsed = time.time() - self._last_action_time
        return max(0, self.cooldown_sec - elapsed)
    
    @property
    def current_action(self) -> Optional[str]:
        """Get the currently running action, if any."""
        return self._current_action if self._lock.locked() else None


# Global instance
_global_lock: Optional[GlobalActionLock] = None


def init_action_lock(cooldown_sec: float) -> GlobalActionLock:
    """Initialize the global action lock."""
    global _global_lock
    _global_lock = GlobalActionLock(cooldown_sec)
    return _global_lock


def get_action_lock() -> GlobalActionLock:
    """Get the global action lock."""
    if _global_lock is None:
        raise RuntimeError("ActionLock not initialized. Call init_action_lock() first.")
    return _global_lock
