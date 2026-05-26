# Day 6：安全、通道与权限

> **目标读者**：已理解 Agent 核心循环和工具系统，想了解 agent-harness 如何在多通道环境下保证执行安全和网络主权。
> **学完本节后，你应该能回答**：PermissionChecker 的三层决策如何串联？为什么 `requires_confirmation` 不是简单的 allow/deny 二元？BaseChannel 的 is_allowed 使用什么配置策略？SSRF 防护如何从 URL 走到 IP 校验？

---

## 一、深度解释

### 1.1 PermissionChecker 的三层决策

`src/agent_harness/permissions/checker.py` 中的 `PermissionChecker.evaluate()` 实现了**三层防御**：

```
evaluate(tool_name, is_read_only, file_path, command)
    │
    ├── 第一层：硬编码敏感路径保护 (SENSITIVE_PATH_PATTERNS)
    │     └── 不可绕过，不可配置
    │
    ├── 第二层：显式允许/拒绝列表
    │     ├── denied_tools → 立即拒绝
    │     ├── allowed_tools → 立即允许
    │     ├── path_rules → fnmatch 匹配的路径规则
    │     └── denied_commands → 命令模式拒绝
    │
    └── 第三层：PermissionMode 决策
          ├── FULL_AUTO → 全部允许
          ├── is_read_only → 允许
          ├── PLAN → 拒绝所有变更操作
          └── DEFAULT → requires_confirmation=True
```

**第一层为什么不可绕过？**

```python
SENSITIVE_PATH_PATTERNS: tuple[str, ...] = (
    "*/.ssh/*",
    "*/.aws/credentials",
    "*/.aws/config",
    "*/.config/gcloud/*",
    "*/.azure/*",
    "*/.gnupg/*",
    "*/.docker/config.json",
    "*/.kube/config",
    "*/.agent-harness/credentials.json",
    "*/.agent-harness/copilot_auth.json",
)
```

这些模式是**编译在代码中的**，不来自用户配置。即使用户设置 `mode: full_auto` 或添加了 allow 规则，只要操作的路径匹配这些模式，PermissionChecker 直接返回 `allowed=False`。

设计思路：LLM 可能被 prompt injection 操纵去读取 SSH 私钥或云服务凭证。如果将敏感路径保护放在配置中，攻击者可以通过修改配置来解除保护。硬编码在源码中意味着即使配置被篡改，底层防护仍然生效。这是一种 defense-in-depth 策略。

`fnmatch` 匹配的路径规则使用的是**完全解析后的绝对路径**，所以 `*/.ssh/*` 匹配 `/home/user/.ssh/id_rsa` 也匹配 `/root/.ssh/authorized_keys`。

### 1.2 PermissionDecision 的三值语义

`PermissionDecision` 不是简单的 allow/deny 布尔值：

```python
@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""
```

这实际上是一个**三值逻辑**：

| allowed | requires_confirmation | 含义 |
|---------|----------------------|------|
| `True` | `False` | 自动放行，无需用户干预 |
| `False` | `False` | 直接拒绝，给出 reason |
| `False` | `True` | 需要用户确认后才放行（DEFAULT 模式下） |

**为什么不让 requires_confirmation=true 时同时 allowed=true？**

这是 API 设计的刻意选择。如果 `allowed=True`，上游调用者（AgentLoop 或权限中间件）可能会直接执行工具而不弹确认框。通过保持 `allowed=False` 配合 `requires_confirmation=True`，调用者必须先检查 `requires_confirmation` 字段，进入"挂起->确认->执行"流程，否则工具根本跑不起来。这种设计迫使调用者显式处理确认逻辑。

`DEFAULT` 模式是所有权限模式中策略最精细的：

```python
if self._settings.mode == PermissionMode.DEFAULT:
    return PermissionDecision(
        allowed=False,
        requires_confirmation=True,
        reason="Mutating tools require user confirmation in default mode",
    )
```

注意它只影响**变更操作**。只读工具在第三层的 `is_read_only` 分支提前返回了 `allowed=True`。这意味着在 DEFAULT 模式下，`read_file` 可以自动执行，但 `shell` 命令需要用户确认。

