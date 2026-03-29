from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Mapping

from ..config import get_imessage_target
from ..models import Alert, AlertLevel

IMSG_PATH = "/opt/homebrew/bin/imsg"


def send_imessage(
    message: str,
    target: str,
    service: str = "imessage",
    *,
    backend: str | None = None,
) -> dict:
    resolved_backend = _resolve_backend(backend)
    if resolved_backend == "imsg":
        return _send_imsg(message, target, service=service)
    return _send_applescript(message, target)


def _resolve_backend(backend: str | None) -> str:
    if backend:
        return backend
    if os.path.exists(IMSG_PATH):
        return "imsg"
    return "applescript"


def _send_imsg(message: str, target: str, *, service: str) -> dict:
    if not os.path.exists(IMSG_PATH):
        raise FileNotFoundError(
            f"imsg binary not found at {IMSG_PATH}. Install with: brew install imessage-cli"
        )

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "send",
        "params": {
            "to": target,
            "text": message,
            "service": service,
        },
    }
    proc = subprocess.run(
        [IMSG_PATH, "rpc"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"imsg rpc failed ({proc.returncode}): {detail}")

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError("imsg rpc returned empty stdout")

    response = json.loads(stdout.splitlines()[-1])
    if isinstance(response, dict) and response.get("error") is not None:
        raise RuntimeError(f"imsg rpc error: {response['error']}")
    return {"ok": True, "backend": "imsg", "response": response}


def _send_applescript(message: str, target: str) -> dict:
    script_lines = [
        "on run argv",
        "set targetRecipient to item 1 of argv",
        "set targetMessage to item 2 of argv",
        'tell application "Messages"',
        "set targetService to first service whose service type = iMessage",
        "set targetBuddy to buddy targetRecipient of targetService",
        "send targetMessage to targetBuddy",
        "end tell",
        "end run",
    ]
    command = ["osascript"]
    for line in script_lines:
        command.extend(["-e", line])
    command.extend([target, message])

    proc = subprocess.run(command, timeout=10, capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"osascript send failed ({proc.returncode}): {detail}")
    return {"ok": True, "backend": "applescript"}


class IMessageChannel:
    def send(
        self,
        alert: Alert,
        *,
        level: AlertLevel,
        channel_config: dict[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bool:
        config = channel_config or {}
        target = str(config.get("recipient", "")).strip() or get_imessage_target(env)
        backend = str(config.get("backend", "")).strip() or None
        service = str(config.get("service", "imessage")).strip() or "imessage"
        response = send_imessage(_render_message(alert, level), target, service=service, backend=backend)
        return bool(response.get("ok"))


def _render_message(alert: Alert, level: AlertLevel) -> str:
    parts = [part for part in (alert.title.strip(), alert.body) if part]
    message = "\n\n".join(parts)
    if level is AlertLevel.CRITICAL:
        return f"** ALERT ** {message}"
    return message
