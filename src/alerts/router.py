from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .channels.email import EmailChannel
from .channels.imessage import IMessageChannel
from .channels.telegram import TelegramChannel
from .config import _load_dotenv
from .evaluator import AlertDecision, AlertEvaluator
from .models import Alert, AlertLevel, AlertResult, coerce_alert_level


class AlertRouter:
    def __init__(
        self,
        *,
        config_path: str | Path,
        env_file: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._env_file = env_file
        self._env = dict(env) if env is not None else (_load_dotenv(env_file) if env_file is not None else None)
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
                if channel_name == "agent":
                    result.agent_dispatched = True
                else:
                    result.delivered_channels.append(channel_name)
            else:
                result.failed_channels[channel_name] = "delivery failed"

        if result.delivered_channels or result.agent_dispatched:
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
            if channel == "agent":
                result.agent_dispatched = True
            else:
                result.delivered_channels.append(channel)
        else:
            result.failed_channels[channel] = "delivery failed"
        return result

    def _get_channel(self, channel_name: str):
        adapter = self._channels.get(channel_name)
        if adapter is not None:
            return adapter
        if channel_name != "agent":
            return None
        try:
            from .channels.agent import AgentChannel
        except ImportError as exc:
            raise ImportError("httpx not installed (pip install agent-alerts[agent])") from exc
        adapter = AgentChannel()
        self._channels["agent"] = adapter
        return adapter


def _source_key(alert: Alert) -> str:
    return (alert.source_type or alert.source or "_default").strip() or "_default"


DEFAULT_CONFIG_PATH = Path("alerting.yaml")