### 1.3 路径规则的 fnmatch 与优先级

`PathRule` 来自用户配置的 `path_rules`：

```python
@dataclass(frozen=True)
class PathRule:
    pattern: str
    allow: bool
```

权限系统中的路径规则优先级遵循**先匹配先返回**原则：

```python
if file_path and self._path_rules:
    for rule in self._path_rules:
        if fnmatch.fnmatch(file_path, rule.pattern):
            if not rule.allow:
                return PermissionDecision(allowed=False, reason=...)
```

注意这里只有 `not rule.allow` 时直接拒绝，但 `rule.allow` 时并不立即返回 `allowed=True`。为什么？因为路径 allow 规则需要和 `denied_tools`、`denied_commands` 等其他规则联合生效。路径 allow 只是一个"不因此路径拒绝"的信号，但工具名可能仍然在 `denied_tools` 中。

但反过来，路径 deny 规则是一票否决的。如果文件路径匹配了一条 `allow=False` 的规则，直接拒绝，不再检查后续规则。

### 1.4 BaseChannel 的抽象生命周期

`src/agent_harness/channels/base.py` 中的 `BaseChannel` 定义了通道的标准契约：

```
login() → start() → [send() / send_delta()] → stop()
```

| 方法 | 语义 | 异常时 |
|------|------|--------|
| `login(force=False)` | 交互式登录（如 Telegram 扫码），可跳过（默认返回 True） | 返回 False |
| `start()` | 长连接监听，持续接收消息，调用 `_handle_message` 推入 MessageBus | Manager 打印 error 日志并继续 |
| `stop()` | 断开连接，清理资源 | 同上 |
| `send(msg)` | 发送完整消息 | 抛出异常让 Manager 重试 |
| `send_delta(chat_id, delta, metadata)` | 流式发送文本块 | 同上 |

`is_allowed` 方法实现了**白名单策略**：

```python
def is_allowed(self, sender_id: str) -> bool:
    allow_list = getattr(self.config, "allow_from", [])
    if not allow_list:
        logger.warning("%s: allow_from is empty -- all access denied", self.name)
        return False
    if "*" in allow_list:
        return True
    return str(sender_id) in allow_list
```

三个策略：
- `allow_from` 未设置或为空列表 → 拒绝所有（白名单关闭，安全默认）
- `allow_from` 包含 `"*"` → 允许所有（公开频道）
- `allow_from` 包含特定 ID → 仅允许这些 ID

`_handle_message` 在发出前检查权限并自动标记流式传输偏好：

```python
async def _handle_message(self, sender_id, chat_id, content, ...):
    if not self.is_allowed(sender_id):
        return  # 静默拒绝
    meta = metadata or {}
    if self.supports_streaming:
        meta = {**meta, "_wants_stream": True}
    msg = InboundMessage(channel=self.name, ...)
    await self.bus.publish_inbound(msg)
```

`sender_id` 和 `chat_id` 在通道层被显式转换为 `str` 类型。这是因为 Telegram 等平台可能返回整数 ID，而 MessageBus 的序列化要求统一为字符串。

### 1.5 ChannelManager 的多通道协调

`src/agent_harness/channels/manager.py` 中的 `ChannelManager` 是通道的调度中心：

```python
class ChannelManager:
    def __init__(self, channel_types, channels_config, bus, ...):
        self.channel_types = channel_types
        # _init_channels() 中：从 channel_types 字典创建启用的通道实例
        # 验证 allow_from 配置（空列表导致 SystemExit）
        # 创建 outbound dispatcher 的 asyncio.Task
```

`_dispatch_outbound` 是一个无限循环，消费 MessageBus 的 outbound 队列：

```python
async def _dispatch_outbound(self) -> None:
    while True:
        msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
        # 过滤 progress/tool_hint 消息（如果未启用）
        channel = self.channels.get(msg.channel)
        if channel:
            await self._send_with_retry(channel, msg)
```

发送重试使用指数退避策略：

