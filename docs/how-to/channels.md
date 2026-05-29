# How to Configure Channels

## Goal

Set up communication channels — CLI for interactive terminal use and WebSocket for external clients.

## Prerequisites

- Working llm-harness installation
- `pip install websockets` (for WebSocket)

## Step by Step

### 1. CLI Channel (stdin/stdout)

The CLI channel reads from stdin and writes to stdout. No auth needed — it trusts the terminal user.

```python
from llm_harness.extensions.channels.cli import CLIChannel
from llm_harness.core.bus.queue import MessageBus

bus = MessageBus()
channel = CLIChannel({"enabled": True, "allow_from": ["*"]}, bus)
await channel.start()
```

### 2. WebSocket Channel with Auth

```python
from llm_harness.extensions.channels.websocket import WebSocketChannel

async def my_auth(payload: dict) -> bool:
    token = payload.get("token", "")
    sender_id = payload.get("sender_id", "")
    # Verify token with your auth service
    return token == "valid-token" and sender_id != ""

ws_channel = WebSocketChannel(
    {"enabled": True, "host": "0.0.0.0", "port": 8081,
     "auth_callback": my_auth, "allow_from": ["alice", "bob"]},
    bus,
)
```

### 3. ChannelManager for Multiple Channels

```python
from llm_harness.extensions.channels.manager import ChannelManager
from llm_harness.extensions.channels.cli import CLIChannel
from llm_harness.extensions.channels.websocket import WebSocketChannel

manager = ChannelManager(
    channel_types={"cli": CLIChannel, "websocket": WebSocketChannel},
    channels_config={
        "cli": {"enabled": True, "allow_from": ["*"]},
        "websocket": {"enabled": True, "host": "0.0.0.0", "port": 8081,
                      "auth_callback": my_auth, "allow_from": ["*"]},
    },
    bus=bus,
    send_max_retries=3,
)

# Start all channels
await manager.start_all()

# Check status
print(manager.get_status())
# -> {"cli": {"enabled": True, "running": True}, "websocket": {...}}

# Graceful stop
await manager.stop_all()
```

## WebSocket Client Example

```bash
# Connect with websocat
websocat ws://127.0.0.1:8081
# Send auth
{"type":"auth","sender_id":"alice","chat_id":"c1","token":"valid-token"}
# -> {"type":"auth_ok"}
# Send message
{"type":"message","content":"Hello"}
# -> streaming deltas then final response
# {"type":"delta","content":"Hello"}
# {"type":"delta","content":" there"}
# {"type":"done","content":"Hello there!"}
```

## Key Configuration Fields

| Field | Type | Description |
|-------|------|-------------|
| `allow_from` | `list[str]` | Sender allowlist. `["*"]` = all, `[]` = none |
| `host` | `str` | WebSocket bind host (default: `127.0.0.1`) |
| `port` | `int` | WebSocket bind port (default: `8081`) |
| `auth_callback` | `Callable` or `None` | Async auth function. `None` = no auth |
| `streaming` | `bool` | Enable streaming deltas to clients |
