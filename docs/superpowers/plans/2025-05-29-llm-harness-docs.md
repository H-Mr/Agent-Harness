# llm-harness Framework Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write complete Diátaxis-structured documentation for llm-harness covering all public APIs, architecture, tutorials, and how-to guides, plus a 7-day mastery learning path.

**Architecture:** MkDocs + Material theme. 25 Markdown files across 4 Diátaxis quadrants + 1 structured learning path. English docstrings on all public classes. Chinese narrative throughout. Zero dependencies beyond `mkdocs` and `mkdocs-material`.

**Tech Stack:** Python/mkdocs, mkdocs-material, Markdown

**Source of truth:** `docs/superpowers/specs/2025-05-29-llm-harness-docs-design.md`

---

## File Structure

```
mkdocs.yml                          # CREATE — MkDocs config
docs/
├── index.md                        # CREATE — landing page
├── tutorials/
│   ├── 7-day-mastery.md           # CREATE — 7-day learning path (~500 lines)
│   ├── quickstart.md               # CREATE — 5-min quickstart (~60 lines)
│   └── first-agent.md             # CREATE — full first example (~90 lines)
├── how-to/
│   ├── custom-tool.md             # CREATE — custom tool implementation
│   ├── custom-provider.md         # CREATE — add new LLM provider
│   ├── custom-sandbox.md          # CREATE — custom sandbox backend
│   ├── custom-memory.md           # CREATE — custom memory backend
│   ├── channels.md                # CREATE — WebSocket/CLI channel setup
│   ├── mcp-integration.md         # CREATE — MCP server integration
│   ├── hooks.md                   # CREATE — lifecycle hook configuration
│   ├── skills.md                  # CREATE — custom skill loading
│   └── permissions.md             # CREATE — permission policy config
├── reference/
│   ├── harness.md                 # CREATE — Harness API reference
│   ├── agent.md                   # CREATE — Agent API reference
│   ├── loop.md                    # CREATE — AgentLoop API reference
│   ├── session.md                 # CREATE — Session data model reference
│   ├── tools.md                   # CREATE — Tool system reference
│   ├── providers.md               # CREATE — Provider system reference
│   ├── config.md                  # CREATE — Config schema reference
│   └── events.md                  # CREATE — Observability events reference
└── explanation/
    ├── architecture.md            # CREATE — overall architecture
    ├── dependency-injection.md    # CREATE — DI design rationale
    ├── protocol-design.md         # CREATE — Protocol-driven adapters
    └── async-model.md             # CREATE — async model & concurrency
```

All source files already have class-level docstrings. Tasks that involve docstring changes target specific gaps identified during implementation.

---

### Task 1: MkDocs Configuration

**Files:**
- Create: `mkdocs.yml`
- Create: `docs/index.md`

- [ ] **Step 1: Create mkdocs.yml with Material theme and Diátaxis navigation**

```yaml
site_name: llm-harness
site_description: Pure async, dependency-injected Agent development framework
theme:
  name: material
  features:
    - navigation.sections
    - content.code.copy
  palette:
    - scheme: default
      primary: indigo
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      primary: indigo
      toggle:
        icon: material/brightness-4
        name: Switch to light mode

markdown_extensions:
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.superfences
  - pymdownx.inlinehilite
  - admonition
  - toc:
      permalink: true

nav:
  - Home: index.md
  - Tutorials:
    - 7-Day Mastery: tutorials/7-day-mastery.md
    - Quickstart: tutorials/quickstart.md
    - First Agent: tutorials/first-agent.md
  - How-To Guides:
    - Custom Tool: how-to/custom-tool.md
    - Custom Provider: how-to/custom-provider.md
    - Custom Sandbox: how-to/custom-sandbox.md
    - Custom Memory: how-to/custom-memory.md
    - Channels: how-to/channels.md
    - MCP Integration: how-to/mcp-integration.md
    - Hooks: how-to/hooks.md
    - Skills: how-to/skills.md
    - Permissions: how-to/permissions.md
  - Reference:
    - Harness: reference/harness.md
    - Agent: reference/agent.md
    - AgentLoop: reference/loop.md
    - Session: reference/session.md
    - Tools: reference/tools.md
    - Providers: reference/providers.md
    - Config: reference/config.md
    - Events: reference/events.md
  - Explanation:
    - Architecture: explanation/architecture.md
    - Dependency Injection: explanation/dependency-injection.md
    - Protocol Design: explanation/protocol-design.md
    - Async Model: explanation/async-model.md
```

- [ ] **Step 2: Create docs/index.md landing page**

```markdown
# llm-harness

Pure async, dependency-injected Agent development framework.

## What is llm-harness?

llm-harness is an **Agent engine kernel** — it gives you `Harness` (the assembler),
`Agent` (the stateless engine), and `AgentLoop` (the ReAct skeleton). You bring
your own LLM provider, tools, sandbox, memory backend, and session storage.

**Not** a LangChain wrapper. **Not** a Dify competitor. A focused, ~7,000-line
library that does one thing: run ReAct agent loops with pluggable everything.

## Quick Look

```python
from llm_harness import Harness, Agent, Session, ToolRegistry, Config, load_config

