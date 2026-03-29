from __future__ import annotations

from typing import Any, Mapping, Protocol

from ..models import Alert, AlertLevel


class ChannelAdapter(Protocol):
    def send(
        self,
        alert: Alert,
        *,
        level: AlertLevel,
        channel_config: dict[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bool: ...
