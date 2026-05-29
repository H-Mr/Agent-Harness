# Agent

`Agent` is the **pure stateless engine** — zero internal state, zero
side-effects. The caller provides `Session`, `cwd`, and optional `account`
on every call.

Source: `llm_harness.core.agent`

## Constructor

```python
Agent(
    loop: AgentLoop,
    consolidator: MemoryConsolidator | None = None,
    emitter: EventEmitter | None = None,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `loop` | `AgentLoop` | Configured ReAct loop |
| `consolidator` | `MemoryConsolidator` or `None` | Memory consolidation engine |
| `emitter` | `EventEmitter` or `None` | Observability event emitter |

## Methods

### process(msg, *, session, cwd, account="") → TurnResult

```python
async def process(
    self,
    msg: InboundMessage,
    *,
    session: Session,
    cwd: Path,
    account: str = "",
) -> TurnResult
```

Runs one complete turn:

1. Emits `SessionOpened` (if emitter configured)
2. Calls `session.get_history()` for message history
3. Calls `session.add_message("user", msg.content)`
4. Runs `MemoryConsolidator.maybe_consolidate()` (if configured)
5. Runs `AgentLoop.run(msg, history, cwd=cwd)`
6. Calls `_save_turn(session, result)` to persist new messages
7. Emits `SessionClosed` (if emitter configured)
8. Returns `TurnResult`

| Parameter | Type | Description |
|-----------|------|-------------|
| `msg` | `InboundMessage` | Incoming user message |
| `session` | `Session` | Session for this conversation |
| `cwd` | `Path` | Working directory for file tools |
| `account` | `str` | Account identifier for tenant isolation |

### close()

```python
async def close(self) -> None
```

Release resources. Currently a no-op (stateless engine). Added for future
compatibility with sub-components that may hold resources.

## Internal Methods

### _save_turn(session, result)

Iterates `result.messages[result.new_messages_start:]` and persists
assistant and tool messages to `session`. Skips:
- Messages that are not `assistant` or `tool` role
- Empty assistant messages without `tool_calls`

## Concurrency

Agent is stateless and safe to call from multiple tasks, provided:
- Each call uses a different `Session` instance
- Or the caller provides external synchronization for shared sessions

## Usage

```python
agent = harness.create_agent()
session = Session(key="user:chat-1")

msg = InboundMessage(channel="cli", sender_id="alice", chat_id="c1",
                     content="What is the capital of France?")
result = await agent.process(msg, session=session, cwd=Path("/workspace"))
print(result.final_content)
# → "The capital of France is Paris."
```
