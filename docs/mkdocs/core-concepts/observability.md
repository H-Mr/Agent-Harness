# Observability -- Events, Bus, and Tracking

## Overview

The observability system provides structured, real-time visibility into every
operation the agent performs. It is designed around three layers:

1. **Events** -- Typed dataclasses representing every significant occurrence
2. **EventBus** -- An async in-process message bus for real-time subscribers
3. **Tracker** -- A background file writer that drains the bus to JSONL

The system is **opt-in** and **zero-overhead when disabled** -- no events are
emitted, no queues are created, and no files are written unless explicitly
enabled.

## 17 Event Types

Events are divided into two categories: **loop events** (emitted during the
ReAct loop) and **system events** (emitted by infrastructure modules).

### Loop Events

| Event | Trigger | Fields |
|-------|---------|--------|
| `AssistantTextDelta` | Every streaming text chunk from the LLM | `text`, `timestamp` |
| `AssistantTurnComplete` | LLM returns a final text response | `content`, `usage` (token counts), `timestamp` |
| `ToolExecutionStarted` | Before a tool executes | `tool_name`, `tool_input`, `timestamp` |
| `ToolExecutionCompleted` | After a tool finishes | `tool_name`, `output`, `is_error`, `duration_ms`, `timestamp` |
| `ErrorEvent` | Non-fatal error in the loop | `message`, `recoverable`, `timestamp` |
| `StatusEvent` | Generic status update | `message`, `timestamp` |

### System Events

| Event | Trigger | Fields |
|-------|---------|--------|
| `SessionOpened` | A new session is created | `session_key`, `timestamp` |
| `SessionClosed` | A session is closed/expired | `session_key`, `message_count`, `timestamp` |
| `SubagentSpawned` | A sub-agent is launched | `task_id`, `label`, `timestamp` |
| `SubagentCompleted` | A sub-agent finishes | `task_id`, `label`, `status`, `duration_ms`, `timestamp` |
| `CronJobTriggered` | A scheduled job fires | `job_id`, `job_name`, `timestamp` |
| `CronJobCompleted` | A scheduled job finishes | `job_id`, `job_name`, `status`, `duration_ms`, `timestamp` |
| `MemoryConsolidated` | Memory consolidation completes | `session_key`, `messages_archived`, `timestamp` |
| `McpConnectionChanged` | MCP server connects/disconnects | `server_name`, `connected`, `timestamp` |
| `PluginLoaded` | A plugin is loaded | `plugin_name`, `timestamp` |
| `ConfigChanged` | Hot-reloaded config value changes | `key`, `timestamp` |

### Event Structure

All events are frozen dataclasses with a `timestamp` field (ISO 8601 UTC):

```python
@dataclass(frozen=True)
class ToolExecutionStarted:
    tool_name: str
    tool_input: dict[str, Any]
    timestamp: str = field(default_factory=_now)

@dataclass(frozen=True)
class ToolExecutionCompleted:
    tool_name: str
    output: str
    is_error: bool = False
    duration_ms: float | None = None
    timestamp: str = field(default_factory=_now)
```

### Type Unions

```python
LoopEvent = (
    AssistantTextDelta
    | AssistantTurnComplete
    | ToolExecutionStarted
    | ToolExecutionCompleted
    | ErrorEvent
    | StatusEvent
)

SystemEvent = (
    SessionOpened
    | SessionClosed
    | SubagentSpawned
    | SubagentCompleted
    | CronJobTriggered
    | CronJobCompleted
    | MemoryConsolidated
    | McpConnectionChanged
    | PluginLoaded
    | ConfigChanged
)

StreamEvent = LoopEvent | SystemEvent  # Full union
```

## EventBus

The `EventBus` is an async-buffered in-process message bus. Any module can push
events to it, and any module can subscribe to receive them.

### Architecture

```python
class EventBus:
    def __init__(self, maxsize: int = 4096):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._listeners: list[Listener] = []
```

- **Thread-safe** via `asyncio.Queue`
- **Non-blocking emission** -- `emit()` uses `put_nowait()`, drops silently
  when the queue is full
- **Multiple consumers** -- both list-based subscribers and poll-based consumers
  can coexist

### API

| Method | Description |
|--------|-------------|
| `emit(event)` | Push an event. Non-blocking; drops silently if queue is full. |
| `consume()` | Block until an event is available (for poll-based consumers). |
| `subscribe(listener)` | Register a real-time async listener. Returns an unsubscribe function. |
| `pending` | Number of events waiting in the queue. |