config = load_config("harness.yaml")
harness = Harness(provider=..., model="claude-sonnet-4-6", tools=..., sandbox=...)
agent = harness.create_agent()

session = Session(key="user:chat-1")
result = await agent.process(msg, session=session, cwd=Path("/workspace"))
print(result.final_content)
```

## Where to Start

- **New here?** → [7-Day Mastery Path](tutorials/7-day-mastery.md)
- **Just want to run?** → [Quickstart](tutorials/quickstart.md)
- **Solving a specific problem?** → [How-To Guides](how-to/custom-tool.md)
- **Need API details?** → [Reference](reference/harness.md)
- **Curious about the design?** → [Explanation](explanation/architecture.md)
```

- [ ] **Step 3: Verify mkdocs builds without warnings**

Run: `mkdocs build --strict`
Expected: zero warnings, site/ directory populated

- [ ] **Step 4: Commit**

```bash
git add mkdocs.yml docs/index.md
git commit -m "docs: add mkdocs config and landing page"
```

---

### Task 2: Explanation — Architecture & Dependency Injection

**Files:**
- Create: `docs/explanation/architecture.md`
- Create: `docs/explanation/dependency-injection.md`

- [ ] **Step 1: Create docs/explanation/architecture.md**

```markdown
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
```

- [ ] **Step 2: Create docs/explanation/dependency-injection.md**

```markdown
# Dependency Injection

llm-harness takes a strong stance: **every dependency is explicit, every
parameter is required.**

## Why No Defaults?

```python
# llm-harness style — everything explicit
harness = Harness(
    provider=OpenAICompatProvider(api_key="sk-xxx"),
    model="deepseek-chat",
    tools=my_tools,        # required
    sandbox=my_sandbox,    # required
    memory=my_memory,      # optional — explicit None
    permissions=my_perms,  # optional — explicit None
)
```

This is deliberate:

1. **No hidden coupling.** You can see every component the Agent depends on
   at the call site.
2. **No filesystem side-effects.** The constructor never reads files,
   environment variables, or global config.
3. **Testable.** Every dependency is replaceable with a mock.
4. **Auditable.** Static analysis tools can verify all dependencies are
   provided.

## Callback Injection

Behavior that varies between deployments is injected as callbacks, not
subclass overrides:

```python
loop = AgentLoop(
    on_build_context=lambda msg, history: [
        {"role": "system", "content": "You are helpful."},
        *history,
        {"role": "user", "content": msg.content},
    ],
    on_tool_check=lambda name, tool, args: (
        permission_checker.evaluate(name, ...)
    ),
    on_error=lambda exc, ctx: logger.exception("Error in %s", ctx),
)
```

This means you can change the system prompt, permission logic, or error
handling without subclassing `AgentLoop`.

## Constructor vs Factory

`Harness` is the only "factory" in the framework. `ToolFactory` is a
convenience for building the standard 15 tools with injected dependencies.
For custom setups, you can bypass both and wire `AgentLoop` + `Agent` directly:

```python
loop = AgentLoop(provider=..., tools=..., model=...,
                 on_build_context=..., on_tool_check=..., on_error=...)
agent = Agent(loop=loop)
result = await agent.process(msg, session=session, cwd=cwd)
```

## Comparison

| Pattern | llm-harness | Typical Framework |
|---------|-------------|-------------------|
| Provider | Constructor param | Env var / global singleton |
| Tools | Injected `ToolRegistry` | Auto-discovered / decorator-registered |
| Config | Pydantic model passed in | YAML file read internally |
| Session | Caller passes `Session` | Framework manages lifecycle |
| Workspace | Caller passes `cwd: Path` | Framework resolves internally |
```

- [ ] **Step 3: Commit**

```bash
git add docs/explanation/architecture.md docs/explanation/dependency-injection.md
git commit -m "docs: add architecture and dependency injection explanation"
```

---

### Task 3: Explanation — Protocol Design & Async Model

**Files:**
- Create: `docs/explanation/protocol-design.md`
- Create: `docs/explanation/async-model.md`

- [ ] **Step 1: Create docs/explanation/protocol-design.md**

```markdown
# Protocol Design

All backend adapters in llm-harness use Python `Protocol` classes from
`typing.Protocol`. This is a deliberate architectural choice.

## Structural vs Nominal Subtyping

```python
# Protocol (structural) — matches any object with these methods
class SandboxBackend(Protocol):
    async def read_file(self, session_key: str, path: str) -> str: ...
    async def write_file(self, session_key: str, path: str, content: str) -> None: ...

# ABC (nominal) — requires explicit inheritance
class SandboxBackend(ABC):
    @abstractmethod
    async def read_file(self, session_key: str, path: str) -> str: ...