```python
_SEND_RETRY_DELAYS = (1, 2, 4)  # 秒

async def _send_with_retry(self, channel, msg):
    for attempt in range(max_attempts):
        try:
            await self._send_once(channel, msg)
            return
        except asyncio.CancelledError:
            raise  # 优雅关闭：不吞 CancelledError
        except Exception as e:
            if attempt == max_attempts - 1:
                return  # 最后一次失败，放弃
            delay = _SEND_RETRY_DELAYS[min(attempt, len(_SEND_RETRY_DELAYS) - 1)]
            await asyncio.sleep(delay)
```

设计要点：`CancelledError` 被重新抛出而不是捕获。这保证了当 Manager 关闭时，正在重试的发送任务可以立即响应取消，而不是继续休眠重试。

`_send_once` 方法区分了流式和非流式消息：

```python
@staticmethod
async def _send_once(channel, msg):
    if msg.metadata.get("_stream_delta") or msg.metadata.get("_stream_end"):
        await channel.send_delta(msg.chat_id, msg.content, msg.metadata)
    elif not msg.metadata.get("_streamed"):
        await channel.send(msg)
```

流式消息走 `send_delta` 路径，非流式消息走 `send` 路径。`_streamed` 标记防止消息被重复发送。

### 1.6 SandboxAdapter：平台检测与 srt 包装

`src/agent_harness/sandbox/adapter.py` 的 `SandboxAdapter` 本质上是 Anthropic `srt`（Sandbox Runtime）CLI 的 Python 包装器。

**平台检测** (`_get_platform`)：

```python
def _get_platform() -> str:
    system = _platform.system().lower()
    if system == "linux":
        if "microsoft" in (_platform.release() or "").lower():
            return "wsl"  # Windows Subsystem for Linux
        return "linux"
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return system
```

WSL 被识别为独立的平台值，因为 bwrap 在 WSL 中需要额外的内核支持。

**依赖检查** (`get_sandbox_availability`)：

```python
if platform_name in {"linux", "wsl"} and shutil.which("bwrap") is None:
    return SandboxAvailability(enabled=True, available=False,
        reason="bubblewrap (`bwrap`) is required on Linux/WSL")

if platform_name == "macos" and shutil.which("sandbox-exec") is None:
    return SandboxAvailability(enabled=True, available=False,
        reason="`sandbox-exec` is required on macOS")
```

Linux 依赖 `bwrap` (bubblewrap)，macOS 依赖 `sandbox-exec`，Windows 原生不支持（提示使用 WSL）。

**命令包装** (`wrap_command_for_sandbox`)：

```python
def wrap_command_for_sandbox(command, *, enabled, sandbox_cfg, ...):
    availability = get_sandbox_availability(enabled, sandbox_cfg, ...)
    if not availability.active:
        return command, None  # 不包装，直接返回原始命令
    settings_path = _write_runtime_settings(build_sandbox_runtime_config(sandbox_cfg))
    wrapped = [
        availability.command or "srt",
        "--settings", str(settings_path),
        "-c", shlex.join(command),
    ]
    return wrapped, settings_path  # 调用者负责删除 settings_path
```

`build_sandbox_runtime_config` 将 agent-harness 的配置格式转换为 srt 所需的 JSON schema。`_write_runtime_settings` 使用 `tempfile.NamedTemporaryFile` 创建临时设置文件，确保每次沙箱调用都有独立的配置文件。

### 1.7 SSRF 防护的三层验证

`src/agent_harness/security/network.py` 实现了 SSRF（Server-Side Request Forgery）防护。

**第一层：URL 解析与 Scheme 验证**

```python
def validate_url_target(url: str) -> tuple[bool, str]:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
    if not p.netloc:
        return False, "Missing domain"
    if not p.hostname:
        return False, "Missing hostname"
```

只允许 http/https 协议，拒绝 `file://`、`ftp://`、`gopher://` 等容易被 SSRF 利用的协议。

**第二层：DNS 解析与 RFC 1918 验证**

```python
infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
for info in infos:
    addr = ipaddress.ip_address(info[4][0])
    if _is_private(addr):
        return False, f"Blocked: {hostname} resolves to private/internal address {addr}"
```

