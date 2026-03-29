from __future__ import annotations

from typing import Mapping

from .models import Alert

MESSAGE_LIMIT = 4096
SUPPORTED_FEEDBACK_CHANNELS = {"telegram", "imessage"}


class FeedbackHandler:
    def send(
        self,
        response: str,
        alert: Alert,
        *,
        channel: str = "telegram",
        env: Mapping[str, str] | None = None,
    ) -> bool:
        if channel not in SUPPORTED_FEEDBACK_CHANNELS:
            raise ValueError(f"Unsupported feedback channel: {channel}")

        source_type = alert.source_type or alert.source or "unknown"
        message = self._truncate(f"Agent Analysis: {source_type}\n\n{response}")

        from . import send as _send

        result = _send(message, channel=channel, env=env)
        if isinstance(result, dict):
            return bool(result.get("ok"))
        return bool(result)

    def _truncate(self, message: str) -> str:
        if len(message) <= MESSAGE_LIMIT:
            return message
        return message[: MESSAGE_LIMIT - 3] + "..."


__all__ = ["FeedbackHandler", "MESSAGE_LIMIT", "SUPPORTED_FEEDBACK_CHANNELS"]
