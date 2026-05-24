# 如何开启观测追踪

本文将指导你如何为 llm-harness Agent 开启可观测性，实时追踪 Agent 的每一次思考、工具调用和系统事件。

---

## 观测系统概述

llm-harness 的可观测性系统基于事件驱动架构，分为三层：

```
┌──────────────────────────────────────────────────┐
│                  EventBus                         │
│  全局异步事件总线（asyncio.Queue）                │
│  emit(event) → 广播给所有订阅者 + 写入 tracker    │
├──────────────────────────────────────────────────┤
│              Event Types (17种)                   │
│  ┌──────────────┐  ┌──────────────────┐          │
│  │ Loop Events   │  │ System Events    │          │
│  │ - Assistant   │  │ - Session        │          │
│  │ - Tool        │  │ - Subagent       │          │
│  │ - Error       │  │ - Cron           │          │
│  └──────────────┘  │ - Memory         │          │
│                     │ - MCP/Plugin     │          │
│                     └──────────────────┘          │
├──────────────────────────────────────────────────┤
│                Consumers                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Tracker  │  │ Dashboard│  │ 程序化订阅      │   │
│  │ (JSONL)  │  │ (UI)     │  │ (实时指标收集)  │   │
│  └──────────┘  └──────────┘  └───────────────┘   │
└──────────────────────────────────────────────────┘
```

- **EventBus** — 全局异步事件总线，所有模块通过 `emit()` 推送事件
- **离散事件类型** — 17 种结构化事件，覆盖 Agent 运行的完整生命周期
- **Tracker** — JSONL 文件写入器，当配置了 `track_file` 时自动启动

---

## 1. 配置文件一行启用

最简单的方式是在 `settings.json` 中指定追踪文件路径：

```json
{
  "observability": {
    "track_file": "~/.agent-harness/track.jsonl"
  }
}
```

当 `track_file` 被设置时，`Harness.from_config()` 会自动创建并启动 `Tracker` 实例，将全部事件写入 JSONL 文件。

### 通过代码启用

```python
from pathlib import Path
from agent_harness import Harness, Agent, OpenAICompatProvider
from agent_harness.observability.tracker import Tracker, start_tracker_from_config

# 方式一：通过 Harness 构造函数传入
harness = Harness(
    provider=OpenAICompatProvider(api_key="sk-xxx"),
    tools=["read_file", "write_file"],
    tracker=Path.home() / ".agent-harness" / "track.jsonl",
)

# 方式二：手动创建 Tracker 并启动
tracker = Tracker(Path.home() / ".agent-harness" / "track.jsonl")
await tracker.start()

# 方式三：从 Config 自动启动（推荐）
from agent_harness.config.loader import load_config
config = load_config()
tracker = await start_tracker_from_config(config)
```

### 环境变量方式

```bash
# 在 Docker/K8s 环境中使用环境变量
export HARNESS_OBSERVABILITY__TRACK_FILE="/data/track.jsonl"
```

---

## 2. 17 种事件类型一览表

所有事件定义在 `agent_harness.observability.events` 中，分为循环事件和系统事件两类。

### Loop Events（Agent 推理循环）

| 事件 | 触发时机 | 关键字段 |
|------|----------|----------|
| `AssistantTextDelta` | LLM 流式输出每个文本片段 | `text` |
| `AssistantTurnComplete` | LLM 完成一次完整回复 | `content`, `usage` (token 用量) |
| `ToolExecutionStarted` | 工具开始执行 | `tool_name`, `tool_input` |
| `ToolExecutionCompleted` | 工具执行完成 | `tool_name`, `output`, `is_error`, `duration_ms` |
| `ErrorEvent` | 发生错误 | `message`, `recoverable` |
| `StatusEvent` | 状态变更 | `message` |

### System Events（基础设施事件）

| 事件 | 触发时机 | 关键字段 |
|------|----------|----------|
| `SessionOpened` | 新会话开始 | `session_key` |
| `SessionClosed` | 会话结束 | `session_key`, `message_count` |
| `SubagentSpawned` | 子 Agent 被创建 | `task_id`, `label` |
| `SubagentCompleted` | 子 Agent 完成 | `task_id`, `label`, `status`, `duration_ms` |
| `CronJobTriggered` | Cron 任务被触发 | `job_id`, `job_name` |
| `CronJobCompleted` | Cron 任务执行完成 | `job_id`, `job_name`, `status`, `duration_ms` |
| `MemoryConsolidated` | 记忆归档完成 | `session_key`, `messages_archived` |
| `McpConnectionChanged` | MCP 服务器连接状态变化 | `server_name`, `connected` |
| `PluginLoaded` | 插件加载完成 | `plugin_name` |
| `ConfigChanged` | 配置变更 | `key` |