将被禁用的网段定义在 `_BLOCKED_NETWORKS` 中，覆盖 RFC 1918 私有地址、链路本地地址（169.254.x.x）、carrier-grade NAT（100.64.0.0/10）、IPv6 唯一本地地址和链路本地地址：

```python
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]
```

**第三层：重定向跟踪**

```python
def validate_resolved_url(url: str) -> tuple[bool, str]:
    hostname = p.hostname
    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private(addr):
            return False, f"Redirect target is a private address: {addr}"
    except ValueError:
        infos = socket.getaddrinfo(hostname, ...)
        for info in infos:
            if _is_private(addr):
                return False, f"Redirect target {hostname} resolves to private address {addr}"
```

一个攻击手法是先用一个合法域名（如 `example.com`）通过验证，然后服务端 302 重定向到 `http://169.254.169.254/latest/meta-data/`（云服务商的 metadata endpoint）。`validate_resolved_url` 在重定向前再次验证目标 IP。

此外，`contains_internal_url` 函数用于扫描命令字符串中的 URL：

```python
def contains_internal_url(command: str) -> bool:
    for m in _URL_RE.finditer(command):
        url = m.group(0)
        ok, _ = validate_url_target(url)
        if not ok:
            return True
    return False
```

正则 `https?://[^\s"`;|<>]+` 匹配命令中所有可能的 URL 并逐一验证。

---

## 二、源码导读

### 2.1 `permissions/checker.py` — evaluate() 的完整决策树 (147 行)

`PermissionChecker` 只有 147 行，`evaluate` 是唯一的核心方法。决策树按顺序执行：

1. **L88-97：敏感路径保护** — 遍历 `SENSITIVE_PATH_PATTERNS`，用 `fnmatch.fnmatch` 匹配路径。匹配即拒绝。
2. **L100-105：工具名黑白名单** — 先 `denied_tools` 后 `allowed_tools`。注意白名单不跳过后续的敏感路径检查（因为敏感路径在前，已经拦截了）。
3. **L108-123：路径规则和命令模式** — 遍历 `self._path_rules`（从 `PermissionSettings.path_rules` 解析），只对 deny 规则提前返回。然后检查 `denied_commands`（如 `"rm -rf *"`）。
4. **L127-145：PermissionMode 决策** — 四个分支：`FULL_AUTO` → 放行全部；只读 → 放行；`PLAN` → 拒绝变更；`DEFAULT` → 需要确认。

解析 path_rules 时有一段兼容性处理：

```python
for rule in getattr(settings, "path_rules", []):
    pattern = getattr(rule, "pattern", None) or \
              (rule.get("pattern") if isinstance(rule, dict) else None)
    allow = getattr(rule, "allow", True) if not isinstance(rule, dict) \
            else rule.get("allow", True)
```

这段代码支持 settings 的 `path_rules` 同时接受 Pydantic 模型和原始 dict，增强了向后兼容性。

### 2.2 `channels/base.py` — BaseChannel 的核心流程 (164 行)

`BaseChannel` 的核心是 `_handle_message` 方法。它做三件事：

1. **权限检查**：调用 `self.is_allowed(sender_id)`，未通过则静默拒绝（只打 log 不抛异常）
2. **流式标记**：如果 `self.supports_streaming` 为 True，在 metadata 中注入 `_wants_stream: True`
3. **发布消息**：构造 `InboundMessage` 并调用 `self.bus.publish_inbound(msg)`

注意 `is_allowed` 的默认行为是**空列表拒绝所有**：

```python
def is_allowed(self, sender_id: str) -> bool:
    allow_list = getattr(self.config, "allow_from", [])
    if not allow_list:
        return False  # 空列表 = 拒绝所有
```

ChannelManager 的 `_validate_allow_from` 进一步强化了这个约束——检测到空列表时直接 `raise SystemExit` 终止进程，避免意外暴露的通道。

### 2.3 `channels/manager.py` — ChannelManager 的调度循环 (218 行)

ChannelManager 在 `start_all` 中启动所有通道：

```python
async def start_all(self) -> None:
    self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
    tasks = []
    for name, channel in self.channels.items():
        tasks.append(asyncio.create_task(self._start_channel(name, channel)))
    await asyncio.gather(*tasks, return_exceptions=True)
