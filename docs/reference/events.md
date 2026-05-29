# Events

Structured observability events emitted throughout the agent lifecycle.

Source: `llm_harness.adapters.observability`

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

## Event Types

### Loop Events

| Event | Key | Payload | Emission Point |
|-------|-----|---------|----------------|
| `AssistantTextDelta` | `assistant:delta` | `text` | Streaming token |
| `AssistantTurnComplete` | `assistant:complete` | `content`, `usage` | Turn finished |
| `ToolExecutionStarted` | `tool:executing` | `tool_name`, `tool_input` | Before tool runs |
| `ToolExecutionCompleted` | `tool:completed` | `tool_name`, `output`, `is_error`, `duration_ms` | After tool runs |
| `ErrorEvent` | `error` | `message`, `recoverable` | Error occurred |
| `StatusEvent` | — | `message` | Status update |

### System Events

| Event | Key | Payload | Emission Point |
|-------|-----|---------|----------------|
| `SessionOpened` | `session:opened` | `session_key` | Agent.process start |
| `SessionClosed` | `session:closed` | `session_key`, `message_count` | Agent.process end |
| `SubagentSpawned` | `agent:spawned` | `task_id`, `label` | Sub-agent created |
| `SubagentCompleted` | `agent:completed` | `task_id`, `label`, `status` | Sub-agent finished |
| `MemoryConsolidated` | `memory:consolidated` | `session_key`, `messages_archived` | Consolidation done |

## Usage

```python
backend = DefaultObservabilityBackend(
    on_emit=lambda event_type, payload: jsonl_file.write(
        json.dumps({"type": event_type, **payload}) + "\n"
    )
)
emitter = EventEmitter(backend)

# Subscribe to specific events
async def on_tool_completed(event_type, payload):
    print(f"Tool {payload['tool_name']} completed: {payload['is_error']}")

await backend.subscribe("tool:completed", on_tool_completed)
```
