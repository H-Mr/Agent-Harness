# 如何对接微信和飞书

本文将指导你如何将 llm-harness Agent 接入即时通讯平台，让用户通过微信或飞书与 Agent 对话。

---

## 通道架构概述

llm-harness 的通道系统建立在三层抽象之上：

```
┌───────────────────────────────────────────────────┐
│                    ChannelManager                  │
│  管理所有通道的生命周期、消息分发、重试策略              │
├───────────────────────────────────────────────────┤
│   BaseChannel (ABC)                               │
│   start() / stop() / send() / _handle_message()   │
│   ↑            ↑            ↑                     │
│ ┌──────┐  ┌────────┐  ┌──────────┐               │
│ │微信   │  │飞书     │  │Telegram  │  ...          │
│ └──────┘  └────────┘  └──────────┘               │
├───────────────────────────────────────────────────┤
│                    MessageBus                      │
│   inbound queue → Agent → outbound queue          │
└───────────────────────────────────────────────────┘
```

- **`BaseChannel`** — 抽象基类，定义通道的通用接口（start/stop/send）
- **`ChannelManager`** — 通道管理器，负责初始化、启停、出站消息分发和重试
- **`MessageBus`** — 异步消息队列，入站消息从通道流向 Agent，出站消息从 Agent 流向通道

### 消息流转过程

一个完整的消息生命周期如下：

```
用户发消息 → BaseChannel._handle_message()
                  │
                  ▼
            is_allowed() 检查权限
                  │
                  ▼
          InboundMessage → MessageBus.inbound
                  │
                  ▼
              Agent 处理（LLM 推理 + 工具调用）
                  │
                  ▼
         OutboundMessage → MessageBus.outbound
                  │
                  ▼
         ChannelManager._dispatch_outbound()
                  │
                  ▼
           BaseChannel.send() → 用户收到回复
```

---

## 1. 创建企业微信机器人

企业微信通道使用 HTTP long-poll API（通过 ilinkai.weixin.qq.com），无需本地微信客户端，使用二维码认证。

### 安装依赖

```bash
# 企业微信通道额外依赖
uv add httpx qrcode pycryptodome
```

### 配置

在 `~/.agent-harness/settings.json` 中添加微信通道配置：

```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "allow_from": ["*"],
      "token": "",
      "base_url": "https://ilinkai.weixin.qq.com",
      "state_dir": "~/.agent-harness/weixin",
      "poll_timeout": 35
    }
  }
}
```

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enabled` | 是否启用通道 | `false` |
| `allow_from` | 允许的用户 ID 列表，`["*"]` 允许所有人 | `[]` |
| `token` | Bot Token，首次登录后自动保存 | `""` |
| `base_url` | 微信 API 地址 | `https://ilinkai.weixin.qq.com` |
| `state_dir` | 状态持久化目录（Token、上下文） | `~/.agent-harness/weixin` |
| `poll_timeout` | 长轮询超时（秒） | `35` |

### 代码接入

```python
import asyncio
from agent_harness import Harness, Agent, OpenAICompatProvider
from agent_harness.bus.queue import MessageBus
from agent_harness.channels.manager import ChannelManager
from agent_harness.channels.wechat import WeChatChannel


async def main():
    # 1. 创建 MessageBus
    bus = MessageBus()

    # 2. 创建 Agent
    agent = Agent(
        Harness(
            provider=OpenAICompatProvider(
                api_key="sk-xxx",
                api_base="https://api.openai.com/v1",
            ),
            tools=["read_file", "write_file", "web_search"],
        ),
        model="gpt-4o",
    )

    # 3. 创建通道管理器
    channels_config = {
        "weixin": {
            "enabled": True,
            "allow_from": ["*"],
        }
    }
    manager = ChannelManager(
        channel_types={"weixin": WeChatChannel},
        channels_config=channels_config,
        bus=bus,
    )

    # 4. 启动通道
    await manager.start_all()

    # 5. 循环处理入站消息
    try:
        while True:
            msg = await bus.consume_inbound()
            result = await agent.process(msg)
            await bus.publish_outbound(result)
    except KeyboardInterrupt:
        await manager.stop_all()


asyncio.run(main())
```

### 二维码登录

首次启动时，微信通道会在终端打印二维码：

```bash
python your_agent.py
# 输出:
# WeChat QR code login...
# ██████████████████████████████
# ██  ████  ██  ██  ██  ████  ██
# ██  ████  ██████████  ████  ██
# ...
# Login URL: https://login.weixin.qq.com/l/xxxxx
```

使用微信扫描二维码确认登录后，Token 会自动保存到 `state_dir`，后续启动无需重复扫码。

!!! tip "无头环境"
    在无终端环境（如 Docker）中，`qrcode` 库不可用时通道会自动回退为打印 Login URL，复制 URL 到浏览器扫码即可。

---

## 2. 创建飞书机器人

