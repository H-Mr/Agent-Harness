# llm-harness

[![PyPI version](https://img.shields.io/pypi/v/llm-harness)](https://pypi.org/project/llm-harness/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-337%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)]()

**[中文介绍](docs/INTRO.md#中文版) · [English Introduction](docs/INTRO.md) · [GitHub](https://github.com/H-Mr/llm-harness)**

**Production-grade reusable agent infrastructure base — ~13,000 lines, 337 tests.**

Build an AI agent by dropping in a provider, tools, and context. Everything else — ReAct loop, tool pipeline, permissions, hooks, session persistence, memory consolidation, observability — is handled by the harness.

```python
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.prompts.sections import IdentitySection

agent = Agent(
    Harness(
        provider=OpenAICompatProvider(api_key="...", api_base="..."),
        tools=["read_file", "write_file", "exec", "web_search"],
        context=[IdentitySection("You are a helpful assistant.")],
    ),
    model="gpt-4",
)

result = await agent.process(InboundMessage(channel="cli", sender_id="user", chat_id="c1", content="Do the thing"))
print(result.content)
```

## Why This Exists

| Option | Problem |
|--------|---------|
| **LangChain/LangGraph** | 300K+ lines, 50+ dependencies, constant API churn |
| **From scratch** | Rebuild loop, retry, registry, session, permissions... every time |
| **llm-harness** | ~13K lines. Read in an afternoon. Fork without fear. 337 tests |
| **llm-harness (v0.2)** | + Harness/Agent: 25 lines to a running agent |

## Architecture

```
Each tool call goes through:
  LLM → Permission.check → Hook.execute(PRE_TOOL_USE) → Tool.execute → Hook.execute(POST_TOOL_USE) → LLM

Each conversation turn goes through:
  Message → AgentLoop → Provider.chat_with_retry → (tool calls? → execute → loop) → Text response

Every event flows through:
  Any module → EventBus → Tracker (JSONL file) / Prometheus / Dashboard
```

```
llm-harness/
  harness.py        Harness — infrastructure container + from_config()
  agent.py          Agent — single process(msg) entry point
  loop/             ReAct skeleton + concurrency (per-session Lock + Semaphore)
  tools/            28 built-in tools + config-driven builder
  providers/        Anthropic + OpenAI-compatible (25 backends), retry + backoff
  permissions/      Sensitive path protection, 3 modes, path/cmd rules
  hooks/            PreToolUse/PostToolUse, 4 hook types (cmd/http/prompt/agent)
  security/         SSRF protection (DNS + private IP blocking)
  sandbox/          OS-level isolation (srt CLI wrapper), built into ExecTool
  session/          JSONL persistence + legal boundary alignment
  memory/           Two-tier (MEMORY.md + HISTORY.md) + LLM consolidation
  skills/           .md loading + dependency checking
  cron/             Scheduler (at/every/cron) + management tools
  channels/         BaseChannel ABC + WeChat + Feishu implementations
  mcp/              MCP stdio/SSE/HTTP, tools as BaseTool subclasses
  commands/         4-tier slash command router
  plugins/          Discovery + manifest loading
  auth/             Credential storage (file + keyring + encryption)
  prompts/          AGENTS.md discovery + environment + SectionProviders
  tasks/            Background subprocess manager + stdout capture
  coordinator/      Subagent spawning with restricted tools
  state/            Observable state store (get/set/subscribe)
  config/           Multi-layer (CLI > env > file > defaults)
  observability/    Structured events + EventBus + JSONL tracker (auto-start)
```

## Quick Start

```bash
pip install llm-harness[all]
```

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
            tools=["read_file", "write_file", "exec"],
            context=[IdentitySection("You are a friendly assistant.")],
        ),
        model="gpt-4",
    )

    result = await agent.process(
        InboundMessage(channel="cli", sender_id="user", chat_id="c1", content="Hello!")
    )
    print(result.content)

asyncio.run(main())
```

### Low-Level API (full control)

```python
from agent_harness import AgentLoop, LoopCallbacks, ToolRegistry, AnthropicProvider

tools = ToolRegistry()
tools.register(MyBusinessTool())

callbacks = LoopCallbacks(
    build_messages=lambda msg: [
        {"role": "system", "content": "You are a friendly assistant."},
        {"role": "user", "content": msg.content},
    ],
    execute_tool=lambda name, args: _exec(tools, name, args),
    get_tool_definitions=lambda: tools.to_api_schema("anthropic"),
)

loop = AgentLoop(AnthropicProvider(api_key="..."), callbacks)
result = await loop.process_direct("Hello!")
print(result.final_content)
```

### Config-Driven Setup

```json
{
  "agent": { "model": "claude-sonnet-4-6", "provider": "anthropic" },
  "tools": { "enabled": ["web_search", "message", "write_memory"] },
  "permission": { "mode": "default" },
  "observability": { "track_file": "~/.llm-harness/track.jsonl" }
}
```

```python
from agent_harness import Agent, Harness, load_config

config = load_config("config.json")
agent = Agent(Harness.from_config(config))
result = await agent.process(InboundMessage(channel="cli", content="Search for latest AI news"))
```

## Observability

Zero-config by default. Set `observability.track_file` in config to auto-start JSONL tracking:

```jsonl
{"type":"SessionOpened","ts":"...","data":{"session_key":"cli:test"}}
{"type":"ToolExecutionStarted","ts":"...","data":{"tool_name":"web_search","tool_input":{...}}}
{"type":"ToolExecutionCompleted","ts":"...","data":{"tool_name":"web_search","output":"...","is_error":false,"duration_ms":123.4}}
{"type":"AssistantTurnComplete","ts":"...","data":{"content":"Done","usage":{"prompt_tokens":10,"completion_tokens":5}}}
```

Or subscribe programmatically for real-time metrics:

```python
from agent_harness.observability import get_event_bus

async def prometheus_collector(event):
    if isinstance(event, ToolExecutionCompleted):
        histogram(f"tool.{event.tool_name}.latency_ms", event.duration_ms)

get_event_bus().subscribe(prometheus_collector)
```

## Deployment

```yaml
# One Deployment per agent scenario
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cs-agent
spec:
  replicas: 3
  template:
    spec:
      containers:
      - image: llm-harness:latest
        env:
        - name: AGENT_SCENARIO
          value: "customer-service"
        volumeMounts:
        - name: tools
          mountPath: /app/tools
        - name: skills
          mountPath: /app/skills
```

```
Kafka: topic:customer-service → cs-agent (3 pods)
       topic:code-review      → cr-agent (2 pods)
       topic:ops-automation   → ops-agent (1 pod)
```

## Installation

```bash
pip install llm-harness               # base
pip install llm-harness[anthropic]    # + Claude
pip install llm-harness[openai]       # + OpenAI
pip install llm-harness[all]          # everything
pip install llm-harness[dev]          # + pytest, ruff
```

## Requirements

Core: Python >= 3.10, pydantic >= 2.0, httpx >= 0.27, pyyaml >= 6.0, mcp >= 1.0, croniter >= 2.0, json-repair >= 0.57
Optional: `anthropic`, `openai`, `ddgs`, `readability-lxml`

## Tests

```
337 passed, 9 skipped, 0 failed
```

9 skipped are optional dependency tests (ddgs, readability-lxml). Install those packages to enable them.

## Design Principles

1. **Harness + LLM = Agent.** Harness handles everything that isn't LLM inference. Agent is `process(msg)` — one method for all channels.

2. **Callback injection, not inheritance.** Every behavior is injected. The loop knows nothing about your tools, channels, or prompts.

3. **Config-driven.** Switch agent behavior via JSON. Tools, permissions, provider, sandbox, observability — all configurable without code changes.

4. **Transport-agnostic.** `BaseChannel` defines the contract. CLI, HTTP, WebSocket, WeChat, Feishu — same interface.

5. **You own the code.** ~13,000 lines. Fork it. Modify it. No framework to learn.

6. **Production observability.** Structured events, EventBus, JSONL tracker, auto-start from config. Zero overhead when disabled.

## License

MIT — see [LICENSE](LICENSE).

## Credits

Extracted and refined from two mature open-source agent projects:

- [OpenHarness](https://github.com/HKUDS/OpenHarness) — tools, permissions, hooks, skills, sandbox, plugins, tasks
- [nanobot](https://github.com/HKUDS/nanobot) — agent loop, providers, message bus, session, memory, cron, channels