### Global Singleton

The global bus is lazily created on first access:

```python
from agent_harness.observability.bus import get_event_bus, emit, is_active

bus = get_event_bus()  # Create or return the singleton

await bus.emit(some_event)  # Push to global bus

# Convenience function (no-op when no consumers exist)
await emit(some_event)

# Check if any consumer is attached
if is_active():
    # Someone is listening
```

### Subscribe/Unsubscribe

```python
from agent_harness.observability.bus import get_event_bus

bus = get_event_bus()

async def log_all_events(event):
    print(f"Event: {type(event).__name__} -> {event}")

# Subscribe
unsubscribe = bus.subscribe(log_all_events)

# ... later ...

# Unsubscribe
unsubscribe()
```

## JSONL Tracker

The `Tracker` is a background consumer that drains the EventBus and writes
events to a JSON Lines file.

```python
from agent_harness.observability.tracker import Tracker

tracker = Tracker(Path("~/.agent-harness/track.jsonl"))
await tracker.start()

# ... run agent ...

await tracker.stop()  # Graceful drain + close
```

### JSONL Format

Each event is serialized as a JSON line:

```jsonl
{"type": "ToolExecutionStarted", "ts": "2026-05-24T10:00:00.123456+00:00", "data": {"tool_name": "read_file", "tool_input": {"file_path": "/tmp/test.txt"}}}
{"type": "ToolExecutionCompleted", "ts": "2026-05-24T10:00:00.234567+00:00", "data": {"tool_name": "read_file", "output": "file contents...", "is_error": false, "duration_ms": 15.3}}
{"type": "AssistantTurnComplete", "ts": "2026-05-24T10:00:01.000000+00:00", "data": {"content": "Here's the result...", "usage": {"prompt_tokens": 150, "completion_tokens": 42}}}
```

The serialization format:

```python
def _serialize(event):
    if dataclasses.is_dataclass(event):
        d = dataclasses.asdict(event)
        ts = d.pop("timestamp", None)
        return json.dumps({
            "type": type(event).__name__,
            "ts": ts,
            "data": d,
        })
    else:
        return json.dumps({
            "type": type(event).__name__,
            "ts": None,
            "data": str(event),
        })
```

### Lifecycle

```python
await tracker.start()   # Creates background asyncio.Task
                        # Opens file for append
                        # Drains events in 1-second polling loop

await tracker.stop()    # Signals task to stop
                        # Drains remaining events
                        # Closes file
```

The tracker uses a 1-second `asyncio.wait_for` timeout on `bus.consume()` to
allow clean shutdown while still being responsive to new events.

### Auto-Start from Config

When `config.observability.track_file` is set, the tracker starts automatically:

```python
from agent_harness.observability.tracker import start_tracker_from_config

config = load_config()  # Has observability.track_file set
tracker = await start_tracker_from_config(config)
# Returns Tracker instance, or None if no track_file configured
```

## Emit Helpers

The `emit_event()` helper provides fire-and-forget emission from any module,
even outside an async context:

```python
from agent_harness.observability.emit_helpers import emit_event
from agent_harness.observability.events import SessionOpened

# Safe to call from anywhere -- never raises
emit_event(SessionOpened(session_key="cli:direct"))
```

The helper:

1. Tries to import the global `emit()` function
2. Gets the running event loop (returns silently if no loop is running)
3. Creates a task to emit the event

This means modules can emit events without needing a reference to the bus
and without worrying about async context availability.

## How Events Are Emitted (The AgentLoop Wiring)

The `AgentLoop` automatically emits events during the ReAct loop:

```python
# In run_react_loop():
for tc in response.tool_calls:
    await self._emit(ToolExecutionStarted(tc.name, tc.arguments))

results = await asyncio.gather(*(execute_tool(...) for tc in response.tool_calls))

for tc, result in zip(response.tool_calls, results):
    duration = (time.monotonic() - start) * 1000
    await self._emit(ToolExecutionCompleted(
        tc.name, str(result), is_error=isinstance(result, BaseException),
        duration_ms=duration,
    ))

# Assistant turn complete
await self._emit(AssistantTurnComplete(final_content, self._last_usage))
```

The `_emit()` method pushes to both:

1. The `LoopCallbacks.on_event` callback (for the Agent to process)
2. The global `EventBus` (for external subscribers and the Tracker)

```python
async def _emit(self, event):
    if self.callbacks.on_event is not None:
        await self.callbacks.on_event(event)
    from agent_harness.observability.bus import get_event_bus
    await get_event_bus().emit(event)
```

