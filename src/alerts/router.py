from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Mapping

from .channels.email import EmailChannel
from .channels.imessage import IMessageChannel
from .channels.telegram import TelegramChannel
from .config import _load_dotenv
from .evaluator import AlertDecision, AlertEvaluator
from .models import Alert, AlertLevel, AlertResult, coerce_alert_level, is_agent_channel

log = logging.getLogger(__name__)

_CHANNEL_PREFIXES = [
    ("telegram", TelegramChannel),
    ("imessage", IMessageChannel),
    ("email", EmailChannel),
]


class AlertRouter:
    def __init__(
        self,
        *,
        config_path: str | Path,
        env_file: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        agent_dispatch_fn: Callable[[str, str, Any, Mapping[str, str] | None, dict[str, str]], None] | None = None,
    ) -> None:
        self._env_file = env_file
        self._env = dict(env) if env is not None else (_load_dotenv(env_file) if env_file is not None else None)
        self._agent_dispatch_fn = agent_dispatch_fn
        self.alert_evaluator = AlertEvaluator(config_path)
        self._channels = {
            "telegram": TelegramChannel(),
            "imessage": IMessageChannel(),
            "email": EmailChannel(),
        }

    def send(self, alert: Alert) -> AlertResult:
        decision = self.alert_evaluator.evaluate(alert)
        result = AlertResult(alert=alert, evaluated_level=decision.level, decision_reason=decision.reason_skipped)
        if not decision.should_alert:
            return result
        return self.send_pre_evaluated(alert, decision)

    def refresh_env(self, env_file: str | Path | None = None) -> None:
        if env_file is not None:
            self._env_file = env_file
        self._env = _load_dotenv(self._env_file)

    def send_pre_evaluated(self, alert: Alert, decision: AlertDecision) -> AlertResult:
        result = AlertResult(alert=alert, evaluated_level=decision.level, decision_reason=decision.reason_skipped)
        if not decision.should_alert:
            return result

        agent_channels = [channel for channel in decision.channels if is_agent_channel(channel)]
        if len(agent_channels) > 1:
            log.warning("Multiple agent channels in decision, keeping first: %s", agent_channels[0])
            channels = [channel for channel in decision.channels if not is_agent_channel(channel)]
            channels.append(agent_channels[0])
            decision = AlertDecision(
                should_alert=decision.should_alert,
                level=decision.level,
                channels=channels,
                reason_skipped=decision.reason_skipped,
                agent_independent=decision.agent_independent,
            )

        for channel_name in decision.channels:
            try:
                adapter = self._get_channel(channel_name)
                if adapter is None:
                    result.skipped_channels[channel_name] = "unsupported channel"
                    continue
                channel_config = self.alert_evaluator.get_channel_config(channel_name)
                delivered = adapter.send(
                    alert,
                    level=decision.level,
                    channel_config=channel_config,
                    env=self._env,
                )
            except Exception as exc:
                result.failed_channels[channel_name] = str(exc)
                continue
            if delivered:
                if is_agent_channel(channel_name):
                    result.agent_dispatched = True
                else:
                    result.delivered_channels.append(channel_name)
            else:
                result.failed_channels[channel_name] = "delivery failed"

        if result.delivered_channels:
            self.alert_evaluator.record_alert_sent(_source_key(alert))
        if result.agent_dispatched:
            if decision.agent_independent:
                self.alert_evaluator.record_agent_sent(_source_key(alert))
            elif not result.delivered_channels:
                self.alert_evaluator.record_alert_sent(_source_key(alert))
        return result

    def send_channel(self, alert: Alert, *, channel: str, level: AlertLevel | str | None = None) -> AlertResult:
        evaluated_level = coerce_alert_level(level or alert.level)
        result = AlertResult(alert=alert, evaluated_level=evaluated_level)
        try:
            adapter = self._get_channel(channel)
            if adapter is None:
                result.skipped_channels[channel] = "unsupported channel"
                return result
            delivered = adapter.send(
                alert,
                level=evaluated_level,
                channel_config=self.alert_evaluator.get_channel_config(channel),
                env=self._env,
            )
        except Exception as exc:
            result.failed_channels[channel] = str(exc)
            return result
        if delivered:
            if is_agent_channel(channel):
                result.agent_dispatched = True
            else:
                result.delivered_channels.append(channel)
        else:
            result.failed_channels[channel] = "delivery failed"
        return result

    def _get_channel(self, channel_name: str):
        if "-" in channel_name and not self._is_configured_channel(channel_name):
            self._channels.pop(channel_name, None)
            return None

        adapter = self._channels.get(channel_name)
        if adapter is not None:
            return adapter

        for prefix, cls in _CHANNEL_PREFIXES:
            if channel_name.startswith(prefix + "-"):
                adapter = cls()
                self._channels[channel_name] = adapter
                return adapter

        if is_agent_channel(channel_name):
            from .channels.agent import AgentChannel

            adapter = AgentChannel(dispatch_fn=self._agent_dispatch_fn)
            self._channels[channel_name] = adapter
            return adapter

        return None

    def _is_configured_channel(self, channel_name: str) -> bool:
        config = self.alert_evaluator.get_config()
        if config is None:
            return False
        return channel_name in config.channels


def _source_key(alert: Alert) -> str:
    return (alert.source_type or alert.source or "_default").strip() or "_default"


DEFAULT_CONFIG_PATH = Path("alerting.yaml")
