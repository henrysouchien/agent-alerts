from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class AlertLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class AlertCategory(str, Enum):
    SCREEN_RESULT = "screen_result"
    SIGNAL = "signal"
    BUDGET = "budget"
    ERROR = "error"
    SYSTEM = "system"
    CUSTOM = "custom"


def coerce_alert_level(value: AlertLevel | str) -> AlertLevel:
    if isinstance(value, AlertLevel):
        return value
    return AlertLevel(str(value).strip().lower() or AlertLevel.NORMAL.value)


def coerce_alert_category(value: AlertCategory | str) -> AlertCategory:
    if isinstance(value, AlertCategory):
        return value
    raw = str(value).strip().lower() or AlertCategory.CUSTOM.value
    try:
        return AlertCategory(raw)
    except ValueError:
        return AlertCategory.CUSTOM


def is_agent_channel(name: str) -> bool:
    return name == "agent" or name.startswith("agent-")


@dataclass(frozen=True)
class Alert:
    title: str
    body: str
    level: AlertLevel = AlertLevel.NORMAL
    category: AlertCategory = AlertCategory.CUSTOM
    source: str = ""
    source_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    alert_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", coerce_alert_level(self.level))
        object.__setattr__(self, "category", coerce_alert_category(self.category))


@dataclass
class AlertResult:
    alert: Alert
    evaluated_level: AlertLevel
    delivered_channels: list[str] = field(default_factory=list)
    skipped_channels: dict[str, str] = field(default_factory=dict)
    failed_channels: dict[str, str] = field(default_factory=dict)
    agent_dispatched: bool = False
    decision_reason: str | None = None
