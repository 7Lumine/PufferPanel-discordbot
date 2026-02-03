"""
Configuration loader for PufferPanel Discord Bot.
Loads settings from config.yml with validation.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class OAuth2Config:
    client_id: str
    client_secret: str
    token_endpoint: str = "/oauth2/token"


@dataclass
class PufferPanelConfig:
    base_url: str
    server_id: str
    oauth2: OAuth2Config

    def __post_init__(self):
        # Remove trailing slash from base_url
        self.base_url = self.base_url.rstrip("/")


@dataclass
class DiscordConfig:
    token: str
    guild_id: int
    dashboard_channel_id: int
    log_parent_channel_id: int
    allowed_role_id: int


@dataclass
class ThreadConfig:
    auto_archive_minutes: int = 1440
    name_format: str = "mc-log-{date}"


@dataclass
class LogsConfig:
    auto_resume: bool = False
    timezone: str = "Asia/Tokyo"
    thread: ThreadConfig = field(default_factory=ThreadConfig)
    batch_seconds: int = 5
    max_chars_per_post: int = 1900


@dataclass
class RestartConfig:
    stop_timeout_sec: int = 30
    start_timeout_sec: int = 30


@dataclass
class ActionsConfig:
    cooldown_sec: int = 10
    restart: RestartConfig = field(default_factory=RestartConfig)


@dataclass
class Config:
    pufferpanel: PufferPanelConfig
    discord: DiscordConfig
    logs: LogsConfig = field(default_factory=LogsConfig)
    actions: ActionsConfig = field(default_factory=ActionsConfig)
    state_file: str = "./data/state.json"

    @classmethod
    def load(cls, config_path: str = "config.yml") -> "Config":
        """Load configuration from YAML file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}\n"
                "Please copy config.example.yml to config.yml and fill in your values."
            )

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary."""
        # Parse PufferPanel config
        pp_data = data.get("pufferpanel", {})
        oauth2_data = pp_data.get("oauth2", {})
        oauth2 = OAuth2Config(
            client_id=oauth2_data.get("client_id", ""),
            client_secret=oauth2_data.get("client_secret", ""),
            token_endpoint=oauth2_data.get("token_endpoint", "/oauth2/token"),
        )
        pufferpanel = PufferPanelConfig(
            base_url=pp_data.get("base_url", ""),
            server_id=pp_data.get("server_id", ""),
            oauth2=oauth2,
        )

        # Parse Discord config
        dc_data = data.get("discord", {})
        discord = DiscordConfig(
            token=dc_data.get("token", ""),
            guild_id=int(dc_data.get("guild_id", 0)),
            dashboard_channel_id=int(dc_data.get("dashboard_channel_id", 0)),
            log_parent_channel_id=int(dc_data.get("log_parent_channel_id", 0)),
            allowed_role_id=int(dc_data.get("allowed_role_id", 0)),
        )

        # Parse Logs config
        logs_data = data.get("logs", {})
        thread_data = logs_data.get("thread", {})
        thread = ThreadConfig(
            auto_archive_minutes=thread_data.get("auto_archive_minutes", 1440),
            name_format=thread_data.get("name_format", "mc-log-{date}"),
        )
        logs = LogsConfig(
            auto_resume=logs_data.get("auto_resume", False),
            timezone=logs_data.get("timezone", "Asia/Tokyo"),
            thread=thread,
            batch_seconds=logs_data.get("batch_seconds", 5),
            max_chars_per_post=logs_data.get("max_chars_per_post", 1900),
        )

        # Parse Actions config
        actions_data = data.get("actions", {})
        restart_data = actions_data.get("restart", {})
        restart = RestartConfig(
            stop_timeout_sec=restart_data.get("stop_timeout_sec", 30),
            start_timeout_sec=restart_data.get("start_timeout_sec", 30),
        )
        actions = ActionsConfig(
            cooldown_sec=actions_data.get("cooldown_sec", 10),
            restart=restart,
        )

        return cls(
            pufferpanel=pufferpanel,
            discord=discord,
            logs=logs,
            actions=actions,
            state_file=data.get("state_file", "./data/state.json"),
        )


# Global config instance (set after load)
_config: Optional[Config] = None


def load_config(config_path: str = "config.yml") -> Config:
    """Load and cache configuration."""
    global _config
    _config = Config.load(config_path)
    return _config


def get_config() -> Config:
    """Get cached configuration. Raises if not loaded."""
    if _config is None:
        raise RuntimeError("Configuration not loaded. Call load_config() first.")
    return _config
