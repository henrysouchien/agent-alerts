"""HTTP SSE client for the finance gateway."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

_SESSION_REFRESH_BUFFER_SECONDS = 300


@dataclass(frozen=True)
class SessionState:
    token: str
    session_id: str
    expires_at: int


class BackendHTTPError(RuntimeError):
    """Raised when the gateway returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        detail_text = detail.strip()
        message = f"Backend HTTP {status_code}"
        if detail_text:
            message = f"{message}: {detail_text}"
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail_text


def _parse_sse_event(raw: str) -> dict[str, Any] | None:
    data_lines: list[str] = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:]
        if payload.startswith(" "):
            payload = payload[1:]
        data_lines.append(payload)

    if not data_lines:
        return None

    payload_text = "\n".join(data_lines).strip()
    if not payload_text:
        return None

    try:
        parsed = json.loads(payload_text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def parse_sse_events(buffer: str) -> tuple[list[dict[str, Any]], str]:
    normalized = buffer.replace("\r\n", "\n").replace("\r", "\n")
    parts = normalized.split("\n\n")
    if len(parts) == 1:
        return [], normalized

    events: list[dict[str, Any]] = []
    for raw in parts[:-1]:
        parsed = _parse_sse_event(raw)
        if parsed is not None:
            events.append(parsed)
    return events, parts[-1]


class GatewayClient:
    """Minimal gateway client with single-session caching."""

    def __init__(
        self,
        gateway_url: str,
        gateway_api_key: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        time_fn: Any = time.time,
    ) -> None:
        self._gateway_url = gateway_url.rstrip("/")
        self._gateway_api_key = gateway_api_key
        self._time_fn = time_fn
        self._client = http_client or httpx.AsyncClient(timeout=60.0)
        self._owns_client = http_client is None
        self._session: SessionState | None = None
        self._pinned_token: str | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def invalidate_session(self) -> None:
        self._session = None
        self._pinned_token = None

    async def ensure_session(self, *, force_refresh: bool = False) -> SessionState:
        now = int(self._time_fn())
        session = self._session
        if (
            session is not None
            and not force_refresh
            and now < session.expires_at - _SESSION_REFRESH_BUFFER_SECONDS
        ):
            return session

        response = await self._client.post(
            f"{self._gateway_url}/api/chat/init",
            json={"api_key": self._gateway_api_key},
        )
        if response.status_code >= 400:
            raise BackendHTTPError(response.status_code, _response_detail(response))

        payload = response.json()
        session = SessionState(
            token=str(payload.get("session_token", "")),
            session_id=str(payload.get("session_id", "")),
            expires_at=int(payload.get("expires_at", 0) or 0),
        )
        self._session = session
        return session

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        session = await self.ensure_session()
        self._pinned_token = session.token

        payload: dict[str, Any] = {"messages": messages, "context": context or {}}
        if model:
            payload["model"] = model

        buffer = ""
        headers = {"Authorization": f"Bearer {session.token}"}
        try:
            async with self._client.stream(
                "POST",
                f"{self._gateway_url}/api/chat",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")
                    raise BackendHTTPError(response.status_code, detail)

                async for chunk in response.aiter_text():
                    if not chunk:
                        continue
                    buffer += chunk
                    events, buffer = parse_sse_events(buffer)
                    for event in events:
                        yield event
        finally:
            if self._pinned_token == session.token:
                self._pinned_token = None

    async def submit_approval(
        self,
        tool_call_id: str,
        nonce: str,
        approved: bool,
    ) -> tuple[int, dict[str, Any]]:
        token = self._pinned_token
        if not token:
            session = self._session or await self.ensure_session()
            token = session.token

        response = await self._client.post(
            f"{self._gateway_url}/api/chat/tool-approval",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "tool_call_id": tool_call_id,
                "nonce": nonce,
                "approved": approved,
            },
        )

        body: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                body = parsed
        except json.JSONDecodeError:
            body = {}

        if response.status_code >= 400 and response.status_code not in {404, 409, 410}:
            raise BackendHTTPError(response.status_code, _response_detail(response, body))
        return response.status_code, body


def _response_detail(response: httpx.Response, body: dict[str, Any] | None = None) -> str:
    parsed = body if body is not None else None
    if parsed is None:
        try:
            maybe_body = response.json()
            parsed = maybe_body if isinstance(maybe_body, dict) else None
        except json.JSONDecodeError:
            parsed = None
    if parsed:
        detail = parsed.get("detail") or parsed.get("error")
        if detail:
            return str(detail)
    return response.text


__all__ = [
    "BackendHTTPError",
    "GatewayClient",
    "SessionState",
    "_parse_sse_event",
    "parse_sse_events",
]