### 事件关系图

```
一次 Agent 交互的典型事件流：

SessionOpened
  └─ AssistantTextDelta (多次)
  └─ ToolExecutionStarted
  │    └─ ToolExecutionCompleted
  └─ AssistantTextDelta (多次)
  └─ AssistantTurnComplete
SessionClosed
```

---

## 3. JSONL 输出格式

每行一个 JSON 对象，包含 `type`、`ts`、`data` 三个顶层字段：

```json
{"type":"AssistantTextDelta","ts":"2026-05-24T10:30:00.123456+00:00","data":{"text":"你好"}}
{"type":"ToolExecutionStarted","ts":"2026-05-24T10:30:01.234567+00:00","data":{"tool_name":"web_search","tool_input":{"query":"今天天气"}}}
{"type":"ToolExecutionCompleted","ts":"2026-05-24T10:30:02.345678+00:00","data":{"tool_name":"web_search","output":"搜索结果...","is_error":false,"duration_ms":1123.456}}
{"type":"AssistantTurnComplete","ts":"2026-05-24T10:30:05.456789+00:00","data":{"content":"今天天气晴朗...","usage":{"input_tokens":150,"output_tokens":42}}}
```

### JSONL 字段说明

| 字段 | 说明 |
|------|------|
| `type` | 事件类名，与上表中的事件名称一致 |
| `ts` | ISO 8601 时间戳（UTC） |
| `data` | 事件特有数据，包含该事件 dataclass 的所有字段 |

### 用 jq 分析日志

```bash
# 查看所有工具调用耗时
jq 'select(.type == "ToolExecutionCompleted") | {tool: .data.tool_name, duration: .data.duration_ms}' track.jsonl

# 统计每种事件的频次
jq -r '.type' track.jsonl | sort | uniq -c | sort -rn

# 筛选错误事件
jq 'select(.type == "ErrorEvent")' track.jsonl

# 查看最近 5 次 Assistant 回复
jq 'select(.type == "AssistantTurnComplete") | .data.content' track.jsonl | tail -5

# 查询某次会话的全部事件
jq 'select(.data.session_key == "cli:c1")' track.jsonl
```

---

## 4. 程序化订阅（实时指标收集）

EventBus 支持 `subscribe()` 方法注册实时监听器，适合对接自定义指标系统。

### 实时统计 Token 用量

```python
import asyncio
from agent_harness.observability.bus import EventBus, get_event_bus
from agent_harness.observability.events import (
    AssistantTurnComplete,
    ToolExecutionCompleted,
)


async def track_token_usage(event):
    """实时统计每次 LLM 调用的 Token 消耗。"""
    if isinstance(event, AssistantTurnComplete) and event.usage:
        total = event.usage.get("input_tokens", 0) + event.usage.get("output_tokens", 0)
        print(f"[Metrics] Token 消耗: {total} (输入: {event.usage.get('input_tokens', 0)}, "
              f"输出: {event.usage.get('output_tokens', 0)})")


async def track_tool_latency(event):
    """实时监控工具调用延迟。"""
    if isinstance(event, ToolExecutionCompleted):
        if event.duration_ms and event.duration_ms > 5000:
            print(f"[Alert] 工具 {event.tool_name} 执行耗时过长: {event.duration_ms:.0f}ms")


async def main():
    bus = get_event_bus()

    # 注册订阅者，返回 unsubscribe 函数
    unsub_token = bus.subscribe(track_token_usage)
    unsub_latency = bus.subscribe(track_tool_latency)

    # ... 运行 Agent ...

    # 不再需要时取消订阅
    unsub_token()
    unsub_latency()
```

### 收集自定义指标

