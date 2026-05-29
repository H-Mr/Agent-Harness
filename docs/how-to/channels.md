# 如何配置 Channels

## 目标

设置通信 channel——CLI 用于交互式终端使用，WebSocket 用于外部客户端。

## 前置条件

- 可用的 llm-harness 安装
- `pip install websockets`（用于 WebSocket）

## 分步指南

### 1. CLI Channel（stdin/stdout）

CLI channel 从 stdin 读取并写入 stdout。无需认证——它信任终端用户。

```python
from llm_harness.extensions.channels.cli import CLIChannel
from llm_harness.core.bus.queue import MessageBus

bus = MessageBus()
channel = CLIChannel({"enabled": True, "allow_from": ["*"]}, bus)
await channel.start()
```

### 2. 带认证的 WebSocket Channel

```python
from llm_harness.extensions.channels.websocket import WebSocketChannel

async def my_auth(payload: dict) -> bool:
    token = payload.get("token", "")
    sender_id = payload.get("sender_id", "")
    # 使用你的认证服务验证 token
    return token == "valid-token" and sender_id != ""

ws_channel = WebSocketChannel(
    {"enabled": True, "host": "0.0.0.0", "port": 8081,
     "auth_callback": my_auth, "allow_from": ["alice", "bob"]},
    bus,
)
```

### 3. 使用 ChannelManager 管理多个 Channel

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

# 启动所有 channel
await manager.start_all()

# 查看状态
print(manager.get_status())
# -> {"cli": {"enabled": True, "running": True}, "websocket": {...}}

# 优雅停止
await manager.stop_all()
```

## WebSocket 客户端示例

```bash
# 使用 websocat 连接
websocat ws://127.0.0.1:8081
# 发送认证信息
{"type":"auth","sender_id":"alice","chat_id":"c1","token":"valid-token"}
# -> {"type":"auth_ok"}
# 发送消息
{"type":"message","content":"Hello"}
# -> 流式 delta 然后返回最终响应
# {"type":"delta","content":"Hello"}
# {"type":"delta","content":" there"}
# {"type":"done","content":"Hello there!"}
```

## 关键配置字段

| 字段 | 类型 | 说明 |
|-------|------|------|
| `allow_from` | `list[str]` | 发送者白名单。`["*"]` = 全部允许，`[]` = 全部拒绝 |
| `host` | `str` | WebSocket 绑定主机（默认：`127.0.0.1`） |
| `port` | `int` | WebSocket 绑定端口（默认：`8081`） |
| `auth_callback` | `Callable` 或 `None` | 异步认证函数。`None` = 不认证 |
| `streaming` | `bool` | 启用向客户端流式推送 delta |
