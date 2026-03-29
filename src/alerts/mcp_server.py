#!/usr/bin/env python3
from __future__ import annotations

import os

from . import send
from .config import get_imessage_target, get_telegram_config


def create_mcp():
    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError("fastmcp is required for alerts.mcp_server; install agent-alerts[mcp]") from exc

    mcp = FastMCP("alerts", instructions="Send notifications via Telegram, iMessage, or email.")

    @mcp.tool()
    def notify_send(
        message: str,
        channel: str = "telegram",
        disable_web_page_preview: bool = False,
        parse_mode: str = "",
    ) -> dict:
        kwargs = {}
        if channel == "telegram":
            if disable_web_page_preview:
                kwargs["disable_web_page_preview"] = True
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
        return send(message, channel=channel, **kwargs)

    @mcp.tool()
    def notify_list_channels() -> dict:
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
        return send("Alerts MCP test - connection OK", channel=channel)

    return mcp


def main() -> None:
    create_mcp().run()


if __name__ == "__main__":
    main()