飞书通道使用 `lark-oapi` SDK 的 WebSocket 长连接，无需公网 IP 或 Webhook。

### 前置条件

1. 在[飞书开放平台](https://open.feishu.cn)创建应用
2. 开启机器人能力（Bot）
3. 订阅事件：`im.message.receive_v1`
4. 获取 `App ID` 和 `App Secret`

### 安装依赖

```bash
# 飞书通道依赖
uv add lark-oapi
```

### 配置

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "allow_from": ["*"],
      "app_id": "cli_xxxxxxxxxxxxxxx",
      "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "encrypt_key": "",
      "verification_token": "",
      "react_emoji": "THUMBSUP",
      "group_policy": "mention",
      "reply_to_message": false
    }
  }
}
```

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enabled` | 是否启用通道 | `false` |
| `allow_from` | 允许的用户 ID 列表 | `[]` |
| `app_id` | 飞书应用的 App ID | `""` |
| `app_secret` | 飞书应用的 App Secret | `""` |
| `encrypt_key` | 消息加密密钥（可选） | `""` |
| `verification_token` | 验证 Token（可选） | `""` |
| `react_emoji` | 自动回复的表情 | `"THUMBSUP"` |
| `group_policy` | 群聊策略：`"mention"`（仅 @bot）或 `"open"`（所有消息） | `"mention"` |
| `reply_to_message` | 是否用回复方式发送消息 | `false` |

### 代码接入

```python
import asyncio
from agent_harness import Harness, Agent, AnthropicProvider
from agent_harness.bus.queue import MessageBus
from agent_harness.channels.manager import ChannelManager
from agent_harness.channels.feishu import FeishuChannel


async def main():
    bus = MessageBus()

    agent = Agent(
        Harness(
            provider=AnthropicProvider(api_key="sk-ant-xxx"),
            tools=["read_file", "write_file", "exec", "web_search"],
        ),
        model="claude-sonnet-4-6",
    )

    manager = ChannelManager(
        channel_types={"feishu": FeishuChannel},
        channels_config={
            "feishu": {
                "enabled": True,
                "allow_from": ["*"],
                "app_id": "cli_xxxxxxxx",
                "app_secret": "xxxxxxxx",
            }
        },
        bus=bus,
    )

    await manager.start_all()

    try:
        while True:
            msg = await bus.consume_inbound()
            result = await agent.process(msg)
            await bus.publish_outbound(result)
    except KeyboardInterrupt:
        await manager.stop_all()


asyncio.run(main())
```

### 群聊策略

| `group_policy` | 行为 |
|---------------|------|
| `"mention"`（默认） | 只有在群聊中 @机器人 时才会处理消息 |
| `"open"` | 群聊中所有消息都会触发 Agent |

---

## 3. ChannelManager 管理多个通道

一个 Agent 可以同时对接多个通道。只需在 `channel_types` 中注册多个通道类，并在 `channels_config` 中分别配置。

### 同时对接微信和飞书

```python
manager = ChannelManager(
    channel_types={
        "weixin": WeChatChannel,
        "feishu": FeishuChannel,
    },
    channels_config={
        "weixin": {
            "enabled": True,
            "allow_from": ["*"],
        },
        "feishu": {
            "enabled": True,
            "allow_from": ["*"],
            "app_id": "cli_xxxxxxxx",
            "app_secret": "xxxxxxxx",
        },
    },
    bus=bus,
    send_tool_hints=True,   # 向用户显示工具调用进度
    send_progress=True,     # 发送处理中状态消息
    send_max_retries=3,     # 消息发送失败重试次数
)
```

### ChannelManager 参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `channel_types` | `dict[str, type[BaseChannel]]` | 通道名称到通道类的映射 | 必填 |
| `channels_config` | `dict[str, Any]` | 每个通道的配置（含 `enabled` 标记） | 必填 |
| `bus` | `MessageBus` | 消息总线实例 | 必填 |
| `send_tool_hints` | `bool` | 是否向用户发送工具调用提示 | `False` |
| `send_progress` | `bool` | 是否发送处理中状态 | `True` |
| `send_max_retries` | `int` | 发送失败最大重试次数 | `3` |

### 发送重试机制

ChannelManager 实现了指数退避重试策略：

```python
# 重试延迟：1s, 2s, 4s（超过 max_retries 后放弃并记录错误日志）
_SEND_RETRY_DELAYS = (1, 2, 4)
```

如果所有重试均失败，错误日志会被记录，但不会阻塞后续消息的处理。

### 查看通道状态

```python
# 获取所有通道的运行状态
status = manager.get_status()
# 返回示例：
# {
#     "weixin": {"enabled": True, "running": True},
#     "feishu": {"enabled": True, "running": True},
# }

# 获取启用的通道列表
enabled = manager.enabled_channels
# 返回：["weixin", "feishu"]
```

---

## 4. 同一个 Agent 处理不同通道的消息

