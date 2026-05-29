# AgentLoop

`AgentLoop` is the **ReAct skeleton** — the core loop that calls the LLM,
checks for tool calls, executes tools, and assembles the message history.

Source: `llm_harness.core.loop`

## Constructor

```python
AgentLoop(
    provider: LLMProvider,
    tools: ToolRegistry,
    model: str,
    *,
    on_build_context: BuildContextCallback,
    on_tool_check: ToolCheckCallback,
    on_error: ErrorCallback,
    on_event: EventCallback | None = None,
    emitter: EventEmitter | None = None,
    max_iterations: int = 40,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | `LLMProvider` | LLM provider |
| `tools` | `ToolRegistry` | Tool registry |
| `model` | `str` | Model identifier |
| `on_build_context` | `BuildContextCallback` | Assembles messages for the LLM |
| `on_tool_check` | `ToolCheckCallback` | Permission check before tool execution |
| `on_error` | `ErrorCallback` | Error handler |
| `on_event` | `EventCallback` or `None` | Legacy event callback |
| `emitter` | `EventEmitter` or `None` | Structured observability |
| `max_iterations` | `int` | Max ReAct iterations (default: 40) |

## Callback Signatures

```python
# BuildContextCallback
Callable[[msg, history], list[dict] | Awaitable[list[dict]]]

# ToolCheckCallback
Callable[[name: str, tool: BaseTool, args: Any], Any | Awaitable[Any]]

# ErrorCallback
Callable[[exc: Exception, ctx: str], None]

# EventCallback
Callable[[event_type: str, payload: dict], Awaitable[None]]
```

## Methods

### run(msg, history, *, cwd=None) → TurnResult

```python
async def run(
    self,
    msg: Any,
    history: list[dict[str, Any]],
    *,
    cwd: Path | None = None,
) -> TurnResult
```

Executes the ReAct loop:

1. Calls `on_build_context(msg, history)` → messages list
2. Loop (up to `max_iterations`):
   a. `provider.chat_with_retry(messages, tools, model)` → LLMResponse
   b. If no tool_calls: append assistant message, return TurnResult
   c. For each tool call: check → parse → execute → append result
3. If max iterations reached: return "Max iterations reached."

## TurnResult

```python
@dataclass
class TurnResult:
    final_content: str | None = None       # LLM text response
    tools_used: list[str] = field(default_factory=list)  # tool names invoked
    messages: list[dict[str, Any]] = field(default_factory=list)  # full message history
    new_messages_start: int = 0  # index where new messages begin
```

## Constants

- `TOOL_RESULT_MAX_CHARS = 16_000` — tool output truncation limit

## Usage

Direct usage (bypassing Harness):

```python
loop = AgentLoop(
    provider=provider,
    tools=registry,
    model="deepseek-chat",
    on_build_context=lambda m, h: [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": m.content},
    ],
    on_tool_check=lambda n, t, a: type("OK", (), {"allowed": True})(),
    on_error=lambda e, c: None,
)

result = await loop.run(msg, history, cwd=Path("/workspace"))
```