```python
from collections import Counter
from agent_harness.observability.bus import get_event_bus
from agent_harness.observability.events import ToolExecutionCompleted


class MetricsCollector:
    """轻量级指标收集器。"""

    def __init__(self):
        self.tool_call_count = Counter()
        self.tool_errors = Counter()
        self.total_tool_duration = 0.0
        self._unsub = None

    def start(self):
        bus = get_event_bus()
        self._unsub = bus.subscribe(self._on_event)

    def stop(self):
        if self._unsub:
            self._unsub()

    async def _on_event(self, event):
        if isinstance(event, ToolExecutionCompleted):
            self.tool_call_count[event.tool_name] += 1
            if event.is_error:
                self.tool_errors[event.tool_name] += 1
            if event.duration_ms:
                self.total_tool_duration += event.duration_ms

    def report(self):
        print("=== 指标报告 ===")
        for tool, count in self.tool_call_count.most_common():
            errors = self.tool_errors[tool]
            print(f"  {tool}: 调用 {count} 次, 错误 {errors} 次")
        print(f"  总耗时: {self.total_tool_duration:.0f}ms")
```

---

## 5. 对接 Prometheus / Grafana

结合程序化订阅和 Prometheus 客户端库，可以将事件指标暴露给 Prometheus 抓取。

### 安装依赖

```bash
uv add prometheus-client
```

### 暴露指标端点

```python
import asyncio
from collections import defaultdict
from prometheus_client import start_http_server, Counter, Histogram
from agent_harness.observability.bus import get_event_bus
from agent_harness.observability.events import (
    AssistantTurnComplete,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)


class PrometheusExporter:
    """将 Agent 事件导出为 Prometheus 指标。"""

    def __init__(self, port: int = 8000):
        # Prometheus 指标定义
        self.tool_calls = Counter(
            "agent_tool_calls_total",
            "工具调用总数",
            ["tool_name", "status"],  # status: "ok" / "error"
        )
        self.tool_duration = Histogram(
            "agent_tool_duration_ms",
            "工具执行耗时（毫秒）",
            ["tool_name"],
            buckets=[100, 500, 1000, 3000, 5000, 10000],
        )
        self.token_usage = Counter(
            "agent_token_usage_total",
            "Token 消耗总量",
            ["type"],  # type: "input" / "output"
        )
        self.port = port
        self._unsub = None

    def start(self):
        # 启动 Prometheus HTTP 服务
        start_http_server(self.port)
        bus = get_event_bus()
        self._unsub = bus.subscribe(self._on_event)
        print(f"Prometheus 指标端点已启动: http://localhost:{self.port}/metrics")

    def stop(self):
        if self._unsub:
            self._unsub()

    async def _on_event(self, event):
        if isinstance(event, ToolExecutionCompleted):
            status = "ok" if not event.is_error else "error"
            self.tool_calls.labels(event.tool_name, status).inc()
            if event.duration_ms:
                self.tool_duration.labels(event.tool_name).observe(event.duration_ms)

        elif isinstance(event, AssistantTurnComplete) and event.usage:
            self.token_usage.labels("input").inc(event.usage.get("input_tokens", 0))
            self.token_usage.labels("output").inc(event.usage.get("output_tokens", 0))
```

### Prometheus 抓取配置

```yaml
# prometheus.yml
scrape_configs:
  - job_name: "llm-harness"
    static_configs:
      - targets: ["localhost:8000"]
```

### Grafana 面板示例指标

| 查询 | 面板类型 | 说明 |
|------|----------|------|
| `rate(agent_tool_calls_total[5m])` | 时间序列 | 工具调用频率 |
| `histogram_quantile(0.95, rate(agent_tool_duration_ms_bucket[5m]))` | 时间序列 | P95 工具延迟 |
| `sum(rate(agent_token_usage_total[5m])) by (type)` | 堆叠面积 | Token 消耗速率 |
| `sum(agent_tool_calls_total{status="error"}) by (tool_name)` | Bar chart | 工具错误分布 |

---

## 6. 对接 Dashboard

llm-harness 支持将观测事件发送到 Web Dashboard 实现实时可视化。

### 标准事件投递

Dashboard 通过订阅 EventBus 接收所有事件，或直接读取 JSONL 文件。你可以将 JSONL 接入任何日志收集系统：

