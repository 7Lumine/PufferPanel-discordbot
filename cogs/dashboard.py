"""
Dashboard Cog for PufferPanel Discord Bot.
Provides persistent buttons for server control and log management.
"""

import asyncio
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands

from services.pufferpanel import ServerStatus, get_pufferpanel_client
from services.log_sync import get_log_sync, init_log_sync
from utils.config import get_config
from utils.rate_limiter import get_action_lock
from utils.state import get_state_manager


class DashboardView(discord.ui.View):
    """
    Persistent view for the dashboard buttons.
    Uses fixed custom_ids so buttons work after bot restart.
    """
    
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view
        self._config = get_config()
    
    def _has_permission(self, interaction: discord.Interaction) -> bool:
        """Check if user has the allowed role."""
        if not interaction.user or not hasattr(interaction.user, "roles"):
            return False
        
        allowed_role_id = self._config.discord.allowed_role_id
        return any(role.id == allowed_role_id for role in interaction.user.roles)
    
    async def _permission_check(self, interaction: discord.Interaction) -> bool:
        """Check permission and send error if not allowed."""
        if not self._has_permission(interaction):
            await interaction.response.send_message(
                "🚫 このボタンを使用する権限がありません。",
                ephemeral=True,
            )
            return False
        return True
    
    @discord.ui.button(
        label="▶️ Start",
        style=discord.ButtonStyle.success,
        custom_id="pp:start",
        row=0,
    )
    async def start_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Start the server."""
        if not await self._permission_check(interaction):
            return
        
        lock = get_action_lock()
        success, blocking = await lock.acquire("server_action")
        
        if not success:
            if blocking == "cooldown":
                remaining = lock.get_remaining_cooldown()
                await interaction.response.send_message(
                    f"⏳ クールダウン中です。あと {remaining:.0f} 秒お待ちください。",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"⏳ 別の操作 ({blocking}) が実行中です。",
                    ephemeral=True,
                )
            return
        
        try:
            await interaction.response.defer(ephemeral=True)
            
            client = get_pufferpanel_client()
            result = await client.start_server()
            
            if result:
                # Update state
                state = get_state_manager()
                state.update_last_action("start", interaction.user.display_name)
                
                await interaction.followup.send("✅ サーバーを起動しました。", ephemeral=True)
                
                # Update dashboard
                await update_dashboard(interaction.client)
            else:
                await interaction.followup.send("❌ サーバーの起動に失敗しました。", ephemeral=True)
                
        finally:
            lock.release()
    
    @discord.ui.button(
        label="⏹️ Stop",
        style=discord.ButtonStyle.danger,
        custom_id="pp:stop",
        row=0,
    )
    async def stop_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Stop the server."""
        if not await self._permission_check(interaction):
            return
        
        lock = get_action_lock()
        success, blocking = await lock.acquire("server_action")
        
        if not success:
            if blocking == "cooldown":
                remaining = lock.get_remaining_cooldown()
                await interaction.response.send_message(
                    f"⏳ クールダウン中です。あと {remaining:.0f} 秒お待ちください。",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"⏳ 別の操作 ({blocking}) が実行中です。",
                    ephemeral=True,
                )
            return
        
        try:
            await interaction.response.defer(ephemeral=True)
            
            client = get_pufferpanel_client()
            result = await client.stop_server()
            
            if result:
                state = get_state_manager()
                state.update_last_action("stop", interaction.user.display_name)
                
                await interaction.followup.send("✅ サーバーを停止しました。", ephemeral=True)
                await update_dashboard(interaction.client)
            else:
                await interaction.followup.send("❌ サーバーの停止に失敗しました。", ephemeral=True)
                
        finally:
            lock.release()
    
    @discord.ui.button(
        label="🔄 Restart",
        style=discord.ButtonStyle.primary,
        custom_id="pp:restart",
        row=0,
    )
    async def restart_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Restart the server (stop then start)."""
        if not await self._permission_check(interaction):
            return
        
        lock = get_action_lock()
        success, blocking = await lock.acquire("server_action")
        
        if not success:
            if blocking == "cooldown":
                remaining = lock.get_remaining_cooldown()
                await interaction.response.send_message(
                    f"⏳ クールダウン中です。あと {remaining:.0f} 秒お待ちください。",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"⏳ 別の操作 ({blocking}) が実行中です。",
                    ephemeral=True,
                )
            return
        
        try:
            await interaction.response.defer(ephemeral=True)
            
            client = get_pufferpanel_client()
            config = get_config()
            
            # Stop server
            stop_result = await client.stop_server()
            if not stop_result:
                await interaction.followup.send("❌ サーバーの停止に失敗しました。", ephemeral=True)
                return
            
            # Wait for server to stop
            await asyncio.sleep(config.actions.restart.stop_timeout_sec)
            
            # Start server
            start_result = await client.start_server()
            if not start_result:
                await interaction.followup.send(
                    "⚠️ サーバーを停止しましたが、起動に失敗しました。",
                    ephemeral=True,
                )
                return
            
            state = get_state_manager()
            state.update_last_action("restart", interaction.user.display_name)
            
            await interaction.followup.send("✅ サーバーを再起動しました。", ephemeral=True)
            await update_dashboard(interaction.client)
            
        finally:
            lock.release()
    
    @discord.ui.button(
        label="🔃 Refresh",
        style=discord.ButtonStyle.secondary,
        custom_id="pp:refresh",
        row=0,
    )
    async def refresh_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Refresh dashboard status."""
        if not await self._permission_check(interaction):
            return
        
        await interaction.response.defer(ephemeral=True)
        await update_dashboard(interaction.client)
        await interaction.followup.send("✅ ダッシュボードを更新しました。", ephemeral=True)
    
    @discord.ui.button(
        label="📋 Logs ON",
        style=discord.ButtonStyle.success,
        custom_id="pp:logs_on",
        row=1,
    )
    async def logs_on_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Start log synchronization."""
        if not await self._permission_check(interaction):
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            log_sync = get_log_sync()
        except RuntimeError:
            log_sync = init_log_sync(interaction.client)
        
        if log_sync.is_running:
            await interaction.followup.send("ℹ️ ログ同期は既に有効です。", ephemeral=True)
            return
        
        result = await log_sync.start()
        if result:
            await interaction.followup.send("✅ ログ同期を開始しました。", ephemeral=True)
            await update_dashboard(interaction.client)
        else:
            await interaction.followup.send("❌ ログ同期の開始に失敗しました。", ephemeral=True)
    
    @discord.ui.button(
        label="📋 Logs OFF",
        style=discord.ButtonStyle.secondary,
        custom_id="pp:logs_off",
        row=1,
    )
    async def logs_off_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Stop log synchronization."""
        if not await self._permission_check(interaction):
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            log_sync = get_log_sync()
            if not log_sync.is_running:
                await interaction.followup.send("ℹ️ ログ同期は既に無効です。", ephemeral=True)
                return
            
            await log_sync.stop()
            await interaction.followup.send("✅ ログ同期を停止しました。", ephemeral=True)
            await update_dashboard(interaction.client)
        except RuntimeError:
            await interaction.followup.send("ℹ️ ログ同期は既に無効です。", ephemeral=True)