```

With `Protocol`, you can implement `SRTSandboxBackend` without importing or
inheriting from `SandboxBackend`. The type checker validates compatibility
at the usage site, not the definition site.

## Why Protocol?

1. **Zero coupling.** Your backend implementation has no import dependency
   on llm-harness. You can put it in a separate package.
2. **Minimal interface.** Each Protocol only declares the methods the
   framework actually calls. No `close()`, `connect()`, or `configure()`
   unless the framework needs them.
3. **Easy mocking.** In tests, `AsyncMock()` satisfies any Protocol.

## All Core Protocols

### SandboxBackend (8 methods)

```
create_session(session_key) → SandboxSession
destroy_session(session_key)
read_file(session_key, path) → str
write_file(session_key, path, content)
list_dir(session_key, path) → list[str]
glob(session_key, pattern) → list[str]
grep(session_key, pattern, path) → list[str]
execute(session_key, command, *, cwd, env, timeout) → ExecResult
```

### MemoryBackend (5 methods)

```
get_context(namespace) → str
read_section(namespace, section) → str
append_section(namespace, section, entry)
add_history(namespace, entry)
consolidate(namespace, messages, provider, model) → bool
```

### AgentBackend (3 methods)

```
spawn(config, origin_session_key, origin_account) → SpawnResult
send_message(agent_id, message) → bool
stop(agent_id) → bool
```

### SessionBackend (3 methods)

```
load(session_key) → dict | None
save(session_key, state)
list_keys() → list[str]
```

### ObservabilityBackend (3 methods)

```
emit(event_type, payload)
subscribe(event_type, handler)
unsubscribe(event_type, handler)
```

## Adding a New Backend

Implement the Protocol methods. No imports from llm-harness needed:

```python
class MySandbox:
    async def create_session(self, session_key: str) -> SandboxSession:
        return SandboxSession(session_key=session_key, volume_path="/tmp", sandbox_id="my")
    # ... implement remaining 7 methods

# Usage
harness = Harness(..., sandbox=MySandbox())
```

The type checker verifies `MySandbox` satisfies `SandboxBackend` at the
`Harness(...)` call site.
```

- [ ] **Step 2: Create docs/explanation/async-model.md**

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add docs/explanation/protocol-design.md docs/explanation/async-model.md
git commit -m "docs: add protocol design and async model explanation"
```

---

### Task 4: Reference — Harness, Agent, AgentLoop

**Files:**
- Create: `docs/reference/harness.md`
- Create: `docs/reference/agent.md`
- Create: `docs/reference/loop.md`

- [ ] **Step 1: Create docs/reference/harness.md**

```markdown
# Harness

`Harness` is the **assembler** — it receives all dependencies, creates the
`MemoryConsolidator` (if memory is configured), injects callbacks into
`AgentLoop`, and returns a ready-to-use `Agent`.

Source: `llm_harness.core.harness`

## Constructor

```python
Harness(
    *,
    provider: LLMProvider,          # required
    model: str,                     # required
    tools: ToolRegistry,            # required
    sandbox: SandboxBackend,        # required
    memory: MemoryBackend | None = None,
    swarm: Any = None,
    permissions: PermissionChecker | None = None,
    skills: SkillRegistry | None = None,
    observability: ObservabilityBackend | None = None,
    system_prompt: str = "",
    context_window_tokens: int = 64_000,
    max_completion_tokens: int = 4096,
)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `provider` | `LLMProvider` | Yes | LLM provider instance |
| `model` | `str` | Yes | Model identifier |
| `tools` | `ToolRegistry` | Yes | Tool registry with registered tools |
| `sandbox` | `SandboxBackend` | Yes | Sandbox for file I/O and exec |
| `memory` | `MemoryBackend` | No | Memory backend for consolidation |
| `swarm` | `Any` | No | Sub-agent backend |
| `permissions` | `PermissionChecker` | No | Permission checker |
| `skills` | `SkillRegistry` | No | Skill registry (defaults to empty) |
| `observability` | `ObservabilityBackend` | No | Event backend |
| `system_prompt` | `str` | No | Custom system prompt (default: "You are a helpful AI assistant.") |
| `context_window_tokens` | `int` | No | Context window size for consolidation |
| `max_completion_tokens` | `int` | No | Max completion tokens for consolidation |

## Methods

### create_agent()

```python
def create_agent(self) -> Agent
```

Creates and returns a configured `Agent` instance. The returned Agent has:
- An `AgentLoop` with callbacks wired to `_build_system`, permissions, and error logging
- A `MemoryConsolidator` (if `memory` was provided)
- An `EventEmitter` (if `observability` was provided)

## Internal Methods

### _build_system(msg)

Assembles the system prompt from:
1. `system_prompt` (or default)
2. Current UTC time
3. Available sub-agent definitions (from swarm)
4. Available skills (from skill registry)

Returns `[{"role": "system", "content": "..."}]`

### _build_consolidator()

Creates `MemoryConsolidator` with `context_window_tokens` and
`max_completion_tokens` from the constructor. Called during `__init__`
only if `memory` is provided.

## Usage

```python
from llm_harness import Harness

harness = Harness(
    provider=OpenAICompatProvider(api_key="sk-xxx"),
    model="deepseek-chat",
    tools=my_tools,
    sandbox=SRTSandboxBackend("/workspace"),
    memory=TencentDBMemoryBackend(),
    permissions=PermissionChecker(PermissionSettings()),
    system_prompt="You are a coding assistant.",
)
agent = harness.create_agent()
```
```

- [ ] **Step 2: Create docs/reference/agent.md**

