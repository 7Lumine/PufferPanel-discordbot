"""
PufferPanel Discord Bot - Entry Point

A Discord bot for managing PufferPanel Minecraft servers.
Provides buttons for Start/Stop/Restart and real-time log streaming.
"""

import asyncio
import os
import sys

import discord
from discord.ext import commands

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cogs.dashboard import DashboardView, update_dashboard
from services.pufferpanel import init_pufferpanel_client, get_pufferpanel_client
from services.log_sync import init_log_sync, get_log_sync
from utils.config import load_config, get_config
from utils.state import init_state_manager, get_state_manager
from utils.rate_limiter import init_action_lock


class PufferPanelBot(discord.Bot):
    """Custom bot class with setup and cleanup."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._config = None
        self._bot_initialized = False
    
    async def on_ready(self):
        """Called when the bot is ready."""
        if self._bot_initialized:
            return
        self._bot_initialized = True
        
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")
        
        config = get_config()
        
        # Register persistent view
        self.add_view(DashboardView())
        print("Registered persistent DashboardView")
        
        # Initialize PufferPanel client
        try:
            await init_pufferpanel_client()
            print("PufferPanel client initialized")
        except Exception as e:
            print(f"Warning: PufferPanel client initialization failed: {e}")
        
        # Initialize log sync service
        init_log_sync(self)
        print("LogSync service initialized")
        
        # Auto-resume log sync if enabled
        state = get_state_manager()
        if config.logs.auto_resume and state.state.logs_enabled:
            print("Auto-resuming log sync...")
            try:
                log_sync = get_log_sync()
                await log_sync.start()
                print("Log sync resumed")
            except Exception as e:
                print(f"Warning: Failed to resume log sync: {e}")
        
        # Update dashboard if exists
        if state.state.dashboard_message_id:
            try:
                await update_dashboard(self)
                print("Dashboard updated")
            except Exception as e:
                print(f"Warning: Failed to update dashboard: {e}")
        
        print("Bot is ready!")
    
    async def close(self):
        """Cleanup on shutdown."""
        print("Shutting down...")
        
        # Stop log sync
        try:
            log_sync = get_log_sync()
            if log_sync.is_running:
                await log_sync.stop()
        except RuntimeError:
            pass
        
        # Close PufferPanel client
        try:
            client = get_pufferpanel_client()
            await client.close()
        except RuntimeError:
            pass
        
        await super().close()


def main():
    """Main entry point."""
    # Load configuration
    try:
        config = load_config()
        print("Configuration loaded")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("\nPlease create config.yml based on config.example.yml")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading configuration: {e}")
        sys.exit(1)
    
    # Initialize state manager
    init_state_manager(config.state_file)
    print(f"State manager initialized (file: {config.state_file})")
    
    # Initialize action lock
    init_action_lock(config.actions.cooldown_sec)
    print(f"Action lock initialized (cooldown: {config.actions.cooldown_sec}s)")
    
    # Create bot
    intents = discord.Intents.default()
    intents.members = True  # Required for thread member invitations
    intents.message_content = True
    
    bot = PufferPanelBot(
        intents=intents,
        debug_guilds=[config.discord.guild_id],  # For faster command sync during dev
    )
    
    # Load cogs
    bot.load_extension("cogs.dashboard")
    print("Dashboard cog loaded")
    
    # Run bot
    print("Starting bot...")
    bot.run(config.discord.token)


if __name__ == "__main__":
    main()
