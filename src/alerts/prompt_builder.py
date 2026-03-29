from __future__ import annotations

import json

from .models import Alert, AlertCategory, AlertLevel

READ_ONLY_TOOL_CONSTRAINT = "Use read-only tools only. Do not create, modify, or delete data."

_CATEGORY_INSTRUCTIONS = {
    AlertCategory.SCREEN_RESULT: (
        "Analyze this screening result. Focus on the most important names, outliers, "
        "and what deserves follow-up."
    ),
    AlertCategory.SIGNAL: (
        "Analyze this signal. Explain what changed, why it matters, and the safest next checks."
    ),
    AlertCategory.BUDGET: (
        "Analyze this budget alert. Focus on spend risk, timing, and the most useful next checks."
    ),
    AlertCategory.ERROR: (
        "Analyze this error alert. Identify likely cause, impact, and safe diagnostic next steps."
    ),
    AlertCategory.SYSTEM: (
        "Analyze this system alert. Focus on operational impact, urgency, and safe investigation."
    ),
    AlertCategory.CUSTOM: (
        "Analyze this alert. Summarize what matters, likely implications, and safe next steps."
    ),
}


class DefaultPromptBuilder:
    def build(self, alert: Alert, level: AlertLevel) -> str:
        sections = []
        if level is AlertLevel.CRITICAL:
            sections.append("CRITICAL ALERT: Treat this as urgent and lead with the highest-risk implications.")
        sections.append(_CATEGORY_INSTRUCTIONS.get(alert.category, _CATEGORY_INSTRUCTIONS[AlertCategory.CUSTOM]))
        sections.append(self._render_context(alert, level))
        sections.append(f"Tool Safety: {READ_ONLY_TOOL_CONSTRAINT}")
        return "\n\n".join(section for section in sections if section)

    def _render_context(self, alert: Alert, level: AlertLevel) -> str:
        metadata = json.dumps(alert.metadata, indent=2, sort_keys=True, default=str)
        return "\n".join(
            [
                "Alert Context:",
                f"Title: {alert.title or '(none)'}",
                f"Body: {alert.body or '(none)'}",
                f"Category: {alert.category.value}",
                f"Level: {level.value}",
                f"Source: {alert.source or '(none)'}",
                f"Source Type: {alert.source_type or '(none)'}",
                f"Timestamp: {alert.timestamp.isoformat()}",
                f"Alert ID: {alert.alert_id}",
                f"Metadata: {metadata}",
            ]
        )


__all__ = ["DefaultPromptBuilder", "READ_ONLY_TOOL_CONSTRAINT"]