```markdown
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
```

- [ ] **Step 3: Create docs/reference/loop.md**

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add docs/reference/harness.md docs/reference/agent.md docs/reference/loop.md
git commit -m "docs: add Harness, Agent, AgentLoop API reference"
```

---

### Task 5: Reference — Session, Tools, Providers

**Files:**
- Create: `docs/reference/session.md`
- Create: `docs/reference/tools.md`
- Create: `docs/reference/providers.md`

- [ ] **Step 1: Create docs/reference/session.md**

```markdown
# Session

`Session` is a pure data structure — no I/O, no persistence. It holds the
conversation messages and consolidation offset.

Source: `llm_harness.core.session`

## Fields

```python
@dataclass
class Session:
    key: str                                          # unique session identifier
    messages: list[dict[str, Any]]                    # full message history
    created_at: datetime                              # creation timestamp (UTC)
    updated_at: datetime                              # last update timestamp (UTC)
    metadata: dict[str, Any]                          # arbitrary metadata
    last_consolidated: int = 0                        # index offset for consolidation
```

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `channel` | `str \| None` | First component of `key` when formatted as `channel:chat_id` |
| `chat_id` | `str \| None` | Second component of `key` when formatted as `channel:chat_id` |

## Methods

### add_message(role, content, **kwargs)

```python
def add_message(self, role: str, content: str, **kwargs: Any) -> None
```

Appends a message to `messages` with auto-generated `timestamp` and any
extra kwargs (e.g., `tool_calls`, `tool_call_id`, `name`).

### get_history(max_messages=500) → list[dict[str, Any]]

Returns recent unconsolidated messages, aligned to start at a `user` message.
Skips messages before `last_consolidated`. Returns at most `max_messages`.
Forward-searches to the nearest `role == "user"` message to ensure the LLM
never receives orphaned assistant/tool messages.

### remove_before(idx)

```python
def remove_before(self, idx: int) -> None
```

Removes messages before `idx` and adjusts `last_consolidated` offset.
Called by `MemoryConsolidator` after successful consolidation.

### to_state() → dict[str, Any]

Returns serializable state: `{"messages": ..., "metadata": ..., "last_consolidated": ...}`

## Usage

```python
session = Session(key="alice:chat1")
session.add_message("user", "Hello")
session.add_message("assistant", "Hi there!", tool_calls=[...])
session.add_message("tool", "result", tool_call_id="c1", name="read_file")

history = session.get_history()
# → last two messages starting from nearest user message

state = session.to_state()
# → persist this dict
```
```

- [ ] **Step 2: Create docs/reference/tools.md**

```markdown
# Tools

The tool system provides the interface between LLM tool-call requests and
actual execution.

Source: `llm_harness.core.tools`

## Core Classes

### BaseTool (ABC)

```python
class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult: ...
    def is_read_only(self, arguments: BaseModel) -> bool: ...
    def to_api_schema(self, api_format: str = "anthropic") -> dict[str, Any]: ...
    def to_openai_schema(self) -> dict[str, Any]: ...
```

### ToolRegistry

```python
class ToolRegistry:
    def register(self, tool: BaseTool) -> None: ...
    def unregister(self, name: str) -> None: ...
    def has(self, name: str) -> bool: ...
    def get(self, name: str) -> BaseTool | None: ...
    def list_tools(self) -> list[BaseTool]: ...
    def to_api_schema(self, api_format: str = "anthropic") -> list[dict[str, Any]]: ...
```

### ToolExecutionContext

```python
@dataclass
class ToolExecutionContext:
    cwd: Path                              # working directory
    metadata: dict[str, Any]               # session_key, account, etc.
```

### ToolResult

```python
@dataclass(frozen=True)
class ToolResult:
    output: str                            # tool output text
    is_error: bool = False                 # whether execution failed
    metadata: dict[str, Any]               # arbitrary metadata
```

### ToolFactory

```python
class ToolFactory:
    def __init__(self, *, sandbox=None, memory=None, swarm=None, bus=None, skills=None, harness_tool_names=None): ...
    def register(self, name: str, builder: Callable[[], BaseTool | None]) -> None: ...
    def build(self, name: str) -> BaseTool | None: ...
```

## Built-in Tools

| Tool | Name | Dependencies | Read-Only |
|------|------|-------------|-----------|
| ReadFileTool | `read_file` | sandbox | Yes |
| WriteFileTool | `write_file` | sandbox | No |
| EditFileTool | `edit_file` | sandbox | No |
| ExecTool | `exec` | sandbox | No |
| GlobTool | `glob` | sandbox | Yes |
| GrepTool | `grep` | sandbox | Yes |
| WebSearchTool | `web_search` | none | Yes |
| WebFetchTool | `web_fetch` | none | Yes |
| MemoryReadTool | `memory_read` | memory | Yes |
| MemoryWriteTool | `memory_write` | memory | No |
| AgentTool | `agent` | swarm, bus | No |
| SendMessageTool | `send_message` | swarm | No |
| TaskStopTool | `task_stop` | swarm | No |
| SkillTool | `skill` | skills | Yes |
| AskUserQuestionTool | `ask_user_question` | none | No |

