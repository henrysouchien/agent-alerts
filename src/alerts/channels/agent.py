from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Any

from ..feedback import FeedbackHandler, SUPPORTED_FEEDBACK_CHANNELS
from ..gateway_client import GatewayClient
from ..models import Alert, AlertLevel
from ..prompt_builder import DefaultPromptBuilder

log = logging.getLogger(__name__)


class AgentChannel:
    def __init__(
        self,
        *,
        prompt_builder: DefaultPromptBuilder | None = None,
        feedback_handler: FeedbackHandler | None = None,
        gateway_client_cls: type[GatewayClient] = GatewayClient,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self._prompt_builder = prompt_builder or DefaultPromptBuilder()
        self._feedback_handler = feedback_handler or FeedbackHandler()
        self._gateway_client_cls = gateway_client_cls
        self._thread_factory = thread_factory

    def send(
        self,
        alert: Alert,
        *,
        level: AlertLevel,
        channel_config: dict[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bool:
        import httpx

        _ = httpx
        config = channel_config or {}
        feedback_channel = str(config.get("feedback_channel", "telegram")).strip().lower() or "telegram"
        if feedback_channel not in SUPPORTED_FEEDBACK_CHANNELS:
            raise ValueError(f"Unsupported feedback channel: {feedback_channel}")

        gateway_url = str(config.get("gateway_url", "")).strip()
        if not gateway_url:
            raise ValueError("Missing required agent channel config: gateway_url")

        api_key_env_name = str(config.get("gateway_api_key_env", "ALERTS_GATEWAY_API_KEY")).strip()
        if not api_key_env_name:
            raise ValueError("Missing required agent channel config: gateway_api_key_env")

        credentials = dict(os.environ if env is None else env)
        gateway_api_key = str(credentials.get(api_key_env_name, "")).strip()
        if not gateway_api_key:
            raise ValueError(f"Missing required environment variable: {api_key_env_name}")

        model = str(config.get("model", "")).strip() or None
        prompt = self._prompt_builder.build(alert, level)
        thread = self._thread_factory(
            target=self._run_thread,
            kwargs={
                "alert": alert,
                "prompt": prompt,
                "gateway_url": gateway_url,
                "gateway_api_key": gateway_api_key,
                "model": model,
                "feedback_channel": feedback_channel,
                "env": dict(env) if env is not None else None,
            },
            daemon=False,
            name=f"alerts-agent-{alert.alert_id}",
        )
        thread.start()
        return True

    def _run_thread(
        self,
        *,
        alert: Alert,
        prompt: str,
        gateway_url: str,
        gateway_api_key: str,
        model: str | None,
        feedback_channel: str,
        env: Mapping[str, str] | None,
    ) -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self._stream_and_feedback(
                    alert=alert,
                    prompt=prompt,
                    gateway_url=gateway_url,
                    gateway_api_key=gateway_api_key,
                    model=model,
                    feedback_channel=feedback_channel,
                    env=env,
                )
            )
        except Exception:
            log.warning("Agent channel failed for alert %s", alert.alert_id, exc_info=True)
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    async def _stream_and_feedback(
        self,
        *,
        alert: Alert,
        prompt: str,
        gateway_url: str,
        gateway_api_key: str,
        model: str | None,
        feedback_channel: str,
        env: Mapping[str, str] | None,
    ) -> None:
        import httpx

        client = httpx.AsyncClient(timeout=120)
        try:
            gateway = self._gateway_client_cls(
                gateway_url,
                gateway_api_key,
                http_client=client,
            )
            response_parts: list[str] = []
            success = False
            stream = gateway.stream_chat(
                [{"role": "user", "content": prompt}],
                model=model,
            )
            try:
                async for event in stream:
                    event_type = str(event.get("type", "") or "")
                    if event_type == "text_delta":
                        delta = str(event.get("text", "") or "")
                        if delta:
                            response_parts.append(delta)
                        continue
                    if event_type == "tool_approval_request":
                        await gateway.submit_approval(
                            str(event.get("tool_call_id", "") or ""),
                            str(event.get("nonce", "") or ""),
                            approved=False,
                        )
                        continue
                    if event_type == "stream_complete":
                        success = True
                        break
                    if event_type in {"stream_error", "error"}:
                        log.warning(
                            "Agent channel stream error for alert %s: %s",
                            alert.alert_id,
                            event.get("error", "unknown"),
                        )
                        break
            finally:
                close_stream = getattr(stream, "aclose", None)
                if close_stream is not None:
                    await close_stream()

            if success and response_parts:
                self._feedback_handler.send(
                    "".join(response_parts),
                    alert,
                    channel=feedback_channel,
                    env=env,
                )
        finally:
            await client.aclose()


__all__ = ["AgentChannel"]