```

`_start_channel` 是一个包装方法：

```python
async def _start_channel(self, name: str, channel: BaseChannel) -> None:
    try:
        await channel.start()
    except Exception as e:
        logger.error("Failed to start channel %s: %s", name, e)
```

如果某个通道的 `start()` 抛出异常（如网络不通），其他通道不受影响。`asyncio.gather(return_exceptions=True)` 确保异常不会传播导致整个 `start_all` 失败。

### 2.4 `sandbox/adapter.py` — 平台检测与命令包装 (200 行)

`get_sandbox_availability` 的五步检测流程：

1. **enabled 主开关**：disabled 直接返回 `available=False`
2. **平台兜底**：Windows 直接拒绝（提示 WSL）
3. **enabled_platforms 白名单**：如果配置了 `enabled_platforms`，检查当前平台是否在其中
4. **srt CLI 检测**：`shutil.which("srt")` 查找 npm 全局安装的 sandbox-runtime CLI
5. **bwrap/sandbox-exec 检测**：Linux/WSL 需要 bwrap，macOS 需要 sandbox-exec

`wrap_command_for_sandbox` 返回 `(wrapped_command, settings_path)`。调用者需要负责清理 `settings_path` 对应的临时文件。这种"返回未管理的临时资源"的设计是为了给调用者灵活的清理时机——可能在命令执行后立即清理，也可能在错误恢复时清理。

### 2.5 `security/network.py` — DNS + IP 双重验证 (105 行)

`validate_url_target` 的完整校验路径：

```
URL 输入
  → urlparse 提取 scheme/hostname
  → scheme 必须是 http/https
  → hostname 不能为空
  → socket.getaddrinfo 解析所有 IP
  → 每个 IP 与 _BLOCKED_NETWORKS 中的 12 个网段逐一比对
  → 任意 IP 落在私有网段 → 拒绝
  → 全部通过 → 返回 (True, "")
```

`validate_resolved_url` 处理重定向后的验证：

```
重定向 URL 输入
  → 尝试直接解析为 IP（hostname 可能是裸 IP，如 169.254.169.254）
  → 如果是 IP → 直接校验
  → 如果是域名 → socket.getaddrinfo 解析后校验