## Implementing a Custom Tool

```python
from pydantic import BaseModel, Field
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult

class GreetInput(BaseModel):
    name: str = Field(description="Name to greet")

class GreetTool(BaseTool):
    name: ClassVar[str] = "greet"
    description: ClassVar[str] = "Greet someone by name."
    input_model: ClassVar[type[BaseModel]] = GreetInput

    async def execute(self, args: GreetInput, ctx: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"Hello, {args.name}!")

    @staticmethod
    def is_read_only(args: GreetInput) -> bool:
        return True
```
```

- [ ] **Step 3: Create docs/reference/providers.md**

```markdown
# Providers

The provider system abstracts LLM API calls behind a unified interface.

Source: `llm_harness.adapters.providers`

## LLMProvider (ABC)

```python
class LLMProvider(ABC):
    # Abstract methods (subclass must implement)
    async def chat(self, messages, tools=None, model=None, ...) -> LLMResponse: ...
    def get_default_model(self) -> str: ...

    # Template methods (retry logic built-in)
    async def chat_with_retry(self, messages, tools=None, model=None, ...) -> LLMResponse: ...
    async def chat_stream_with_retry(self, messages, tools=None, model=None, ...) -> LLMResponse: ...

    # Streaming (override for native support)
    async def chat_stream(self, messages, tools=None, model=None, ...,
                          on_content_delta=None) -> LLMResponse: ...
```

## LLMResponse

```python
@dataclass
class LLMResponse:
    content: str | None                     # text response
    tool_calls: list[ToolCallRequest]       # tool call list
    finish_reason: str = "stop"             # stop / tool_calls / error / length
    usage: dict[str, int]                   # token usage stats
    reasoning_content: str | None = None    # reasoning (DeepSeek-R1, Kimi, etc.)
    thinking_blocks: list[dict] | None = None  # Anthropic extended thinking

    @property
    def has_tool_calls(self) -> bool: ...
```

## ToolCallRequest

```python
@dataclass
class ToolCallRequest:
    id: str                                 # unique tool call ID
    name: str                               # tool name
    arguments: dict[str, Any]               # tool arguments
    extra_content: dict | None = None       # provider-specific extras (e.g., Gemini)
    provider_specific_fields: dict | None = None    # non-standard tool_call fields
    function_provider_specific_fields: dict | None = None  # non-standard function fields

    def to_openai_tool_call(self) -> dict: ...
```

## Retry Strategy

| Condition | Action |
|-----------|--------|
| Transient error (429, 5xx, timeout, etc.) | Retry with 1s/2s/4s backoff |
| Non-transient error + image content | Strip images, retry once |
| Non-transient error, no images | Return error response |

## Built-in Providers

### OpenAICompatProvider

Covers all OpenAI-compatible APIs (OpenAI, DeepSeek, DashScope, OpenRouter,
Ollama, vLLM, Gemini, Zhipu, Moonshot, Mistral, and more).

```python
provider = OpenAICompatProvider(
    api_key="sk-xxx",
    api_base="https://api.deepseek.com",
    default_model="deepseek-chat",
)
```

### AnthropicProvider

Native Anthropic SDK integration with prompt caching and extended thinking.

```python
provider = AnthropicProvider(
    api_key="sk-ant-xxx",
    default_model="claude-sonnet-4-20250514",
)
```

## ProviderSpec Registry

29 providers defined in `llm_harness.adapters.providers.registry.PROVIDERS`.

```python
from llm_harness.adapters.providers.registry import detect_provider, instantiate_provider

spec = detect_provider(model="deepseek-chat")
provider = instantiate_provider(spec)
```
```

- [ ] **Step 4: Commit**

```bash
git add docs/reference/session.md docs/reference/tools.md docs/reference/providers.md
git commit -m "docs: add Session, Tools, Providers API reference"
```

---

### Task 6: Reference — Config & Events

**Files:**
- Create: `docs/reference/config.md`
- Create: `docs/reference/events.md`

- [ ] **Step 1: Create docs/reference/config.md**

```markdown
# Config

Configuration schema and loading. Pydantic models with env-var override support.

Source: `llm_harness.config`

## Config Model

```python
class Config(BaseModel):
    agent: AgentConfig
    tools: ToolsConfig
    permission: PermissionConfig
    sandbox: SandboxConfig
    memory: MemoryConfig
    observability: ObservabilityConfig
    channels: list[ChannelConfig]
    workspace: str = "."

    @property
    def workspace_path(self) -> Path: ...
```

## Sub-models

### AgentConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `str` | `"claude-sonnet-4-6"` | Model identifier |
| `provider` | `str` | `"auto"` | Provider name or "auto" |
| `api_key` | `str` | `""` | API key (prefer env var) |
| `api_base` | `str` | `""` | API base URL |
| `max_tokens` | `int` | `4096` | Max completion tokens |
| `context_window_tokens` | `int` | `64000` | Context window size |

### ToolsConfig

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | `list[str]` | Tools to enable (15 default tools) |
| `disabled` | `list[str]` | Tools to explicitly disable |

### PermissionConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `str` | `"default"` | `default` / `plan` / `full_auto` |
| `allowed_tools` | `list[str]` | `[]` | Explicit tool allowlist |
| `denied_tools` | `list[str]` | `[]` | Explicit tool denylist |

### SandboxConfig

| Field | Type | Default |
|-------|------|---------|
| `backend` | `str` | `"srt"` |

### MemoryConfig

| Field | Type | Default |
|-------|------|---------|
| `backend` | `str` | `"tencentdb"` |
| `base_url` | `str` | `"http://localhost:8420"` |

### ObservabilityConfig

| Field | Type | Default |
|-------|------|---------|
| `track_file` | `str` | `""` |

### ChannelConfig

| Field | Type | Default |
|-------|------|---------|
| `type` | `str` | `"cli"` |
| `settings` | `dict` | `{}` |

## Loading

```python
from llm_harness.config import load_config, Config

# From YAML
config = load_config("harness.yaml")

# With overrides
config = load_config("harness.yaml", model="claude-sonnet-4-6", provider="anthropic")

# From env
# LLM_HARNESS_MODEL=deepseek-chat LLM_HARNESS_API_KEY=sk-xxx
config = load_config()
```

### Priority (highest to lowest)

1. CLI arguments (`model=`, `provider=`)
2. Environment variables (`LLM_HARNESS_MODEL`, `LLM_HARNESS_API_KEY`, etc.)
3. YAML config file
4. Pydantic defaults

### Environment Variables

| Variable | Maps To |
|----------|---------|
| `LLM_HARNESS_CONFIG` | Config file path |
| `LLM_HARNESS_MODEL` | `agent.model` |
| `LLM_HARNESS_PROVIDER` | `agent.provider` |
| `LLM_HARNESS_API_KEY` | `agent.api_key` |
| `LLM_HARNESS_API_BASE` | `agent.api_base` |
| `LLM_HARNESS_WORKSPACE` | `workspace` |
```

- [ ] **Step 2: Create docs/reference/events.md**

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add docs/reference/config.md docs/reference/events.md
git commit -m "docs: add Config and Events API reference"
```

---

### Task 7: Tutorials — Quickstart & First Agent

**Files:**
- Create: `docs/tutorials/quickstart.md`
- Create: `docs/tutorials/first-agent.md`

- [ ] **Step 1: Create docs/tutorials/quickstart.md**

```markdown
# Quickstart

Get an Agent running in 5 minutes.

## 1. Install

```bash
pip install llm-harness[openai]
```

## 2. Set your API key

```bash
export LLM_HARNESS_API_KEY=sk-your-key-here
```

## 3. Create the Agent

```python
import os
import asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    # 1. Create provider
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )

    # 2. Set up sandbox and tools
    sandbox = SRTSandboxBackend(Path("./workspace"))
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "web_search"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    # 3. Assemble
    harness = Harness(
        provider=provider,
        model="deepseek-chat",
        tools=tools,
        sandbox=sandbox,
    )
    agent = harness.create_agent()

    # 4. Create a session and send a message
    session = Session(key="quickstart:chat1")
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="chat1",
                         content="What is 2+2?")
    result = await agent.process(msg, session=session, cwd=Path("./workspace"))
    print(result.final_content)

asyncio.run(main())
```

## 4. Run it

```bash
python quickstart.py
# → 2+2 equals 4.
```

## Next Steps

- [7-Day Mastery Path](7-day-mastery.md) — structured learning
- [First Agent](first-agent.md) — deeper dive with more tools
```

- [ ] **Step 2: Create docs/tutorials/first-agent.md**

```markdown
# Your First Agent

A complete example: file operations, web search, and multi-turn conversation.

## Setup

```python
import os, asyncio, tempfile
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path(tempfile.mkdtemp())

    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "exec", "glob", "grep", "web_search"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    harness = Harness(
        provider=provider, model="deepseek-chat",
        tools=tools, sandbox=sandbox,
        system_prompt="You are a coding assistant. Be concise.",
    )
    agent = harness.create_agent()
    session = Session(key="demo:chat1")

    # Turn 1: create a file
    msg1 = InboundMessage("cli", "alice", "c1",
        'Create a Python file called hello.py that prints "Hello from llm-harness!"')
    r1 = await agent.process(msg1, session=session, cwd=ws)
    print("Turn 1:", r1.final_content[:100])

    # Turn 2: run it
    msg2 = InboundMessage("cli", "alice", "c1", "Now run hello.py and tell me the output")
    r2 = await agent.process(msg2, session=session, cwd=ws)
    print("Turn 2:", r2.final_content[:100])

    print(f"\nMessages in session: {len(session.messages)}")
    print(f"Tools used: {r2.tools_used}")

asyncio.run(main())
```

## What Happens

1. `Harness` assembles the Agent with the provider, tools, sandbox, and system prompt
2. Turn 1: Agent receives the message → LLM decides to use `write_file` → tool executes → LLM confirms
3. Turn 2: Agent receives the follow-up → LLM uses `exec` to run `python hello.py` → LLM reports the output
4. Session accumulates all messages across turns
```

- [ ] **Step 3: Commit**

```bash
git add docs/tutorials/quickstart.md docs/tutorials/first-agent.md
git commit -m "docs: add quickstart and first-agent tutorials"
```