llm-harness 的 `MessageBus` 将所有通道的入站消息统一为 `InboundMessage` 格式，Agent 无需关心消息来自哪个通道。

### InboundMessage 结构

```python
@dataclass
class InboundMessage:
    channel: str       # 来源通道： "weixin", "feishu", "cli" 等
    sender_id: str     # 发送者标识
    chat_id: str       # 会话标识（群聊 ID 或私聊 ID）
    content: str       # 消息文本
    media: list[str]   # 附件列表
    metadata: dict     # 通道特定元数据

    @property
    def session_key(self) -> str:
        # 会话隔离键，格式："通道名:chat_id"
        return f"{self.channel}:{self.chat_id}"
```

### OutboundMessage 结构

```python
@dataclass
class OutboundMessage:
    channel: str       # 目标通道
    chat_id: str       # 目标会话
    content: str       # 回复文本
    media: list[str]   # 附件列表
    metadata: dict     # 携带流式/进度标记
```

### 会话隔离

不同通道的消息使用 `session_key`（格式 `channel:chat_id`）进行隔离。同 session 的消息串行处理，不同 session 的消息可并行处理。这意味着微信用户 A 和飞书用户 B 可以同时与 Agent 交互而互不干扰。

---

## 5. 通道的 allowList 访问控制

每个通道支持通过 `allow_from` 配置项实现白名单访问控制。

### 工作原理

```python
# BaseChannel 中的权限检查逻辑
def is_allowed(self, sender_id: str) -> bool:
    allow_list = getattr(self.config, "allow_from", [])
    if not allow_list:
        # 空列表拒绝所有访问
        logger.warning("allow_from is empty -- all access denied")
        return False
    if "*" in allow_list:
        # 通配符允许所有人
        return True
    return str(sender_id) in allow_list
```

### 配置示例

```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "allow_from": ["wx_user_001", "wx_user_002"]
    },
    "feishu": {
      "enabled": true,
      "allow_from": ["ou_xxxxxxxxxx"]
    }
  }
}
```

| `allow_from` 值 | 行为 |
|----------------|------|
| `["*"]` | 允许所有用户 |
| `["user1", "user2"]` | 仅允许指定用户 |
| `[]` | 拒绝所有用户（启动时会触发 `SystemExit` 警告） |

!!! warning "空 allowList"
    如果 `allow_from` 为空列表 `[]`，所有消息都会被拒绝，ChannelManager 在初始化时会抛出 `SystemExit` 错误。要么显式设置为 `["*"]`，要么添加具体的用户 ID。

---

## 6. 完整示例：多通道 Agent

以下是一个同时对接微信和飞书的完整 Agent：

```python
"""multi-channel-agent.py — 同时对接微信和飞书的消息处理 Agent"""
import asyncio
import logging

from agent_harness import Harness, Agent, AnthropicProvider
from agent_harness.bus.queue import MessageBus
from agent_harness.channels.manager import ChannelManager
from agent_harness.channels.wechat import WeChatChannel
from agent_harness.channels.feishu import FeishuChannel

logging.basicConfig(level=logging.INFO)


async def main():
    bus = MessageBus()

    # 创建 Agent
    agent = Agent(
        Harness(
            provider=AnthropicProvider(api_key="sk-ant-xxx"),
            tools=["read_file", "write_file", "web_search", "exec"],
            permissions="default",
        ),
        model="claude-sonnet-4-6",
    )

    # 通道配置
    channels_config = {
        "weixin": {
            "enabled": True,
            "allow_from": ["*"],
        },
        "feishu": {
            "enabled": True,
            "allow_from": ["*"],
            "app_id": "cli_xxxxxxxxxxxxxxx",
            "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxx",
            "group_policy": "mention",
        },
    }

    # 通道管理器
    manager = ChannelManager(
        channel_types={
            "weixin": WeChatChannel,
            "feishu": FeishuChannel,
        },
        channels_config=channels_config,
        bus=bus,
        send_tool_hints=True,
    )

    # 启动所有通道
    await manager.start_all()

    print("Agent 已启动，等待消息...")
    print(f"已启用通道: {manager.enabled_channels}")

    try:
        while True:
            # 接收来自任何通道的消息
            inbound = await bus.consume_inbound()
            print(f"[{inbound.channel}] {inbound.sender_id}: {inbound.content[:60]}...")

            # Agent 处理（自动保持会话上下文）
            result = await agent.process(inbound)

            # 发送回复到对应的通道
            await bus.publish_outbound(result)
            print(f"  → 回复已发送到 {inbound.channel}")
    except KeyboardInterrupt:
        print("\n正在关闭通道...")
        await manager.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 相关参考

- [通道 API 参考](../api/channels.md) — `BaseChannel` 和 `ChannelManager` 完整 API
- [消息总线 API 参考](../api/harness.md) — `MessageBus` 和消息类型
- [架构设计](../explanation/architecture.md) — 通道系统的设计原理
