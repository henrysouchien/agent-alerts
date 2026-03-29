from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AlertConfig, AlertConfigLoader
from .models import Alert, AlertLevel, coerce_alert_level
from .quiet_hours import in_quiet_hours
from .rate_limiter import InMemoryRateLimiter

log = logging.getLogger(__name__)


@dataclass
class AlertDecision:
    should_alert: bool
    level: AlertLevel
    channels: list[str]
    reason_skipped: str | None = None


class AlertEvaluator:
    def __init__(self, config_path: str | Path):
        self._loader = AlertConfigLoader(config_path)
        self._rate_limiter = InMemoryRateLimiter()
        self._condition_warnings: set[str] = set()

    def evaluate(self, alert: Alert) -> AlertDecision:
        config = self._loader.load()
        if config is None:
            return AlertDecision(True, AlertLevel.NORMAL, ["telegram"])

        thresholds = config.thresholds.get(self._source_key(alert), config.thresholds.get("_default", {}))
        passed_count = self._get_passed_count(alert.metadata)
        min_passed = int(thresholds.get("min_passed_count", 1))
        if passed_count < min_passed:
            return AlertDecision(
                should_alert=False,
                level=AlertLevel.LOW,
                channels=[],
                reason_skipped=f"passed_count {passed_count} < min {min_passed}",
            )

        try:
            level = coerce_alert_level(thresholds.get("default_level", alert.level))
        except ValueError:
            log.warning(
                "Unknown alert level '%s' for %s, falling back to 'normal'",
                thresholds.get("default_level"),
                self._source_key(alert),
            )
            level = AlertLevel.NORMAL
        context = self._build_context(alert.metadata)
        for rule in thresholds.get("level_rules", []):
            if self._eval_condition(str(rule.get("condition", "")), context):
                try:
                    level = coerce_alert_level(str(rule.get("level", level.value)))
                except ValueError:
                    log.warning("Unknown alert level '%s' for %s, falling back to 'normal'", rule.get("level"), self._source_key(alert))
                    level = AlertLevel.NORMAL
                break

        if config.rate_limits.get("enabled", False):
            max_per_hour = int(thresholds.get("max_per_hour", 5))
            global_max = int(config.rate_limits.get("global_max_per_hour", 20))
            source_type = self._source_key(alert)
            if not self._rate_limiter.check(source_type, max_per_hour):
                return AlertDecision(
                    should_alert=False,
                    level=level,
                    channels=[],
                    reason_skipped=f"rate limit exceeded ({max_per_hour}/hr for {source_type})",
                )
            if not self._rate_limiter.check_global(global_max):
                return AlertDecision(
                    should_alert=False,
                    level=level,
                    channels=[],
                    reason_skipped=f"global rate limit exceeded ({global_max}/hr)",
                )

        channels = self._resolve_channels(config, alert, level)
        if not channels:
            return AlertDecision(
                should_alert=False,
                level=level,
                channels=[],
                reason_skipped=f"level '{level.value}' routes to no channels",
            )

        if level is not AlertLevel.CRITICAL and config.quiet_hours.get("enabled", False):
            channels = [channel for channel in channels if not in_quiet_hours(config.quiet_hours, channel=channel)]

        if not channels:
            return AlertDecision(
                should_alert=False,
                level=level,
                channels=[],
                reason_skipped="all channels suppressed by quiet hours",
            )

        channels = [
            channel
            for channel in channels
            if isinstance(config.channels.get(channel), dict) and config.channels[channel].get("enabled", False)
        ]

        return AlertDecision(
            should_alert=bool(channels),
            level=level,
            channels=channels,
            reason_skipped=None if channels else "no enabled channels",
        )

    def record_alert_sent(self, source_type: str) -> None:
        self._rate_limiter.record(source_type)

    def get_channel_config(self, channel: str) -> dict[str, Any] | None:
        return self._loader.get_channel_config(channel)

    def get_config(self) -> AlertConfig | None:
        return self._loader.load()

    def _resolve_channels(self, config: AlertConfig, alert: Alert, level: AlertLevel) -> list[str]:
        routing = config.routing
        by_category = routing.get("by_category", {})
        category_name = alert.category.value
        if isinstance(by_category, dict):
            category_routes = by_category.get(category_name)
            if isinstance(category_routes, dict):
                matched = category_routes.get(level.value)
                if isinstance(matched, list):
                    return [str(channel) for channel in matched]
        routed = routing.get(level.value, [])
        return [str(channel) for channel in routed] if isinstance(routed, list) else []

    def _get_passed_count(self, metadata: dict[str, Any]) -> int:
        raw = metadata.get("passed_count", 0)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _build_context(self, metadata: dict[str, Any]) -> dict[str, Any]:
        context = dict(metadata)
        source_ticker_count = context.get("source_ticker_count", context.get("source_count", 0))
        context.setdefault("passed_count", self._get_passed_count(metadata))
        context.setdefault("source_ticker_count", source_ticker_count)
        context.setdefault("picks_extracted", 0)
        context.setdefault("has_new_tickers", False)
        context.setdefault("has_dropped_tickers", False)
        context.setdefault("has_spikes", False)
        return context

    def _source_key(self, alert: Alert) -> str:
        return (alert.source_type or alert.source or "_default").strip() or "_default"

    def _eval_condition(self, condition: str, context: dict[str, Any]) -> bool:
        condition = condition.strip()
        if not condition:
            return False

        if " and " in condition:
            return all(self._eval_condition(part.strip(), context) for part in condition.split(" and "))

        if condition in context and isinstance(context[condition], bool):
            return bool(context[condition])

        operators = (
            (">=", lambda left, right: left >= right),
            ("<=", lambda left, right: left <= right),
            ("==", lambda left, right: left == right),
            ("!=", lambda left, right: left != right),
            (">", lambda left, right: left > right),
            ("<", lambda left, right: left < right),
        )
        for operator, predicate in operators:
            if operator not in condition:
                continue
            lhs, rhs = condition.split(operator, 1)
            lhs = lhs.strip()
            rhs = rhs.strip()
            if lhs not in context:
                self._warn_once(f"Unknown field '{lhs}' in condition: {condition}")
                return False
            try:
                rhs_value = float(rhs)
            except ValueError:
                self._warn_once(f"Invalid RHS '{rhs}' in condition: {condition}")
                return False
            try:
                return predicate(float(context[lhs]), rhs_value)
            except (TypeError, ValueError):
                return False

        self._warn_once(f"Unrecognized condition expression: {condition}")
        return False

    def _warn_once(self, message: str) -> None:
        if message in self._condition_warnings:
            return
        self._condition_warnings.add(message)
        log.warning("Alerting condition: %s", message)