async def update_dashboard(bot: discord.Bot) -> bool:
    """Update the dashboard message with current status."""
    config = get_config()
    state = get_state_manager()
    
    if not state.state.dashboard_message_id:
        return False
    
    try:
        guild = bot.get_guild(config.discord.guild_id)
        if not guild:
            return False
        
        channel = guild.get_channel(config.discord.dashboard_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return False
        
        message = await channel.fetch_message(state.state.dashboard_message_id)
        
        # Get current status
        client = get_pufferpanel_client()
        status = await client.get_server_status()
        
        # Build status display
        status_emoji = "🟢" if status == ServerStatus.RUNNING else "🔴"
        status_text = "Running" if status == ServerStatus.RUNNING else "Stopped"
        
        # Log sync status
        try:
            log_sync = get_log_sync()
            logs_running = log_sync.is_running
            thread_info = await log_sync.get_thread_info()
        except RuntimeError:
            logs_running = False
            thread_info = None
        
        logs_emoji = "🟢" if logs_running else "🔴"
        logs_text = "ON" if logs_running else "OFF"
        if thread_info:
            logs_text = f"ON ({thread_info})"
        
        # Last action
        last_action = "なし"
        if state.state.last_action_type and state.state.last_action_time:
            try:
                dt = datetime.fromisoformat(state.state.last_action_time)
                time_str = dt.strftime("%Y-%m-%d %H:%M")
                last_action = f"{state.state.last_action_type.capitalize()} by {state.state.last_action_user} ({time_str})"
            except Exception:
                pass
        
        # Build embed
        embed = discord.Embed(
            title="🖥️ Minecraft Server Dashboard",
            color=discord.Color.green() if status == ServerStatus.RUNNING else discord.Color.red(),
        )
        embed.add_field(
            name="📊 Status",
            value=f"{status_emoji} {status_text}",
            inline=True,
        )
        embed.add_field(
            name="📋 Log Sync",
            value=f"{logs_emoji} {logs_text}",
            inline=True,
        )
        embed.add_field(
            name="🕐 Last Action",
            value=last_action,
            inline=False,
        )
        embed.set_footer(text=f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        await message.edit(embed=embed, view=DashboardView())
        return True
        
    except discord.NotFound:
        print("Dashboard: Message not found")
        return False
    except Exception as e:
        print(f"Dashboard: Update failed: {e}")
        return False


class Dashboard(commands.Cog):
    """Dashboard Cog for slash commands."""
    
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self._config = get_config()
    
    @commands.slash_command(
        name="setup",
        description="ダッシュボードメッセージを作成します",
    )
    async def setup_dashboard(self, ctx: discord.ApplicationContext):
        """Create the dashboard message."""
        # Check permission
        allowed_role_id = self._config.discord.allowed_role_id
        if not any(role.id == allowed_role_id for role in ctx.author.roles):
            await ctx.respond("🚫 このコマンドを使用する権限がありません。", ephemeral=True)
            return
        
        # Check if in correct channel
        if ctx.channel_id != self._config.discord.dashboard_channel_id:
            await ctx.respond(
                f"⚠️ ダッシュボードは指定されたチャンネルでのみ作成できます。",
                ephemeral=True,
            )
            return
        
        await ctx.defer(ephemeral=True)
        
        # Get current status
        client = get_pufferpanel_client()
        status = await client.get_server_status()
        
        status_emoji = "🟢" if status == ServerStatus.RUNNING else "🔴"
        status_text = "Running" if status == ServerStatus.RUNNING else "Stopped"
        
        # Build initial embed
        embed = discord.Embed(
            title="🖥️ Minecraft Server Dashboard",
            color=discord.Color.green() if status == ServerStatus.RUNNING else discord.Color.red(),
        )
        embed.add_field(
            name="📊 Status",
            value=f"{status_emoji} {status_text}",
            inline=True,
        )
        embed.add_field(
            name="📋 Log Sync",
            value="🔴 OFF",
            inline=True,
        )
        embed.add_field(
            name="🕐 Last Action",
            value="なし",
            inline=False,
        )
        embed.set_footer(text=f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Send dashboard message
        message = await ctx.channel.send(embed=embed, view=DashboardView())
        
        # Save message ID
        state = get_state_manager()
        state.update_dashboard(message.id)
        
        await ctx.followup.send(
            f"✅ ダッシュボードを作成しました (Message ID: {message.id})",
            ephemeral=True,
        )
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages in log thread to execute as server commands."""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Check if message is in a thread
        if not isinstance(message.channel, discord.Thread):
            return
        
        # Check if this is the current log thread
        state = get_state_manager()
        if not state.state.current_thread_id:
            return
        
        if message.channel.id != state.state.current_thread_id:
            return
        
        # Check if log sync is enabled
        if not state.state.logs_enabled:
            return
        
        # Check if user has allowed role
        allowed_role_id = self._config.discord.allowed_role_id
        if not hasattr(message.author, "roles"):
            return
        
        if not any(role.id == allowed_role_id for role in message.author.roles):
            return
        
        # Get command from message content
        command = message.content.strip()
        if not command:
            return
        
        # Send command to server
        try:
            client = get_pufferpanel_client()
            success = await client.send_command(command)
            
            if success:
                # React with checkmark to indicate command was sent
                await message.add_reaction("✅")
            else:
                await message.add_reaction("❌")
                
        except Exception as e:
            print(f"Command execution failed: {e}")
            await message.add_reaction("⚠️")


def setup(bot: discord.Bot):
    """Setup function for the cog."""
    bot.add_cog(Dashboard(bot))
