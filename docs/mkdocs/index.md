# llm-harness

**Production-grade reusable AI agent infrastructure. Build an agent in 25 lines.**

```
Harness + LLM = Agent
```

llm-harness is the infrastructure layer between your LLM and your business logic — the plumbing every agent needs but nobody wants to write. ~13,000 lines of Python, 337 tests, MIT license.

<div class="grid cards" markdown>

-   **25 Lines to Agent**

    ---

    Harness handles tools, permissions, memory, sessions, and observability. `Agent(Harness(...), model="gpt-4o").process(msg)` is all you need.

-   **28 Built-in Tools**

    ---

    File I/O, shell execution, web search, glob/grep, notebook editing, cron jobs. Config-driven — enable with `["*"]`.

-   **Defense in Depth**

    ---

    SSRF protection, sensitive path blocking, 3 permission modes, Pre/Post tool hooks, OS-level sandbox via `srt`.

-   **Observability First**

    ---

    17 structured event types, async EventBus, JSONL tracker. Auto-start from config. Zero overhead when disabled.

</div>

---

## 25 Lines to an Agent

```python
import asyncio
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage
from agent_harness.prompts.sections import IdentitySection

async def main():
    agent = Agent(
        Harness(
            provider=OpenAICompatProvider(
                api_key="sk-...", api_base="https://api.openai.com/v1"
            ),
            tools=["read_file", "write_file", "exec", "web_search"],
            context=[IdentitySection("You are a helpful assistant.")],
        ),
        model="gpt-4o",
    )

    result = await agent.process(
        InboundMessage(channel="cli", sender_id="user", chat_id="c1", content="Hello!")
    )
    print(result.content)

asyncio.run(main())
```

!!! tip "No boilerplate"
    Those 25 lines include session management, memory consolidation, permission checks, tool execution, retry logic, and error handling. No additional wiring needed.

---

## Why llm-harness?

| Option | Cost |
|--------|------|
| **LangChain / LangGraph** | 300K+ lines, 50+ dependencies, constant API churn, weeks to learn |
| **From scratch** | 2–4 weeks rebuilding loop, retry, registry, session, permissions, hooks |
| **llm-harness** | ~13,000 lines. Read in an afternoon. Fork without fear. MIT license. |

---

## Architecture

Every tool call flows through a pipeline you never wrote:

```
LLM → Permission.check → Hook.execute(PRE) → Tool.execute → Hook.execute(POST) → LLM
```

Every message flows through an 8-step pipeline:

```
Session → Consolidation → Context → ReAct → Persist → OutboundMessage
```

```
┌──────────────────────────────────────────────────┐
│  Agent.process(msg) → OutboundMessage            │
├──────────────────────────────────────────────────┤
│  Harness                                         │
│   Message Pipeline: Session → Memory → Context   │
│   Tool Pipeline:  Lookup → Validate → Execute    │
├──────────────────────────────────────────────────┤
│  Parts: tools │ providers │ permissions │ hooks  │
│  session │ memory │ observability │ cron │ mcp   │
│  channels │ commands │ plugins │ sandbox         │
└──────────────────────────────────────────────────┘
```

---

## Quick Navigation

<div class="grid cards" markdown>

-   :material-school-outline:{ .lg .middle } **Tutorials**

    ---

    Follow step-by-step to run your first agent in 5 minutes.

    [:octicons-arrow-right-24: Quick Start](tutorials/quick-start.md)

-   :material-book-open-page-variant-outline:{ .lg .middle } **How-to Guides**

    ---

    Solve specific problems: deploy, add channels, schedule jobs, enable tracing.

    [:octicons-arrow-right-24: Deploy to K8s](how-to/deploy-k8s.md)

-   :material-bookshelf:{ .lg .middle } **API Reference**

    ---

    Complete module, class, and method reference. Auto-generated from source.

    [:octicons-arrow-right-24: Harness API](api/harness.md)

-   :material-graph-outline:{ .lg .middle } **Explanation**

    ---

    Understand design decisions, architecture, concurrency, and the memory model.

    [:octicons-arrow-right-24: Architecture](explanation/architecture.md)

</div>
