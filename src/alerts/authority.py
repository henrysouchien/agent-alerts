"""Send authority: the one gate every outbound send in this package passes.

The package cannot know whether the process embedding it is allowed to reach a
real destination (a dev checkout must not message production chats). The host
answers that by injecting a predicate with ``set_send_authority``. Default-deny:
with nothing injected, a predicate that returns anything but ``True``, or a
predicate that raises, every send path refuses with ``SendNotAuthorized`` before
any network, SMTP, subprocess or agent-dispatch work starts.
"""

from __future__ import annotations

import threading
from typing import Callable

SendAuthority = Callable[[], bool]

_lock = threading.Lock()
_predicate: SendAuthority | None = None


class SendNotAuthorized(RuntimeError):
    """The host has not authorized this process to send; nothing was sent."""


def set_send_authority(predicate: SendAuthority) -> None:
    """Inject the predicate that decides whether this process may send.

    The predicate takes no arguments and is called on every send attempt, so it
    may change its answer over the process lifetime. A later call replaces an
    earlier one.
    """
    global _predicate
    if not callable(predicate):
        raise TypeError("send authority must be a callable returning bool")
    with _lock:
        _predicate = predicate


def clear_send_authority() -> None:
    """Remove the injected predicate, returning to default-deny."""
    global _predicate
    with _lock:
        _predicate = None


def require_send_authority(channel: str) -> None:
    """Raise ``SendNotAuthorized`` unless the injected predicate returns ``True``."""
    with _lock:
        predicate = _predicate
    if predicate is None:
        raise SendNotAuthorized(f"{channel} send refused: no send authority injected")
    try:
        authorized = predicate()
    except Exception as exc:
        raise SendNotAuthorized(
            f"{channel} send refused: send authority raised {type(exc).__name__}"
        ) from exc
    if authorized is not True:
        raise SendNotAuthorized(f"{channel} send refused: send authority denied")


__all__ = [
    "SendAuthority",
    "SendNotAuthorized",
    "clear_send_authority",
    "require_send_authority",
    "set_send_authority",
]