```

两个函数的不同侧重：`validate_url_target` 在**首次请求前**调用，`validate_resolved_url` 在**重定向后**调用。这分开设计是因为重定向后的 URL 可能已经包含了 IP（而非域名），需要不同的解析路径。

---

## 三、动手练习：实现一个 ConsoleChannel

让我们实现一个最简单的通道：通过 stdin 读取用户输入、stdout 输出响应。

### 3.1 实现 Channel

在 `src/agent_harness/channels/` 下新建 `console.py`：

```python
"""A simple console channel using stdin/stdout."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness.bus.events import OutboundMessage
from agent_harness.channels.base import BaseChannel


class ConsoleChannel(BaseChannel):
    """Read messages from stdin, write responses to stdout."""

    name = "console"
    display_name = "Console"

    def __init__(self, config: Any, bus):
        super().__init__(config, bus)
        self._reader: asyncio.StreamReader | None = None
        self._protocol: asyncio.StreamReaderProtocol | None = None

    async def start(self) -> None:
        """Start reading from stdin."""
        self._running = True
        loop = asyncio.get_running_loop()
        self._reader = asyncio.StreamReader()
        self._protocol = asyncio.StreamReaderProtocol(self._reader)
        # 将标准输入连接到 asyncio 的事件循环
        await loop.connect_read_pipe(
            lambda: self._protocol,  # type: ignore
            open(0, "rb", buffering=0),  # stdin, unbuffered binary
        )
        logger = self.__class__.__module__
        print("[ConsoleChannel ready. Type your message and press Enter.]")

        while self._running:
            try:
                line = await asyncio.wait_for(
                    self._reader.readline(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            if not line:
                # EOF (Ctrl+D or pipe closed)
                break

            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            await self._handle_message(
                sender_id="console_user",
                chat_id="console",
                content=text,
                metadata={"_wants_stream": True},
            )

    async def stop(self) -> None:
        """Stop the console channel."""
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Send a complete response to stdout."""
        print(f"\n[Agent]: {msg.content}")

    async def send_delta(
        self, chat_id: str, delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stream a text chunk to stdout."""
        print(delta, end="", flush=True)

    async def login(self, force: bool = False) -> bool:
        """No authentication needed for console."""
        return True
```

### 3.2 集成到 ChannelManager

```python
from agent_harness.channels.console import ConsoleChannel
from agent_harness.channels.manager import ChannelManager

manager = ChannelManager(
    channel_types={
        "console": ConsoleChannel,
        # "telegram": TelegramChannel,   # 如果有其他通道
    },
    channels_config={
        "console": {
            "enabled": True,
            "allow_from": ["*"],  # 允许所有输入
        },
    },
    bus=bus,
)

# 启动所有通道（包括 console）
await manager.start_all()
```

### 3.3 编写测试

创建 `tests/test_console_channel.py`：

```python
"""Tests for ConsoleChannel."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_harness.bus.events import InboundMessage, OutboundMessage
from agent_harness.channels.console import ConsoleChannel


@pytest.mark.asyncio
async def test_console_channel_send():
    """ConsoleChannel.send should print the message content."""
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()

    channel = ConsoleChannel({"allow_from": ["*"]}, bus)

    msg = OutboundMessage(
        channel="console",
        chat_id="console",
        content="Hello, world!",
    )
    # send 方法直接 print，我们验证它不抛异常即可
    await channel.send(msg)
    assert True


@pytest.mark.asyncio
async def test_console_channel_is_allowed():
    """Verify the allow_from configuration works."""
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()

    # 空 allow_from → 拒绝所有
    restricted = ConsoleChannel({}, bus)
    assert not restricted.is_allowed("anyone")

    # "*" → 允许所有
    open_channel = ConsoleChannel({"allow_from": ["*"]}, bus)
    assert open_channel.is_allowed("anyone")

    # 明确指定 → 仅允许指定用户
    specific = ConsoleChannel({"allow_from": ["alice"]}, bus)
    assert specific.is_allowed("alice")
    assert not specific.is_allowed("bob")


@pytest.mark.asyncio
async def test_console_channel_handle_message():
    """_handle_message should publish an InboundMessage to the bus."""
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()

    channel = ConsoleChannel({"allow_from": ["*"]}, bus)

    await channel._handle_message(
        sender_id="test_user",
        chat_id="console",
        content="test message",
    )

    bus.publish_inbound.assert_awaited_once()
    msg: InboundMessage = bus.publish_inbound.await_args[0][0]
    assert msg.channel == "console"
    assert msg.sender_id == "test_user"
    assert msg.content == "test message"


@pytest.mark.asyncio
async def test_console_channel_blocks_unauthorized():
    """Unauthorized senders should not publish to the bus."""
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()

    channel = ConsoleChannel({"allow_from": ["alice"]}, bus)

    await channel._handle_message(
        sender_id="mallory",
        chat_id="console",
        content="malicious payload",
    )

    bus.publish_inbound.assert_not_awaited()
```

### 3.4 手动测试

```python
# 在 main.py 或测试脚本中
import asyncio
from agent_harness.bus.queue import MessageBus
from agent_harness.channels.console import ConsoleChannel

async def main():
    bus = MessageBus()
    channel = ConsoleChannel({"allow_from": ["*"]}, bus)
    await channel.start()

asyncio.run(main())
```

运行这个脚本后，在终端输入文本并按 Enter，你会看到输入被转换为 `InboundMessage` 发布到 MessageBus（尽管当前没有消费者输出）。

这个练习让你理解了：
1. `BaseChannel` 的四个抽象方法如何映射到具体的 I/O 操作
2. `asyncio.StreamReader` + `connect_read_pipe` 如何将标准输入接入事件循环
3. `is_allowed` + `_handle_message` 的调用链如何从平台输入流到 MessageBus
4. `send` 和 `send_delta` 的区别：完整消息 vs 流式块
5. `asyncio.wait_for` + 超时轮询模式如何实现非阻塞的 stdin 读取
