# Architecture

llm-harness is built as a **three-layer kernel** with **Protocol-driven adapters**
and **caller-managed state**.

## Three Layers

```
InboundMessage
      │
      ▼
┌──────────────┐
│    Agent     │  pure stateless engine — caller provides Session + cwd
└──────┬───────┘
       │ delegates to AgentLoop after:
       │   session.get_history()
       │   MemoryConsolidator.maybe_consolidate()
       │
       ▼
┌──────────────┐
│  AgentLoop   │  ReAct skeleton — injected with callbacks
└──────┬───────┘
       │ for each iteration:
       │   build_context → LLM API → has tool_calls?
       │   yes → permission check → execute tool → append result → loop
       │   no  → return final_content
       │
       ▼
┌──────────────┐
│   Harness    │  assembler — wires components, returns Agent
└──────────────┘
  constructor receives ALL dependencies explicitly
  _build_consolidator()
  _build_system() — assembles system prompt
  create_agent() — creates AgentLoop + Agent
```

### Harness (Assembler)

`Harness` receives every dependency as a constructor parameter. No defaults
for critical components (provider, model, tools, sandbox). It:

1. Creates `MemoryConsolidator` if `memory` is provided
2. Injects callbacks into `AgentLoop`:
   - `on_build_context` — assembles system message + history + user message
   - `on_tool_check` — wraps `PermissionChecker.evaluate()`
   - `on_error` — logs exceptions
3. Creates `Agent` with the configured loop

### Agent (Pure Engine)

`Agent` is **completely stateless**. Every call to `process()` is self-contained:

```python
async def process(self, msg, *, session, cwd, account="") -> TurnResult:
    history = session.get_history()
    session.add_message("user", msg.content)
    if self._consolidator:
        await self._consolidator.maybe_consolidate(session, account=account)
    result = await self._loop.run(msg, history, cwd=cwd)
    self._save_turn(session, result)
    return result
```

The caller owns session persistence, concurrency control, and workspace resolution.

### AgentLoop (ReAct Skeleton)

`AgentLoop` implements the standard ReAct pattern with callbacks for all
behavior that varies between deployments:

| Callback | Purpose |
|----------|---------|
| `on_build_context` | Assemble messages from the user message + history |
| `on_tool_check` | Permission check before tool execution |
| `on_error` | Error logging / reporting |
| `on_event` | Legacy event emission |
| `emitter` | Structured observability events |

## Data Flow: One Turn

```
1. InboundMessage arrives
2. Agent.process():
   a. Emit SessionOpened
   b. session.get_history() → filtered message list
   c. session.add_message("user", msg.content)
   d. MemoryConsolidator.maybe_consolidate() — if configured
   e. AgentLoop.run():
      - on_build_context(msg, history) → messages list
      - provider.chat_with_retry(messages, tools) → LLMResponse
      - if tool_calls: permission check → execute → append result → loop
      - if no tool_calls: append assistant message, return TurnResult
   f. _save_turn(session, result) — persist assistant + tool messages
   g. Emit SessionClosed
3. Return TurnResult
```

## Adapter Protocols

All backends use Python `Protocol` classes (structural subtyping). Callers
implement the protocol methods without inheriting from a base class:

| Protocol | Methods | Purpose |
|----------|---------|---------|
| `SandboxBackend` | 8 methods | File I/O + subprocess execution |
| `MemoryBackend` | 5 methods | Context retrieval + consolidation |
| `AgentBackend` | 3 methods | Sub-agent lifecycle |
| `SessionBackend` | 3 methods | Session persistence |
| `ObservabilityBackend` | 3 methods | Event pub-sub |
| `SkillLoader` | 1 method | Skill loading |
