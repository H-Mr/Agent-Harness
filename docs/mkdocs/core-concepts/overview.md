# Conceptual Overview

## The Problem: Every Agent Project Rewrites the Same Infrastructure

Building a production-grade LLM agent requires far more than just calling an API.
Every project needs the same set of infrastructure concerns:

- **LLM provider abstraction** -- swapping between Anthropic, OpenAI, DeepSeek,
  Gemini, and dozens of other backends without changing application code
- **Tool execution** -- defining, validating, and executing tools with Pydantic
  input schemas, plus converting between Anthropic and OpenAI function-calling
  formats
- **Permission checking** -- read-only auto-approve, mutating confirmation prompts,
  sensitive-path guardrails, command deny-lists, and plan-mode restrictions
- **Conversation sessions** -- persisting message history to JSONL files,
  session key management, legal tool-call boundary alignment
- **Memory** -- long-term fact storage (MEMORY.md), grep-searchable logs
  (HISTORY.md), LLM-based consolidation when context windows get full
- **Context assembly** -- building system prompts from pluggable section providers,
  injecting runtime context (time, channel metadata)
- **Observability** -- structured events for every tool call, every LLM turn,
  every error; JSONL tracking; real-time event bus
- **Error handling** -- transient retry with exponential backoff, image-strip
  fallback, graceful degradation
- **Concurrency** -- per-session locks, global semaphore, cancellation
  propagation

Every agent project implements these from scratch -- and each one gets them
slightly wrong. The Harness exists to solve this problem _once_.

## The Solution: Harness Handles Everything That Isn't LLM Inference

Agent Harness is an infrastructure container. It owns every cross-cutting concern
listed above so that your application code owns only the things that make your
agent unique:

- **What tools does your agent need?** Register them. The Harness handles schema
  conversion, validation, and lifecycle.
- **How should permissions work?** Choose a mode (default / plan / full-auto) or
  inject a custom callback. The Harness enforces the policy.
- **Should the agent remember things across sessions?** Point the Harness at a
  workspace directory. It creates MEMORY.md and HISTORY.md automatically.
- **What model provider should it use?** Pass a provider instance or let
  `detect_provider()` auto-detect from model name / API key prefix / base URL.

The Harness is not an agent. It is the _scaffolding_ that an agent runs inside.

## The Formula: Harness + LLM = Agent

```
Agent(Harness(provider=LLMProvider, tools=ToolRegistry, permissions=...), model="...")
```

An `Agent` is the composition of a `Harness` (infrastructure) with a model name
(an LLM). The `Agent.process()` method is a single entry point that drives the
entire pipeline:

1. **Concurrency gate** -- per-session `asyncio.Lock` + global `asyncio.Semaphore`
2. **Session bookkeeping** -- get-or-create session, append user message, persist
3. **Memory consolidation** -- if context is approaching the window limit,
   archive old messages to MEMORY.md / HISTORY.md
4. **Context building** -- call the `on_build_context` callback to assemble
   system prompt + history + current message
5. **ReAct loop** -- delegate to `AgentLoop` which calls the LLM, executes
   tools, feeds results back, and repeats until final text or iteration limit
6. **Turn persistence** -- save assistant + tool messages back to the session file
7. **Return** -- produce an `OutboundMessage` with the final response

## The Pipeline Model: Permission -> Hook(PRE) -> Execute -> Hook(POST)

Every tool invocation passes through a uniform pipeline:

```
Tool identified  →  Permission check  →  Hook(PRE)  →  Execute  →  Hook(POST)  →  Result
```

| Stage | Responsibility |
|-------|---------------|
| Permission | `PermissionChecker.evaluate()` returns allow/deny/confirm. Sensitive path patterns are always enforced. |
| Hook(PRE) | User-defined `on_tool_check` callback. Can override the default permission decision. |
| Execute | `BaseTool.execute()` with Pydantic-validated arguments. |
| Hook(POST) | Result is returned. Structured events are emitted. |

Observability events (`ToolExecutionStarted`, `ToolExecutionCompleted`) are
emitted automatically around execution.

## The Callback Injection Pattern: All App-Specific Behavior Is Injected, Nothing Is Inherited

The `AgentLoop` (the core ReAct skeleton) has **no subclasses**. Instead, it
receives a `LoopCallbacks` dataclass with function references:

```python
@dataclass
class LoopCallbacks:
    build_messages: Callable     # assemble message list for LLM call
    execute_tool: Callable       # run one tool by name + args
    get_tool_definitions: Callable  # return tool schemas
    on_progress: Callable | None    # progress indicator
    on_stream: Callable | None      # streaming text delta
    on_event: Callable | None       # structured observability
```

Similarly, the `Harness` accepts three pipeline callbacks:

- `on_tool_check` -- custom permission logic (default: delegate to `PermissionChecker`)
- `on_build_context` -- how to assemble messages from system prompt + history + input
- `on_error` -- what to return when an exception escapes the pipeline

This means every behavioral extension is a **function you pass in**, not a class
you override. The system is composed, not inherited.

## The Three-Layer Architecture: Agent -> Harness -> Parts Library

```
┌─────────────────────────────────────────────┐
│                   Agent                      │
│  process(msg) → ReAct → OutboundMessage     │
│  Owns: concurrency, sessions, memory,        │
│        consolidator                          │
├─────────────────────────────────────────────┤
│                  Harness                     │
│  Infrastructure container                    │
│  Owns: provider, tools, permissions,         │
│        context, skills, hooks, tracker       │
├─────────────────────────────────────────────┤
│              Parts Library                   │
│  BaseTool, ToolRegistry, LLMProvider,         │
│  PermissionChecker, MemoryStore,             │
│  SessionManager, ContextBuilder,             │
│  EventBus, Tracker, AgentLoop                │
│  (all reusable independently)                │
└─────────────────────────────────────────────┘
```

- **Agent**: High-level runnable. Add a Harness and a model name, call
  `process(msg)`.
- **Harness**: Infrastructure container. Wires together all subsystems with
  sensible defaults. Accepts simplified shorthands (strings, paths, lists).
- **Parts Library**: Every component is independently usable. You can use
  `AgentLoop` directly without `Harness` or `Agent`. You can use
  `PermissionChecker` in a non-agent script. You can emit events to `EventBus`
  from anywhere.

## When to Use Harness + Agent vs. Low-Level AgentLoop

| Use Case | Recommended API |
|----------|----------------|
| Building a chat agent with persistent sessions and memory | `Harness` + `Agent` |
| Building a one-shot script that needs a ReAct loop | `AgentLoop` directly |
| Adding agent capabilities to an existing application | `Harness` + `Agent` |
| Running headless batch processing | `AgentLoop.process_direct()` |
| Testing tool execution in isolation | `ToolRegistry` + `BaseTool` directly |
| Custom permission logic without the rest of the stack | `PermissionChecker` independently |
| Observability-only integration | `EventBus` + `Tracker` independently |

The `Harness` + `Agent` pair is opinionated -- it assumes you want sessions,
memory, and a specific process flow. When those assumptions don't fit, drop down
to `AgentLoop`, which is a pure ReAct skeleton with no opinions about sessions,
persistence, or channels.

---

**Next:** [Harness Deep Dive](harness.md) | [Agent Deep Dive](agent.md) | [Tools](tools.md)
