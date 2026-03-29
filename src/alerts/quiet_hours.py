from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def is_valid_time_string(value: str) -> bool:
    if ":" not in value:
        return False
    try:
        hours_str, minutes_str = value.split(":", 1)
        hours = int(hours_str)
        minutes = int(minutes_str)
    except ValueError:
        return False
    return 0 <= hours <= 23 and 0 <= minutes <= 59


def in_quiet_hours(
    quiet_config: dict[str, Any],
    *,
    channel: str | None = None,
    now: datetime | None = None,
) -> bool:
    try:
        effective_config = quiet_config
        per_channel = quiet_config.get("per_channel", {})
        if channel and isinstance(per_channel, dict):
            channel_override = per_channel.get(channel)
            if isinstance(channel_override, dict):
                enabled = channel_override.get("enabled", quiet_config.get("enabled", False))
                if enabled is False:
                    return False
                effective_config = {**quiet_config, **channel_override}
        elif not quiet_config.get("enabled", False):
            return False

        if not effective_config.get("enabled", False):
            return False

        timezone_name = str(effective_config.get("timezone", "")).strip()
        if now is None:
            current = datetime.now(ZoneInfo(timezone_name)) if timezone_name else datetime.now()
        elif timezone_name:
            zone = ZoneInfo(timezone_name)
            current = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
        else:
            current = now

        start_h, start_m = map(int, str(effective_config["start"]).split(":"))
        end_h, end_m = map(int, str(effective_config["end"]).split(":"))
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m
        now_minutes = current.hour * 60 + current.minute

        if start_minutes <= end_minutes:
            return start_minutes <= now_minutes < end_minutes
        return now_minutes >= start_minutes or now_minutes < end_minutes
    except Exception:
        return False
