from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .channels.email import send_email
from .channels.imessage import send_imessage
from .channels.telegram import send_telegram
from .config import _load_dotenv, get_imessage_target, get_telegram_config
from .evaluator import AlertDecision, AlertEvaluator
from .models import Alert, AlertCategory, AlertLevel, AlertResult, coerce_alert_category, coerce_alert_level
from .router import AlertRouter, DEFAULT_CONFIG_PATH


def send(message: str, channel: str = "telegram", **kwargs) -> dict | bool:
    env = _resolve_env(kwargs.pop("env", None), kwargs.pop("env_file", None))

    if channel == "telegram":
        token = kwargs.pop("token", None)
        chat_id = kwargs.pop("chat_id", None)
        if not token or not chat_id:
            env_token, env_chat_id = get_telegram_config(env)
            token = token or env_token
            chat_id = chat_id or env_chat_id
        return send_telegram(message, token, chat_id, **kwargs)

    if channel == "imessage":
        target = kwargs.pop("target", None) or get_imessage_target(env)
        service = kwargs.pop("service", "imessage")
        backend = kwargs.pop("backend", None)
        return send_imessage(message, target, service=service, backend=backend)

    if channel == "email":
        channel_config = kwargs.pop("channel_config", None)
        return send_email(message, channel_config=channel_config, env=env)

    raise ValueError(f"Unknown channel: {channel}")


def send_alert(
    alert: Alert,
    *,
    router: AlertRouter | None = None,
    config_path: str | Path | None = None,
    env_file: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    agent_dispatch_fn: Callable[[str, str, Any, Mapping[str, str] | None, dict[str, str]], None] | None = None,
) -> AlertResult:
    active_router = router or AlertRouter(
        config_path=_require_config_path(config_path),
        env_file=env_file,
        env=env,
        agent_dispatch_fn=agent_dispatch_fn,
    )
    return active_router.send(alert)


def send_alert_message(
    message: str,
    *,
    title: str = "",
    level: AlertLevel | str = AlertLevel.NORMAL,
    category: AlertCategory | str = AlertCategory.CUSTOM,
    source: str = "",
    source_type: str = "",
    metadata: dict[str, Any] | None = None,
    channel: str | None = None,
    router: AlertRouter | None = None,
    config_path: str | Path | None = None,
    env_file: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    agent_dispatch_fn: Callable[[str, str, Any, Mapping[str, str] | None, dict[str, str]], None] | None = None,
) -> AlertResult:
    alert = Alert(
        title=title,
        body=message,
        level=coerce_alert_level(level),
        category=coerce_alert_category(category),
        source=source,
        source_type=source_type,
        metadata=dict(metadata or {}),
    )
    active_router = router or AlertRouter(
        config_path=_require_config_path(config_path),
        env_file=env_file,
        env=env,
        agent_dispatch_fn=agent_dispatch_fn,
    )
    if channel:
        return active_router.send_channel(alert, channel=channel, level=alert.level)
    return active_router.send(alert)


def _resolve_env(env: Mapping[str, str] | None, env_file: str | Path | None) -> Mapping[str, str] | None:
    if env is not None:
        return dict(env)
    if env_file is not None:
        return _load_dotenv(env_file)
    return None


def _require_config_path(config_path: str | Path | None) -> str | Path:
    return config_path or DEFAULT_CONFIG_PATH


__all__ = [
    "Alert",
    "AlertCategory",
    "AlertDecision",
    "AlertEvaluator",
    "AlertLevel",
    "AlertResult",
    "AlertRouter",
    "get_imessage_target",
    "get_telegram_config",
    "send",
    "send_alert",
    "send_alert_message",
    "send_email",
    "send_imessage",
    "send_telegram",
]
