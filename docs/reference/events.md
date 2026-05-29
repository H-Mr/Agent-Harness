# Events

在代理生命周期中发射的结构化可观测性事件。

源码位置：`llm_harness.adapters.observability`

## EventEmitter

```python
class EventEmitter:
    def __init__(self, backend: ObservabilityBackend): ...
    async def send(self, event: object) -> None: ...
    async def tool_executing(self, name: str, args: dict) -> None: ...
    async def tool_completed(self, name: str, output: str, is_error: bool = False) -> None: ...
```

## DefaultObservabilityBackend

```python
class DefaultObservabilityBackend:
    def __init__(self, *, on_emit: EventHandler | None = None): ...
    async def emit(self, event_type: str, payload: dict) -> None: ...
    async def subscribe(self, event_type: str, handler: EventHandler) -> None: ...
    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None: ...
```

## 事件类型

### 循环事件

| 事件 | 键 | 载荷 | 发射点 |
|-------|-----|---------|----------------|
| `AssistantTextDelta` | `assistant:delta` | `text` | 流式令牌 |
| `AssistantTurnComplete` | `assistant:complete` | `content`、`usage` | 回合结束 |
| `ToolExecutionStarted` | `tool:executing` | `tool_name`、`tool_input` | 工具运行前 |
| `ToolExecutionCompleted` | `tool:completed` | `tool_name`、`output`、`is_error`、`duration_ms` | 工具运行后 |
| `ErrorEvent` | `error` | `message`、`recoverable` | 发生错误 |
| `StatusEvent` | — | `message` | 状态更新 |

### 系统事件

| 事件 | 键 | 载荷 | 发射点 |
|-------|-----|---------|----------------|
| `SessionOpened` | `session:opened` | `session_key` | Agent.process 开始 |
| `SessionClosed` | `session:closed` | `session_key`、`message_count` | Agent.process 结束 |
| `SubagentSpawned` | `agent:spawned` | `task_id`、`label` | 子代理创建 |
| `SubagentCompleted` | `agent:completed` | `task_id`、`label`、`status` | 子代理完成 |
| `MemoryConsolidated` | `memory:consolidated` | `session_key`、`messages_archived` | 整合完成 |

## 用法

```python
backend = DefaultObservabilityBackend(
    on_emit=lambda event_type, payload: jsonl_file.write(
        json.dumps({"type": event_type, **payload}) + "\n"
    )
)
emitter = EventEmitter(backend)

# 订阅特定事件
async def on_tool_completed(event_type, payload):
    print(f"工具 {payload['tool_name']} 已完成：{payload['is_error']}")

await backend.subscribe("tool:completed", on_tool_completed)
```
