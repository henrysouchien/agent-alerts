from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import AlertLevel

log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSIONS = {1, 2}
KNOWN_ROUTING_KEYS = {level.value for level in AlertLevel} | {"by_category"}


@dataclass
class AlertConfig:
    schema_version: int
    on_config_error: str
    channels: dict[str, dict[str, Any]]
    routing: dict[str, Any]
    quiet_hours: dict[str, Any]
    rate_limits: dict[str, Any]
    thresholds: dict[str, dict[str, Any]]
    _loaded_at: float = 0.0
    _file_mtime: float = 0.0


def _require_env(name: str, env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    value = str(source.get(name, "")).strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def get_telegram_config(env: Mapping[str, str] | None = None) -> tuple[str, str]:
    return _require_env("TELEGRAM_BOT_TOKEN", env), _require_env("TELEGRAM_CHAT_ID", env)


def get_imessage_target(env: Mapping[str, str] | None = None) -> str:
    return _require_env("IMESSAGE_TARGET", env)


def _load_dotenv(env_path: str | Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    path = Path(env_path) if env_path is not None else Path(".env")
    if not path.is_file():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            env[key] = value
    return env


class AlertConfigLoader:
    def __init__(self, config_path: str | Path):
        self._config_path = Path(config_path)
        self._config: AlertConfig | None = None

    def load(self) -> AlertConfig | None:
        if not self._config_path.is_file():
            return None

        try:
            mtime = self._config_path.stat().st_mtime
        except OSError:
            return self._config

        if self._config and mtime == self._config._file_mtime:
            return self._config

        try:
            raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError("Alerting config must be a mapping")
            version = raw.get("schema_version", 1)
            if version not in SUPPORTED_SCHEMA_VERSIONS:
                log.error("Unsupported alerting config schema_version: %s", version)
                return self._apply_error_policy(raw)
            self._config = AlertConfig(
                schema_version=int(version),
                on_config_error=str(raw.get("on_config_error", "use_last_good")),
                channels={
                    str(name): dict(value)
                    for name, value in dict(raw.get("channels", {})).items()
                    if isinstance(value, dict)
                },
                routing=dict(raw.get("routing", {})),
                quiet_hours=dict(raw.get("quiet_hours", {})),
                rate_limits=dict(raw.get("rate_limits", {})),
                thresholds={
                    str(name): dict(value)
                    for name, value in dict(raw.get("thresholds", {})).items()
                    if isinstance(value, dict)
                },
                _loaded_at=time.time(),
                _file_mtime=mtime,
            )
            self._validate_config(self._config)
        except Exception:
            log.warning("Failed to load alerting config", exc_info=True)
            return self._apply_error_policy(None)

        return self._config

    def get_channel_config(self, channel: str) -> dict[str, Any] | None:
        config = self.load()
        if config is None:
            return None
        channel_config = config.channels.get(channel)
        return channel_config if isinstance(channel_config, dict) else None

    def _apply_error_policy(self, raw: dict[str, Any] | None) -> AlertConfig | None:
        policy = "use_last_good"
        if raw and isinstance(raw, dict):
            policy = str(raw.get("on_config_error", "use_last_good"))
        elif self._config:
            policy = self._config.on_config_error

        if policy == "use_last_good" and self._config:
            log.warning("Config error: using last good config (loaded at %s)", self._config._loaded_at)
            return self._config
        if policy == "fail_open":
            log.warning("Config error: fail_open - falling back to legacy telegram behavior")
            return None
        if policy == "fail_closed":
            log.warning("Config error: fail_closed - suppressing all alerts")
            return AlertConfig(
                schema_version=1,
                on_config_error="fail_closed",
                channels={},
                routing={},
                quiet_hours={},
                rate_limits={},
                thresholds={"_default": {"min_passed_count": 999999}},
            )
        return None

    def _validate_config(self, config: AlertConfig) -> None:
        for level in config.routing:
            if level not in KNOWN_ROUTING_KEYS:
                log.warning("Routing references unknown level: '%s'", level)

        for channel in self._iter_routed_channels(config.routing):
            if channel not in config.channels:
                log.warning("Routing references undefined channel: '%s'", channel)

        quiet_hours = config.quiet_hours
        if not quiet_hours.get("enabled"):
            return
        from .quiet_hours import is_valid_time_string

        for field_name in ("start", "end"):
            value = str(quiet_hours.get(field_name, ""))
            if not is_valid_time_string(value):
                log.warning("quiet_hours.%s is not a valid HH:MM time: '%s'", field_name, value)
        per_channel = quiet_hours.get("per_channel", {})
        if not isinstance(per_channel, dict):
            return
        for channel, overrides in per_channel.items():
            if channel not in config.channels:
                log.warning("quiet_hours.per_channel references undefined channel: '%s'", channel)
            if not isinstance(overrides, dict):
                continue
            for field_name in ("start", "end"):
                if field_name not in overrides:
                    continue
                value = str(overrides.get(field_name, ""))
                if not is_valid_time_string(value):
                    log.warning(
                        "quiet_hours.per_channel.%s.%s is not a valid HH:MM time: '%s'",
                        channel,
                        field_name,
                        value,
                    )

    def _iter_routed_channels(self, routing: dict[str, Any]) -> list[str]:
        channels: list[str] = []
        for key, value in routing.items():
            if key == "by_category":
                if not isinstance(value, dict):
                    continue
                for category_levels in value.values():
                    if not isinstance(category_levels, dict):
                        continue
                    for channel_list in category_levels.values():
                        if isinstance(channel_list, list):
                            channels.extend(str(channel) for channel in channel_list)
                continue
            if isinstance(value, list):
                channels.extend(str(channel) for channel in value)
        return channels
