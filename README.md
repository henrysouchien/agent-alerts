# agent-alerts

Structured alert routing to humans and AI agents.

## Install

```bash
pip install agent-alerts
pip install "agent-alerts[mcp]"
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
| `agent` | Background agent analysis | `agent_name`, `dispatch_fn` on router; optional `notify` |

## Named Channel Variants

Define multiple instances of the same channel type for different contexts:

```yaml
channels:
  telegram-analyst:
    enabled: true
    bot_token_env: ANALYST_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID
  telegram-finance:
    enabled: true
    bot_token_env: FINANCE_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID
  agent-analyst:
    enabled: true
    agent_name: alerts-agent
    notify: telegram
  agent-finance:
    enabled: true
    agent_name: finance-agent
    notify: telegram

routing:
  critical: [telegram-analyst, agent-analyst]
  high: [telegram-analyst, agent-analyst]
  normal: [telegram-analyst]
  by_category:
    budget:
      high: [telegram-finance, agent-finance]
      normal: [telegram-finance]
```

Channel names are resolved by prefix: `telegram-*` → TelegramChannel, `agent-*` → AgentChannel, etc. Each variant reads its own credentials from `channel_config`. Plain names (`telegram`, `agent`) still work for backward compatibility.

Variants must be defined in `channels:` — undefined names are rejected to prevent typos silently falling back to default credentials.

## Agent Channel

The agent channel dispatches alerts to an AI agent for analysis. The caller provides a `dispatch_fn` when constructing the router:

```python
def my_dispatch(agent_name, task, notify, env, alert_context):
    """Called on a background thread by AgentChannel."""
    # invoke the agent, send notification, etc.
    ...

router = AlertRouter(
    config_path="alerting.yaml",
    agent_dispatch_fn=my_dispatch,
)
```

Config:

```yaml
channels:
  agent:
    enabled: true
    agent_name: alerts-agent
    notify: telegram          # where to send agent findings
```

## Independent Agent Rate Limiting

The agent channel can have its own rate budget, independent of human channels:

```yaml
rate_limits:
  enabled: true
  global_max_per_hour: 20
  agent_max_per_hour: 5       # opt-in, 0 or absent = agent follows human limits
```

When human channels are rate-limited, the agent can still fire if under its own `agent_max_per_hour` budget. This prevents losing agent analysis during alert bursts.

## Router Config

Example `alerting.yaml`:

```yaml
schema_version: 1
on_config_error: use_last_good

channels:
  telegram:
    enabled: true
  agent:
    enabled: true
    agent_name: alerts-agent
    notify: telegram

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

It provides four tools:

- `notify_send`
- `notify_preview`
- `notify_list_channels`
- `notify_test_channel`

`notify_send` always requires the confirmation token returned for the exact
payload by `notify_preview`; environment variables and caller-supplied mode
flags do not bypass that gate.

## License

MIT
