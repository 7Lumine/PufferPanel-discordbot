"""
Persistent state management for PufferPanel Discord Bot.
Stores dashboard message ID, log thread info, etc.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class BotState:
    """Bot persistent state."""
    # Dashboard
    dashboard_message_id: Optional[int] = None
    
    # Log sync
    logs_enabled: bool = False
    current_thread_id: Optional[int] = None
    current_date: Optional[str] = None  # YYYY-MM-DD format
    
    # Last action
    last_action_time: Optional[str] = None  # ISO format
    last_action_user: Optional[str] = None
    last_action_type: Optional[str] = None  # start, stop, restart


class StateManager:
    """
    Manages persistent state stored in a JSON file.
    Thread-safe for single-process use.
    """
    
    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self._state: Optional[BotState] = None
    
    def load(self) -> BotState:
        """Load state from file. Creates default if not exists."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._state = BotState(**data)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Warning: Failed to load state file, using defaults: {e}")
                self._state = BotState()
        else:
            self._state = BotState()
        
        return self._state
    
    def save(self) -> None:
        """Save current state to file."""
        if self._state is None:
            return
        
        # Ensure directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(asdict(self._state), f, indent=2, ensure_ascii=False)
    
    @property
    def state(self) -> BotState:
        """Get current state. Loads if not yet loaded."""
        if self._state is None:
            self.load()
        return self._state
    
    def update_dashboard(self, message_id: int) -> None:
        """Update dashboard message ID."""
        self.state.dashboard_message_id = message_id
        self.save()
    
    def update_logs(
        self,
        enabled: bool,
        thread_id: Optional[int] = None,
        date: Optional[str] = None,
    ) -> None:
        """Update log sync state."""
        self.state.logs_enabled = enabled
        if thread_id is not None:
            self.state.current_thread_id = thread_id
        if date is not None:
            self.state.current_date = date
        self.save()
    
    def update_last_action(
        self,
        action_type: str,
        user: str,
    ) -> None:
        """Update last action info."""
        self.state.last_action_time = datetime.now().isoformat()
        self.state.last_action_type = action_type
        self.state.last_action_user = user
        self.save()
    
    def clear_logs(self) -> None:
        """Clear log sync state (on logs off)."""
        self.state.logs_enabled = False
        self.state.current_thread_id = None
        self.state.current_date = None
        self.save()


# Global instance
_state_manager: Optional[StateManager] = None


def init_state_manager(state_file: str) -> StateManager:
    """Initialize the global state manager."""
    global _state_manager
    _state_manager = StateManager(state_file)
    _state_manager.load()
    return _state_manager


def get_state_manager() -> StateManager:
    """Get the global state manager."""
    if _state_manager is None:
        raise RuntimeError("StateManager not initialized. Call init_state_manager() first.")
    return _state_manager