## Zero Overhead When Disabled

When no tracker is configured and no subscribers are attached, the event system
adds negligible overhead:

- `get_event_bus()` creates the singleton on first call -- if never called, no
  bus exists
- `emit_event()` checks `is_active()` internally and returns immediately if
  no bus exists
- Events inside `AgentLoop._emit()` wrap the bus call in a try/except -- if
  the bus import fails or no listeners exist, it's a no-op

## Integration with External Monitoring

The JSONL tracker file is designed to be consumed by external tools:

### Log Aggregation

```bash
# Tail live events
tail -f ~/.agent-harness/track.jsonl | jq .

# Filter by event type
jq 'select(.type == "ToolExecutionStarted")' ~/.agent-harness/track.jsonl

# Extract tool usage stats
jq -r 'select(.type == "ToolExecutionCompleted") | [.data.tool_name, .data.duration_ms] | @tsv' \
  ~/.agent-harness/track.jsonl
```

### Prometheus Integration

Subscribe to the EventBus and forward to Prometheus:

```python
from agent_harness.observability.bus import get_event_bus

# Prometheus counters
tool_invocations = Counter("agent_tool_invocations_total", "...", ["tool_name"])
tool_errors = Counter("agent_tool_errors_total", "...", ["tool_name"])
llm_tokens = Counter("agent_llm_tokens_total", "...", ["type"])

async def prometheus_listener(event):
    if isinstance(event, ToolExecutionCompleted):
        tool_invocations.labels(tool_name=event.tool_name).inc()
        if event.is_error:
            tool_errors.labels(tool_name=event.tool_name).inc()
    elif isinstance(event, AssistantTurnComplete):
        llm_tokens.labels(type="prompt").inc(event.usage.get("prompt_tokens", 0))
        llm_tokens.labels(type="completion").inc(event.usage.get("completion_tokens", 0))

bus = get_event_bus()
bus.subscribe(prometheus_listener)
```

### Dashboard Integration

The same subscription pattern works for WebSocket dashboards, Slack
notifications, or any real-time monitoring:

```python
async def dashboard_listener(event):
    if isinstance(event, ToolExecutionStarted):
        await ws.send(json.dumps({
            "type": "tool_start",
            "tool": event.tool_name,
            "input": event.tool_input,
        }))
    elif isinstance(event, ToolExecutionCompleted):
        await ws.send(json.dumps({
            "type": "tool_end",
            "tool": event.tool_name,
            "duration_ms": event.duration_ms,
            "error": event.is_error,
        }))

bus.subscribe(dashboard_listener)
```

## Code Examples

### Minimal: JSONL Tracking

```python
from agent_harness import Harness, Agent, load_config
from agent_harness.harness import Harness
from agent_harness.observability.tracker import start_tracker_from_config

config = load_config()
harness = Harness.from_config(config)

# Tracker auto-starts if track_file is configured
tracker = await start_tracker_from_config(config)

agent = Agent(harness)
response = await agent.process(message)

await tracker.stop()
```

### Custom: Real-Time Monitoring with Subscriptions

```python
from agent_harness.observability.bus import get_event_bus
from agent_harness.observability.events import (
    ToolExecutionStarted,
    ToolExecutionCompleted,
    AssistantTurnComplete,
    ErrorEvent,
)

bus = get_event_bus()

async def monitor(event):
    if isinstance(event, ToolExecutionStarted):
        print(f"[TOOL START] {event.tool_name}")
    elif isinstance(event, ToolExecutionCompleted):
        status = "ERROR" if event.is_error else "OK"
        print(f"[TOOL END] {event.tool_name} -> {status} ({event.duration_ms:.0f}ms)")
    elif isinstance(event, AssistantTurnComplete):
        tokens = event.usage.get("completion_tokens", 0)
        print(f"[LLM] Turn complete: {tokens} completion tokens")
    elif isinstance(event, ErrorEvent):
        print(f"[ERROR] {event.message}")

unsubscribe = bus.subscribe(monitor)
```

### Custom: Instrumenting Custom Code

```python
from agent_harness.observability.emit_helpers import emit_event
from agent_harness.observability.events import StatusEvent

async def my_batch_job():
    for batch in batches:
        emit_event(StatusEvent(f"Processing batch {batch.id}"))
        # ... process ...
        emit_event(StatusEvent(f"Batch {batch.id} complete"))
```

---

**Prev:** [Permissions](permissions.md)
