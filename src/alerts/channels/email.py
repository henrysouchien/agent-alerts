from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any, Mapping

from ..models import Alert, AlertLevel


def send_email(
    message: str,
    *,
    channel_config: dict[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    config = channel_config or {}
    smtp_host = str(config.get("smtp_host", "")).strip()
    sender = str(config.get("from", "")).strip()
    recipients_raw = config.get("to", [])
    if isinstance(recipients_raw, str):
        recipients = [recipients_raw.strip()] if recipients_raw.strip() else []
    elif isinstance(recipients_raw, list):
        recipients = [str(recipient).strip() for recipient in recipients_raw if str(recipient).strip()]
    else:
        recipients = []

    try:
        smtp_port = int(config.get("smtp_port", 0))
    except (TypeError, ValueError):
        smtp_port = 0

    if not smtp_host or not smtp_port or not sender or not recipients:
        return False

    credentials = dict(os.environ if env is None else env)
    username = str(credentials.get("EMAIL_USERNAME", "")).strip()
    password = str(credentials.get("EMAIL_PASSWORD", "")).strip()
    if not username or not password:
        return False

    msg = EmailMessage()
    msg["Subject"] = str(config.get("subject", "Investment Tools Alert"))
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(message)

    timeout = float(config.get("timeout_seconds", 10))
    use_ssl = bool(config.get("use_ssl", smtp_port == 465))
    use_starttls = bool(config.get("starttls", not use_ssl and smtp_port == 587))

    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout) as server:
            server.login(username, password)
            server.send_message(msg)
        return True

    with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as server:
        server.ehlo()
        if use_starttls:
            server.starttls()
            server.ehlo()
        server.login(username, password)
        server.send_message(msg)
    return True


class EmailChannel:
    def send(
        self,
        alert: Alert,
        *,
        level: AlertLevel,
        channel_config: dict[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bool:
        return send_email(_render_message(alert, level), channel_config=channel_config, env=env)


def _render_message(alert: Alert, level: AlertLevel) -> str:
    parts = [part for part in (alert.title.strip(), alert.body) if part]
    message = "\n\n".join(parts)
    if level is AlertLevel.CRITICAL:
        return f"** ALERT ** {message}"
    return message