---

### Task 8: Tutorials — 7-Day Mastery Path

**Files:**
- Create: `docs/tutorials/7-day-mastery.md`

This is the largest single document (~500 lines). Each day follows the spec design:
Theory (concepts + code reading) → Hands-on (exercises with actual code) → Deliverable
(runnable script) → Checkpoint (verification command).

Write the complete document based on the spec at
`docs/superpowers/specs/2025-05-29-llm-harness-docs-design.md`, Section "7-Day Mastery Module".

Cover:
- Day 1: Installation, three-layer model, first Agent (hello_agent.py)
- Day 2: Tool system quintuple, 5 exercises, tool_lab.py
- Day 3: Session/memory deep dive, 5 exercises, session_lab.py
- Day 4: Provider/config, 7 exercises, config_lab.py + provider_test.py
- Day 5: MCP/Skills/Hooks/Channels, 5 exercises, extended_agent.py
- Day 6: Observability/permissions/swarm, 5 exercises, 3 deliverables
- Day 7: Custom backends + production, 5 exercises, 4 deliverables

Each day must have:
- Theory section with concepts and framework internals
- 4-7 hands-on exercises with complete code snippets
- Deliverable file name and verification command

- [ ] **Step 1: Write docs/tutorials/7-day-mastery.md**

Follow this structure for each day:

```markdown
# 7-Day Mastery Path

## Day N: Title (duration)

### Theory

... concepts, architecture, internals ...

### Hands-On

#### Exercise 1: Title
```python
# complete runnable code
```

#### Exercise 2: Title
...

### Deliverable

- `filename.py` — description
- Verify: `LLM_HARNESS_API_KEY=sk-xxx python filename.py` → expected output

### Post-Lesson Reflection

- question to think about
```

- [ ] **Step 2: Commit**

```bash
git add docs/tutorials/7-day-mastery.md
git commit -m "docs: add 7-day mastery learning path"
```

---

### Task 9: How-To Guides — Custom Tool & Provider

**Files:**
- Create: `docs/how-to/custom-tool.md`
- Create: `docs/how-to/custom-provider.md`

- [ ] **Step 1: Create docs/how-to/custom-tool.md**

Write a task-oriented guide with:
1. Goal statement
2. Prerequisites
3. Step-by-step: subclass BaseTool → define input model → implement execute() → register
4. Complete working example
5. Testing the tool

- [ ] **Step 2: Create docs/how-to/custom-provider.md**

Write a task-oriented guide with:
1. Goal statement
2. Prerequisites
3. Step-by-step: create ProviderSpec → register → instantiate
4. Example: adding a private LLM gateway
5. Testing with a real API call

- [ ] **Step 3: Commit**

```bash
git add docs/how-to/custom-tool.md docs/how-to/custom-provider.md
git commit -m "docs: add custom tool and custom provider how-to guides"
```

---

### Task 10: How-To Guides — Sandbox, Memory, Channels

**Files:**
- Create: `docs/how-to/custom-sandbox.md`
- Create: `docs/how-to/custom-memory.md`
- Create: `docs/how-to/channels.md`

- [ ] **Step 1: Create docs/how-to/custom-sandbox.md**

Guide for implementing SandboxBackend Protocol (8 methods). Example: a simple LocalSandboxBackend.

- [ ] **Step 2: Create docs/how-to/custom-memory.md**

Guide for implementing MemoryBackend Protocol (5 methods). Example: RedisMemoryBackend.

- [ ] **Step 3: Create docs/how-to/channels.md**

Guide for configuring WebSocket and CLI channels. Covers auth_callback, allow_from, streaming, ChannelManager.

- [ ] **Step 4: Commit**

```bash
git add docs/how-to/custom-sandbox.md docs/how-to/custom-memory.md docs/how-to/channels.md
git commit -m "docs: add sandbox, memory, and channels how-to guides"
```

---

### Task 11: How-To Guides — MCP, Hooks, Skills, Permissions

**Files:**
- Create: `docs/how-to/mcp-integration.md`
- Create: `docs/how-to/hooks.md`
- Create: `docs/how-to/skills.md`
- Create: `docs/how-to/permissions.md`

- [ ] **Step 1: Create docs/how-to/mcp-integration.md**

Guide for connecting MCP servers (stdio, SSE, streamable HTTP). Example with a real MCP filesystem server.

- [ ] **Step 2: Create docs/how-to/hooks.md**

Guide for configuring lifecycle hooks (command, http, prompt, agent types). Example: PreToolUse validation hook.

- [ ] **Step 3: Create docs/how-to/skills.md**

Guide for creating and loading skills. Create a SKILL.md → DirectorySkillLoader → SkillRegistry → Agent uses skill tool.

- [ ] **Step 4: Create docs/how-to/permissions.md**

Guide for configuring permission modes and rules. Examples: denylist, allowlist, path rules, SENSITIVE_PATH_PATTERNS.

- [ ] **Step 5: Commit**

```bash
git add docs/how-to/mcp-integration.md docs/how-to/hooks.md docs/how-to/skills.md docs/how-to/permissions.md
git commit -m "docs: add MCP, hooks, skills, and permissions how-to guides"
```

