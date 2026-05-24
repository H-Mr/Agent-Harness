# llm-harness

**Production-grade reusable AI agent infrastructure base — build an AI agent in 25 lines.**

<div class="grid cards" markdown>

- :material-rocket-launch: **25 Lines to Agent** — Harness handles everything that isn't LLM inference. `Agent(Harness(...), model="gpt-4").process(msg)` is all you need.
- :material-puzzle: **28 Built-in Tools** — File I/O, shell execution, web search, glob/grep, notebook editing, cron management, and more. Config-driven enable/disable.
- :material-shield-check: **Defense in Depth** — SSRF protection, sensitive path blocking, 3 permission modes, Pre/Post tool hooks, OS sandbox integration.
- :material-chart-line: **Observability First** — 17 structured event types, async EventBus, JSONL tracker. Auto-start from config. Zero overhead when disabled.

</div>

```python
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage
from agent_harness.prompts.sections import IdentitySection

agent = Agent(
    Harness(
        provider=OpenAICompatProvider(api_key="...", api_base="https://api.openai.com/v1"),
        tools=["read_file", "write_file", "exec", "web_search"],
        context=[IdentitySection("You are a helpful assistant.")],
    ),
    model="gpt-4",
)

result = await agent.process(
    InboundMessage(channel="cli", sender_id="user", chat_id="c1", content="Hello!")
)
print(result.content)
```

---

## Why llm-harness?

| Option | Problem |
|--------|---------|
| **LangChain / LangGraph** | 300K+ lines, 50+ dependencies, constant API churn, learning curve measured in weeks |
| **From scratch** | 2–4 weeks rebuilding loop, retry, registry, session, permissions, hooks every time |
| **llm-harness** | ~13,000 lines. Read in an afternoon. Fork without fear. MIT license. |

---

## The Core Idea

```
Harness + LLM = Agent
```

**Harness** is everything that isn't LLM inference: tools, permissions, memory, sessions, hooks, observability, sandbox. It's a configurable container with sensible defaults — `Harness()` already works.

**Agent** is Harness plus a model name. It exposes exactly one method: `process(msg)`. CLI, HTTP, WebSocket, WeChat, Feishu — every channel is an `InboundMessage`.

Every tool call goes through a pipeline you never wrote:

```
LLM → Permission.check → Hook.execute(PRE) → Tool.execute → Hook.execute(POST) → LLM
```

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────┐
│  Agent.process(msg) → OutboundMessage            │
├──────────────────────────────────────────────────┤
│  Harness                                         │
│                                                  │
│  Message Pipeline:                               │
│    Session → Consolidation → Context → ReAct     │
│                                                  │
│  Tool Pipeline:                                  │
│    Lookup → Validate → Permissions → Execute     │
├──────────────────────────────────────────────────┤
│  Parts Library                                   │
│  tools │ providers │ permissions │ hooks         │
│  session │ memory │ observability │ cron │ mcp   │
│  channels │ commands │ plugins │ sandbox         │
└──────────────────────────────────────────────────┘
```

---

## Quick Navigation

| Section | Description |
|---------|-------------|
| [Getting Started](getting-started.md) | Install, configure, and run your first agent |
| [Core Concepts](core-concepts/overview.md) | Deep dives into Harness, Agent, Tools, Providers, and more |
| [Architecture](architecture.md) | Full system design, data flow, and design principles |
| [API Reference](api/harness.md) | Auto-generated API docs for every module |
| [Deployment](deployment.md) | K8s, Docker, Kafka, and production best practices |
| [Examples](examples/index.md) | Customer service agent, CLI bot, cron-based agent |
