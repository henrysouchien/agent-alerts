from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any

from ..models import Alert, AlertLevel

log = logging.getLogger(__name__)

DispatchFn = Callable[[str, str, Any, Mapping[str, str] | None, dict[str, str]], None]


class AgentChannel:
    def __init__(
        self,
        *,
        dispatch_fn: DispatchFn | None = None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self._dispatch_fn = dispatch_fn
        self._thread_factory = thread_factory

    def send(
        self,
        alert: Alert,
        *,
        level: AlertLevel,
        channel_config: dict[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bool:
        config = channel_config or {}
        agent_name = str(config.get("agent_name", "")).strip()
        if not agent_name:
            raise ValueError("Missing required agent channel config: agent_name")
        if self._dispatch_fn is None:
            raise ValueError("Agent channel requires a dispatch_fn")

        notify = config.get("notify")
        task = self._format_task(alert, level)
        alert_context = {
            "alert_id": alert.alert_id,
            "source_type": alert.source_type or "",
            "level": level.value,
            "category": alert.category.value,
        }
        thread = self._thread_factory(
            target=self._run_thread,
            kwargs={
                "alert_id": alert.alert_id,
                "agent_name": agent_name,
                "task": task,
                "notify": notify,
                "env": dict(env) if env is not None else None,
                "alert_context": alert_context,
            },
            daemon=False,
            name=f"alerts-agent-{alert.alert_id}",
        )
        thread.start()
        return True

    def _run_thread(
        self,
        *,
        alert_id: str,
        agent_name: str,
        task: str,
        notify: Any,
        env: Mapping[str, str] | None,
        alert_context: dict[str, str],
    ) -> None:
        try:
            assert self._dispatch_fn is not None
            self._dispatch_fn(agent_name, task, notify, env, alert_context)
        except Exception:
            log.warning("Agent channel failed for alert %s", alert_id, exc_info=True)

    def _format_task(self, alert: Alert, level: AlertLevel) -> str:
        metadata = json.dumps(alert.metadata, indent=2, sort_keys=True, default=str)
        return "\n".join(
            [
                f"Title: {alert.title or '(none)'}",
                f"Body: {alert.body or '(none)'}",
                f"Level: {level.value}",
                f"Category: {alert.category.value}",
                f"Source: {alert.source or '(none)'}",
                f"Metadata: {metadata}",
            ]
        )


__all__ = ["AgentChannel"]