---

### Task 12: Docstring Audit & Supplement

**Files:**
- Modify: `src/llm_harness/core/harness.py` — verify Harness class docstring covers all params
- Modify: `src/llm_harness/core/agent.py` — verify Agent class docstring
- Modify: `src/llm_harness/core/loop.py` — verify AgentLoop + TurnResult docstrings
- Modify: `src/llm_harness/core/session/session.py` — verify Session docstring
- Modify: `src/llm_harness/core/tools/base.py` — verify ToolRegistry, BaseTool, ToolExecutionContext, ToolResult docstrings
- Modify: `src/llm_harness/core/tools/factory.py` — verify ToolFactory docstring
- Modify: `src/llm_harness/adapters/providers/base.py` — verify LLMProvider, LLMResponse docstrings
- Modify: `src/llm_harness/adapters/providers/registry.py` — verify ProviderSpec, detect_provider, instantiate_provider docstrings
- Modify: `src/llm_harness/core/bus/queue.py` — verify MessageBus docstring
- Modify: `src/llm_harness/core/bus/events.py` — verify InboundMessage, OutboundMessage docstrings
- Modify: `src/llm_harness/core/permissions/checker.py` — verify PermissionChecker docstring
- Modify: `src/llm_harness/adapters/observability/emit_helpers.py` — verify EventEmitter docstring
- Modify: `src/llm_harness/adapters/observability/default.py` — verify DefaultObservabilityBackend docstring
- Modify: `src/llm_harness/adapters/memory/consolidator.py` — verify MemoryConsolidator docstring
- Modify: `src/llm_harness/extensions/channels/manager.py` — verify ChannelManager docstring
- Modify: `src/llm_harness/extensions/channels/base.py` — verify BaseChannel docstring
- Modify: `src/llm_harness/extensions/hooks/executor.py` — verify HookExecutor docstring
- Modify: `src/llm_harness/extensions/skills/registry.py` — verify SkillRegistry docstring
- Modify: `src/llm_harness/extensions/skills/loader.py` — verify DirectorySkillLoader docstring
- Modify: `src/llm_harness/extensions/mcp/client.py` — verify MCPToolWrapper, MCPServerConnection docstrings
- Modify: `src/llm_harness/core/swarm/subprocess.py` — verify SubprocessBackend docstring
- Modify: `src/llm_harness/core/swarm/mailbox.py` — verify Mailbox docstring

- [ ] **Step 1: Audit each file — read class docstring, verify it covers: what the class does, constructor parameters, key methods, usage example**

For each file above, read the class docstring. The codebase has docstrings on most classes already. Only add missing parameter descriptions and `Usage:` sections where absent.

- [ ] **Step 2: Run mkdocs build to verify no broken references**

Run: `mkdocs build --strict`
Expected: zero warnings

- [ ] **Step 3: Run test suite to verify no import/docstring regressions**

Run: `pytest tests/ -x -q`
Expected: all passing

- [ ] **Step 4: Commit**

```bash
git add -u src/
git commit -m "docs: audit and supplement public API docstrings"
```

---

### Task 13: Final Verification

- [ ] **Step 1: Full mkdocs build**

Run: `mkdocs build --strict`
Expected: BUILD SUCCESS, zero warnings

- [ ] **Step 2: Check nav completeness**

Verify all 25 pages in `mkdocs.yml` nav exist as files:
```bash
find docs -name "*.md" | sort
```
Expected: index.md + 3 tutorials + 9 how-to + 8 reference + 4 explanation = 25 files

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: all tests pass (293+ unit, 3 E2E if API key set)

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "docs: finalize llm-harness framework documentation"
```
```

---

## Self-Review

**Spec coverage check:**

| Spec Section | Task Coverage |
|---|---|
| mkdocs.yml + index.md | Task 1 |
| Architecture explanation | Task 2 |
| Dependency injection explanation | Task 2 |
| Protocol design explanation | Task 3 |
| Async model explanation | Task 3 |
| Harness reference | Task 4 |
| Agent reference | Task 4 |
| AgentLoop reference | Task 4 |
| Session reference | Task 5 |
| Tools reference | Task 5 |
| Providers reference | Task 5 |
| Config reference | Task 6 |
| Events reference | Task 6 |
| Quickstart tutorial | Task 7 |
| First Agent tutorial | Task 7 |
| 7-Day Mastery | Task 8 |
| Custom tool how-to | Task 9 |
| Custom provider how-to | Task 9 |
| Custom sandbox how-to | Task 10 |
| Custom memory how-to | Task 10 |
| Channels how-to | Task 10 |
| MCP integration how-to | Task 11 |
| Hooks how-to | Task 11 |
| Skills how-to | Task 11 |
| Permissions how-to | Task 11 |
| Docstring audit | Task 12 |
| Final verification | Task 13 |

**Placeholder scan:** Tasks 9-11 contain abbreviated descriptions (not full code). This is intentional — the how-to guides are standard task-oriented documentation, not code-heavy. The implementing agent writes the actual markdown content following the structural hints provided.

**Type consistency:** All class names and method signatures match the source code verified during audit.