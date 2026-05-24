# Agent -- Harness + Model = Runnable Agent

## What Agent Is

`Agent` is the high-level runnable that combines a fully configured
[Harness](harness.md) with a model name into a single `process(msg)` entry point.
It handles session bookkeeping, memory consolidation, context building, and the
ReAct loop, then returns an `OutboundMessage`.

```python
from agent_harness import Harness, Agent

harness = Harness(provider=provider, sessions=Path("./sessions"))
agent = Agent(harness, model="claude-sonnet-4-20250514")

result = await agent.process(InboundMessage(
    channel="cli", sender_id="user", chat_id="direct", content="Hello!"
))
print(result.content)
```

## `process(msg)` -- The Single Entry Point

`Agent.process()` is the only method you need to call. It drives the full
pipeline and returns an `OutboundMessage` (or `None` on failure).

```python
async def process(self, msg: InboundMessage) -> OutboundMessage | None:
```

### The 8-Step Internal Pipeline

```
process(msg)
  │
  ├─ 1. Concurrency ────────────────── acquire per-session Lock + global Semaphore
  │
  ├─ 2. Session ────────────────────── session = sessions.get_or_create(msg.session_key)
  │                                    (skipped when sessions is None)
  │
  ├─ 3. Persist user message ───────── session.add_message("user", msg.content)
  │                                    sessions.save(session)
  │                                    (skipped when sessions is None)
  │
  ├─ 4. Memory consolidation ──────── maybe_consolidate_by_tokens(session)
  │         (if memory + sessions)     (skipped when memory or sessions is None)
  │
  ├─ 5. Build context ─────────────── harness.on_build_context(msg, history)
  │                                    → [system, *history, user_message]
  │
  ├─ 6. ReAct loop ────────────────── loop.run_react_loop(messages)
  │                                    → TurnResult(final_content, tools_used, messages, usage)
  │
  ├─ 7. Persist turn ──────────────── session.add_message(assistant + tool messages)
  │                                    sessions.save(session)
  │                                    (skipped when sessions is None)
  │
  └─ 8. Return ────────────────────── OutboundMessage(channel, chat_id, content)
                                     or None when final_content is empty
```

### Step-by-Step Detail

**Step 1 -- Concurrency:** Each session has its own `asyncio.Lock` so messages
within a session are processed serially (preserving turn order). A global
`asyncio.Semaphore` limits the total number of concurrent sessions.

**Step 2 -- Session:** Gets an existing session from the `SessionManager` or
creates a new one. The session key is `msg.session_key` (typically
`"channel:chat_id"`).

**Step 3 -- Persist User Message:** Saves the user's message to the session
BEFORE building context. This ensures the message is persisted even if the
ReAct loop fails partway through.

**Step 4 -- Memory Consolidation:** Before running the ReAct loop, the Agent
checks whether the current prompt is approaching the context window limit. If
so, it archives old messages to MEMORY.md and HISTORY.md via the
`MemoryConsolidator`.

**Step 5 -- Build Context:** Delegates to `harness.on_build_context(msg, history)`.
The history is captured **before** the current user message was appended, so
`on_build_context` sees the session state as of the last completed turn.

**Step 6 -- ReAct Loop:** Creates an `AgentLoop` internally (wired with all
callbacks from the harness) and calls `run_react_loop(initial_messages)`.
The loop calls the LLM, executes tools, feeds results back, and repeats until
the LLM returns final text or the iteration limit is reached.

**Step 7 -- Persist Turn:** Saves the new assistant response and all tool
results back to the session file. Tool results are truncated at 16,000
characters to avoid bloating storage.

**Step 8 -- Return:** Wraps the final content in an `OutboundMessage`. Returns
`None` if no content was produced.

## How Agent Creates AgentLoop Internally

The `Agent._build_loop()` method creates an `AgentLoop` with all callbacks wired
to the Harness:

```python
def _build_loop(self) -> AgentLoop:
    harness = self.harness

    async def execute_tool(tool_name, args_dict):
        tool = harness.tools.get(tool_name)
        parsed = tool.input_model.model_validate(args_dict)
        permission = await harness.on_tool_check(tool_name, tool, parsed)
        # ... execute result = await tool.execute(parsed, context)

    callbacks = LoopCallbacks(
        build_messages=lambda *args, **kwargs: [],
        execute_tool=execute_tool,
        get_tool_definitions=lambda: harness.tools.to_api_schema("openai"),
    )

    return AgentLoop(
        provider=harness.provider,
        callbacks=callbacks,
        model=self.model,
        max_iterations=self.max_iterations,
        max_concurrent=0,  # Agent handles concurrency at its own level
    )
```

