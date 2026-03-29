# agent-alerts

Structured alert routing to humans and AI agents.

## Install

```bash
pip install agent-alerts
pip install "agent-alerts[mcp]"
pip install "agent-alerts[agent]"
```

Python imports stay under `alerts`.

## Quick Start

Send a simple alert directly to Telegram:

```python
from alerts import send

send("Screen complete: 4 names passed", channel="telegram")
```

That reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from your environment unless you pass `token=` and `chat_id=` explicitly.

Use `AlertRouter` for structured routing, thresholds, quiet hours, and agent follow-up:

```python
from alerts import Alert, AlertCategory, AlertLevel, AlertRouter

router = AlertRouter(config_path="alerting.yaml")

result = router.send(
    Alert(
        title="Estimate revisions turning negative",
        body="NVDA revisions rolled over after guidance.",
        level=AlertLevel.HIGH,
        category=AlertCategory.SIGNAL,
        source="portfolio-system",
        source_type="estimate_revisions",
        metadata={"passed_count": 1},
    )
)

print(result.delivered_channels)
print(result.agent_dispatched)
```

## Channels

| Channel | Purpose | Required config |
| --- | --- | --- |
| `telegram` | Fast human notification | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `imessage` | Local macOS delivery | `IMESSAGE_TARGET` or `channels.imessage.recipient`; optional `backend`, `service` |
| `email` | SMTP delivery | `smtp_host`, `smtp_port`, `from`, `to` plus `EMAIL_USERNAME`, `EMAIL_PASSWORD` |
| `agent` | Background agent analysis with human feedback | `gateway_url`, `gateway_api_key_env`; optional `model`, `feedback_channel` |

## Router Config

Example `alerting.yaml`:

```yaml
schema_version: 2
on_config_error: use_last_good

channels:
  telegram:
    enabled: true
  imessage:
    enabled: false
    recipient: "+15555551212"
    backend: applescript
  email:
    enabled: false
    smtp_host: smtp.gmail.com
    smtp_port: 587
    from: alerts@example.com
    to:
      - user@example.com
  agent:
    enabled: true
    gateway_url: "http://127.0.0.1:8002"
    gateway_api_key_env: "ALERTS_GATEWAY_API_KEY"
    model: "claude-sonnet-4-6"
    feedback_channel: telegram

routing:
  critical: [telegram, agent]
  high: [telegram, agent]
  normal: [telegram]
  low: []
  by_category:
    signal:
      critical: [telegram, agent]
    screen_result:
      high: [telegram, agent]

quiet_hours:
  enabled: true
  start: "22:00"
  end: "07:00"
  timezone: "America/New_York"
  per_channel:
    agent:
      enabled: false

rate_limits:
  enabled: true
  global_max_per_hour: 20
  agent_max_per_hour: 5

thresholds:
  _default:
    min_passed_count: 1
    default_level: normal
    max_per_hour: 3
  estimate_revisions:
    min_passed_count: 1
    level_rules:
      - when:
          passed_count_gte: 3
        level: critical
```

## MCP Server

The package exposes an MCP server entry point:

```bash
alerts-mcp
python -m alerts.mcp_server
```

It provides three tools:

- `notify_send`
- `notify_list_channels`
- `notify_test_channel`

## License

MIT
