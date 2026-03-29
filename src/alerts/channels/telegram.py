from __future__ import annotations

import json
from typing import Any, Mapping
from urllib import request

from ..config import get_telegram_config
from ..models import Alert, AlertLevel

TELEGRAM_MESSAGE_LIMIT = 4096


def _truncate_message(message: str) -> str:
    if len(message) <= TELEGRAM_MESSAGE_LIMIT:
        return message
    return message[: TELEGRAM_MESSAGE_LIMIT - 3] + "..."


def send_telegram(message: str, token: str, chat_id: str, **kwargs) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload_dict = {"chat_id": chat_id, "text": _truncate_message(message)}
    payload_dict.update(kwargs)
    payload = json.dumps(payload_dict).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8")
    parsed = json.loads(body)
    result = parsed.get("result", {}) if isinstance(parsed, dict) else {}
    message_id = result.get("message_id") if isinstance(result, dict) else None
    return {
        "ok": bool(parsed.get("ok")) if isinstance(parsed, dict) else False,
        "message_id": int(message_id) if isinstance(message_id, int) else None,
        "response": parsed,
    }


class TelegramChannel:
    def send(
        self,
        alert: Alert,
        *,
        level: AlertLevel,
        channel_config: dict[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bool:
        _ = channel_config
        token, chat_id = get_telegram_config(env)
        response = send_telegram(_render_message(alert, level), token, chat_id)
        return bool(response.get("ok"))


def _render_message(alert: Alert, level: AlertLevel) -> str:
    parts = [part for part in (alert.title.strip(), alert.body) if part]
    message = "\n\n".join(parts)
    if level is AlertLevel.CRITICAL:
        return f"** ALERT ** {message}"
    return message
