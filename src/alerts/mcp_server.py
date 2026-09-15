#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Literal

from . import send
from .config import get_imessage_target, get_telegram_config

_VALID_CHANNELS = ("telegram", "imessage", "email")


@dataclass
class ToolError:
    error_class: str
    message: str
    names_correction: dict[str, Any] | None = None
    suggested_tool_calls: list[dict[str, Any]] | None = None
    recoverable: bool = True

    def to_envelope(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error_class": self.error_class,
            "message": self.message,
            "names_correction": self.names_correction or {},
            "suggested_tool_calls": self.suggested_tool_calls or [],
            "recoverable": self.recoverable,
        }


def create_mcp():
    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError("fastmcp is required for alerts.mcp_server; install agent-alerts[mcp]") from exc

    mcp = FastMCP("alerts", instructions="Send notifications via Telegram, iMessage, or email.")

    @mcp.tool()
    def notify_send(
        message: str,
        channel: Literal["telegram", "imessage", "email"] = "telegram",
        disable_web_page_preview: bool = False,
        parse_mode: str = "",
        confirm_token: str | None = None,
    ) -> dict:
        """Preview or send a notification to a registered channel.

        Discovery: call notify_list_channels to inspect channel availability.
        Valid channel values: telegram | imessage | email
        Safety: default calls only preview; call notify_preview first, then pass confirm_token to send.
        """
        preview = _notification_preview(message, channel, disable_web_page_preview, parse_mode)
        if preview["status"] == "error":
            return preview

        if confirm_token != preview["confirm_token"]:
            return preview

        kwargs = {}
        if channel == "telegram":
            if disable_web_page_preview:
                kwargs["disable_web_page_preview"] = True
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
        try:
            result = send(message, channel=channel, **kwargs)
        except Exception as exc:
            return ToolError(
                error_class=type(exc).__name__,
                message=str(exc),
                names_correction={"channel": "Run notify_list_channels to verify configured channels."},
                suggested_tool_calls=[
                    {
                        "name": "notify_list_channels",
                        "args": {},
                        "reason": "Verify channel configuration before retrying.",
                    }
                ],
            ).to_envelope()
        return {
            "status": "sent",
            "channel": channel,
            "result": result,
        }

    @mcp.tool()
    def notify_preview(
        message: str,
        channel: Literal["telegram", "imessage", "email"] = "telegram",
        disable_web_page_preview: bool = False,
        parse_mode: str = "",
    ) -> dict:
        """Preview a notification and return the confirm_token required by notify_send.

        Discovery: call notify_list_channels to inspect channel availability.
        Valid channel values: telegram | imessage | email
        """
        return _notification_preview(message, channel, disable_web_page_preview, parse_mode)

    @mcp.tool()
    def notify_list_channels() -> dict:
        """List notification channel configuration and valid channel names.

        Discovery: call before notify_preview, notify_send, or notify_test_channel to verify available channels.
        Sibling tools: notify_preview prepares a confirm_token; notify_send sends after confirmation; notify_test_channel checks delivery.
        Common mistake: do not guess Slack or Teams channel names; valid channel values are telegram | imessage | email.
        """
        channels = {}
        try:
            get_telegram_config()
            channels["telegram"] = {"configured": True}
        except ValueError:
            channels["telegram"] = {"configured": False, "missing": "TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID"}
        try:
            get_imessage_target()
            channels["imessage"] = {"configured": True, "imsg_binary": os.path.exists("/opt/homebrew/bin/imsg")}
        except ValueError:
            channels["imessage"] = {"configured": False, "missing": "IMESSAGE_TARGET"}
        channels["email"] = {"configured": False}
        return channels

    @mcp.tool()
    def notify_test_channel(channel: str = "telegram") -> dict:
        """Send a short connectivity test to one configured notification channel.

        Discovery: call notify_list_channels first to choose a configured channel.
        Sibling tools: notify_preview and notify_send are for user-provided notification content.
        Common mistake: do not use this for real alerts; it sends only the fixed test message.
        """
        return send("Alerts MCP test - connection OK", channel=channel)

    return mcp


def _notification_preview(
    message: str,
    channel: str,
    disable_web_page_preview: bool,
    parse_mode: str,
) -> dict:
    if channel not in _VALID_CHANNELS:
        return ToolError(
            error_class="InvalidChannel",
            message=f"Unknown channel: {channel}",
            names_correction={"channel": list(_VALID_CHANNELS)},
            suggested_tool_calls=[
                {
                    "name": "notify_list_channels",
                    "args": {},
                    "reason": "List configured channels and valid channel names.",
                }
            ],
        ).to_envelope()

    payload = {
        "message": message,
        "channel": channel,
        "disable_web_page_preview": bool(disable_web_page_preview),
        "parse_mode": parse_mode or "",
    }
    confirm_token = _notification_confirm_token(payload)
    return {
        "status": "confirmation_required",
        "dry_run": True,
        "channel": channel,
        "message": message,
        "options": {
            "disable_web_page_preview": bool(disable_web_page_preview),
            "parse_mode": parse_mode or "",
        },
        "confirm_token": confirm_token,
        "next_actions": [
            {
                "tool": "notify_send",
                "arguments": {
                    **payload,
                    "confirm_token": confirm_token,
                },
                "reason": "Send this exact notification after reviewing the preview.",
            }
        ],
    }


def _notification_confirm_token(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"notify:{hashlib.sha256(encoded).hexdigest()[:16]}"


def main() -> None:
    create_mcp().run()


if __name__ == "__main__":
    main()