```bash
# 使用 Filebeat 将 JSONL 发送到 Elasticsearch
filebeat.inputs:
  - type: log
    paths:
      - ~/.agent-harness/track.jsonl
    json.keys_under_root: true
    json.add_error_key: true

output.elasticsearch:
  hosts: ["https://localhost:9200"]
  index: "llm-harness-events"
```

```bash
# 使用 Vector 将 JSONL 发送到各种后端
[sources.track_file]
type = "file"
include = ["~/.agent-harness/track.jsonl"]

[transforms.parse_json]
type = "json_parser"
inputs = ["track_file"]
field = "."

[sinks.prometheus]
type = "prometheus"
inputs = ["parse_json"]
# ...
```

---

## 7. 性能开销说明

### 零开销当禁用

当未设置 `track_file` 且没有注册任何订阅者时，EventBus 是**零开销**的：

```python
# 检查 EventBus 是否活跃
from agent_harness.observability.bus import is_active

# 当没有消费者时，emit() 直接返回，不创建队列、不分配任何资源
```

```python
# agent_harness.observability.bus 的实现
_GLOBAL_BUS: EventBus | None = None

async def emit(event: object) -> None:
    if _GLOBAL_BUS is None:
        return  # 全局总线未创建，直接跳过 —— 零开销
    await _GLOBAL_BUS.emit(event)
```

### 开销估算

| 场景 | 额外开销 | 说明 |
|------|----------|------|
| 不配置 `track_file` | 无 | `emit()` 是空操作 |
| 配置 `track_file` | ~0.1ms/事件 | JSON 序列化 + 文件追加写 |
| 订阅 5 个监听器 | ~0.5ms/事件 | 串行调用监听器 |
| 满队列 | 事件丢弃 | 队列大小 4096，满时新事件静默丢弃 |

```python
# 默认队列大小 4096，满时静默丢弃不阻塞发送方
class EventBus:
    def __init__(self, maxsize: int = 4096):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def emit(self, event: object) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # 队列满了 —— 丢弃事件，不阻塞调用方
            return
```

---

## 8. 完整示例：开启追踪的 Agent

```python
"""observable-agent.py — 带有完整观测能力的 Agent"""
import asyncio
import logging
from pathlib import Path

from agent_harness import Harness, Agent, OpenAICompatProvider
from agent_harness.observability.bus import get_event_bus
from agent_harness.observability.tracker import Tracker
from agent_harness.observability.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ToolExecutionStarted,
    ToolExecutionCompleted,
    ErrorEvent,
)
from agent_harness.bus.events import InboundMessage

logging.basicConfig(level=logging.INFO)


async def live_viewer(event):
    """实时在终端打印事件，方便调试。"""
    if isinstance(event, AssistantTextDelta):
        print(event.text, end="", flush=True)
    elif isinstance(event, ToolExecutionStarted):
        print(f"\n[工具] {event.tool_name}({event.tool_input})")
    elif isinstance(event, ToolExecutionCompleted):
        status = "✓" if not event.is_error else "✗"
        print(f"\n[工具完成] {status} 耗时: {event.duration_ms:.0f}ms")
    elif isinstance(event, AssistantTurnComplete):
        print(f"\n--- Turn 完成, Token: {event.usage} ---")
    elif isinstance(event, ErrorEvent):
        print(f"\n[错误] {event.message} (可恢复: {event.recoverable})")


async def main():
    # 1. 创建 Tracker（写入 JSONL）
    tracker = Tracker(Path.home() / ".agent-harness" / "track.jsonl")
    await tracker.start()

    # 2. 订阅实时查看器
    bus = get_event_bus()
    unsub = bus.subscribe(live_viewer)

    # 3. 创建 Agent
    agent = Agent(
        Harness(
            provider=OpenAICompatProvider(
                api_key="sk-xxx",
                api_base="https://api.openai.com/v1",
            ),
            tools=["web_search"],
        ),
        model="gpt-4o",
    )

    # 4. 处理消息
    result = await agent.process(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="demo",
            content="今天有什么新闻？",
        )
    )

    print(f"\n最终回复: {result.content}")

    # 5. 清理
    unsub()
    await tracker.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 相关参考

- [Observability API 参考](../api/observability.md) — `EventBus`、`Tracker`、事件类型完整 API
- [配置参考](../api/config.md) — `ObservabilityConfig` 完整配置说明
- [架构设计](../explanation/architecture.md) — 可观测性系统设计原理
