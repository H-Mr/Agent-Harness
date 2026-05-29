# Async Model

llm-harness is **fully async**. Every I/O operation — LLM API calls, file
reads, subprocess execution, HTTP requests — uses `async`/`await`.

## Why Async?

Agent workloads are **I/O-bound**, not CPU-bound. An agent turn spends most
of its time waiting: LLM API latency (1-30s), network calls (web search,
web fetch), and subprocess I/O. Async lets a single process handle many
concurrent sessions without thread overhead.

## Concurrency Model

llm-harness is **single-threaded, cooperative**:

- One `Agent` instance processes one turn at a time
- Multiple sessions can run concurrently by creating multiple `Agent`
  instances (one per asyncio Task)
- `MemoryConsolidator` uses per-session `asyncio.Lock` with 30s timeout
- `MessageBus` uses bounded `asyncio.Queue(maxsize=10_000)`

## Caller Responsibility

llm-harness does NOT manage concurrency for you. The caller decides:

```python
# Sequential — simple, safe
for msg in messages:
    await agent.process(msg, session=session, cwd=cwd)

# Concurrent — one Agent per task
async def handle_session(session_key):
    agent = harness.create_agent()
    session = await load_session(session_key)
    ...
tasks = [handle_session(k) for k in session_keys]
await asyncio.gather(*tasks)
```

The `Agent` docstring states: "create one Agent per thread, or serialize."

## Avoiding Common Pitfalls

1. **Don't share a Session across concurrent Agent.process() calls.**
   `session.add_message()` and `session.remove_before()` mutate the message
   list. Concurrent access without external locking will corrupt history.

2. **Don't block the event loop.** All framework I/O is async. If your
   custom tool calls a synchronous library, wrap it with
   `asyncio.to_thread()`.

3. **Do set queue limits.** `MessageBus(maxsize=10_000)` prevents memory
   exhaustion under load. The default is already set.

4. **Do handle CancelledError.** The framework propagates
   `asyncio.CancelledError` through `_safe_chat` and `_safe_chat_stream`.
   Task cancellation during an LLM call is safe.

## Timeouts & Retries

| Component | Timeout | Retry |
|-----------|---------|-------|
| LLM API | per-request | 3 retries with 1s/2s/4s backoff |
| Tool execution | per-tool (configurable) | none |
| Memory consolidation lock | 30s | skips turn |
| Subprocess execution | 60s default | none |
| Web fetch | 15s (Jina) / 30s (readability) | falls back to readability |
| MCP tool call | 30s | none |