!!! note "Agent disables AgentLoop's built-in concurrency"
    The Agent manages its own concurrency (per-session locks + global semaphore),
    so it passes `max_concurrent=0` to AgentLoop. This avoids double-gating.

## Concurrency Model

```python
# Per-session lock — serializes messages within one conversation
self._session_locks: dict[str, asyncio.Lock] = {}

# Global semaphore — limits total concurrent sessions
self._concurrency_gate = asyncio.Semaphore(max_concurrent)
```

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `max_concurrent` | 3 | Maximum number of sessions processed simultaneously. `0` disables the gate entirely. |

The Agent acquires both the per-session lock and the global semaphore before
processing:

```python
async with lock, gate:
    # ... process
```

This means:

- Messages for the same session are always processed in order
- Different sessions can proceed in parallel (up to `max_concurrent`)
- If `max_concurrent=0`, no limit is enforced

## What Happens When Sessions/Memory Are None (Stateless Mode)

When `sessions` and/or `memory` are not configured on the Harness, the Agent
skips all persistence-related steps:

| Feature | With Sessions | Without Sessions |
|---------|--------------|-----------------|
| Session get-or-create | Yes | Skipped entirely |
| User message persistence | Saved to JSONL | Not persisted |
| Memory consolidation | Active | Skipped |
| Turn persistence | Saved to JSONL | Not persisted |
| History for context | Loaded from session | Empty `[]` |

The `MemoryConsolidator` is only created when **both** `memory` and `sessions`
are available:

```python
if harness.memory is not None and harness.sessions is not None:
    self._consolidator = MemoryConsolidator(...)
```

!!! tip "When to use stateless mode"
    Stateless mode is ideal for one-shot scripts, testing, and scenarios where
    every interaction is independent (e.g., a stateless webhook handler).

## Error Recovery via `on_error` Callback

When an exception escapes the main pipeline, the Agent catches it and calls
`harness.on_error(exc, "agent.process")`:

```python
except Exception as exc:
    user_msg = await self.harness.on_error(exc, "agent.process")
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content=user_msg or "Sorry, I encountered an error.",
    )
```

The `on_error` callback can:

- Return a user-facing message string (shown to the user)
- Return `None` (the Agent falls back to its default message)
- Log the error, trigger alerts, or attempt cleanup

!!! warning "CancelledError is re-raised"
    `asyncio.CancelledError` is logged and re-raised, not caught by the
    `on_error` handler. This ensures task cancellation propagates correctly.

## Code Examples

### Stateless Agent (no memory, no sessions)

```python
from agent_harness import Harness, Agent, InboundMessage, OutboundMessage
from agent_harness.providers.openai_compat_provider import OpenAICompatProvider

harness = Harness(
    provider=OpenAICompatProvider(api_key="sk-...", model="gpt-4o"),
    tools=["web_search", "web_fetch"],
    permissions="full_auto",
)

agent = Agent(harness, model="gpt-4o")

response = await agent.process(InboundMessage(
    channel="cli", sender_id="user", chat_id="direct",
    content="What is the latest news about AI?",
))
print(response.content)
```

### Sessioned Agent (with persistence)

```python
from pathlib import Path

harness = Harness(
    provider=anthropic_provider,
    tools=ToolRegistry() | [read_tool, write_tool],
    permissions="default",
    memory=Path("~/.my-agent/memory"),
    sessions=Path("~/.my-agent"),
    context_window_tokens=200_000,
    max_completion_tokens=8192,
)

agent = Agent(harness, model="claude-sonnet-4-20250514")

# First turn
r1 = await agent.process(InboundMessage(..., content="My name is Alice."))

# Second turn -- the agent remembers "Alice" from the session history
r2 = await agent.process(InboundMessage(..., content="What's my name?"))
```

### Custom Error Handler

```python
async def my_on_error(exc: Exception, ctx: str) -> str | None:
    if isinstance(exc, ConnectionError):
        return "I'm having trouble connecting. Please try again in a moment."
    log.error("Unhandled error [%s]: %s", ctx, exc)
    return None  # fall back to default message

harness = Harness(
    provider=provider,
    tools=["read_file", "exec"],
    permissions="default",
    on_error=my_on_error,
)

agent = Agent(harness)
```

### Custom Concurrency Limits

```python
# Allow up to 10 concurrent sessions
agent = Agent(harness, max_concurrent=10)

# No concurrency limit (be careful in production)
agent = Agent(harness, max_concurrent=0)
```

---

**Prev:** [Harness Deep Dive](harness.md) | **Next:** [Tools](tools.md)
