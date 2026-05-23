# llm-harness

**[中文介绍](docs/INTRO.md#中文版) · [English Introduction](docs/INTRO.md) · [GitHub](https://github.com/H-Mr/llm-harness) · [PyPI](https://pypi.org/project/llm-harness/)**

**Production-grade reusable agent infrastructure base — ~10,000 lines, 290 tests.**

Build an AI agent by defining your tools, writing your skills, and choosing a provider. Everything else — ReAct loop, tool pipeline, permissions, hooks, session persistence, memory consolidation, observability — is handled by the harness.

```python
from agent_harness import AgentLoop, LoopCallbacks, ToolRegistry, AnthropicProvider

tools = ToolRegistry()
tools.register(MyBusinessTool())

callbacks = LoopCallbacks(
    build_messages=...,               # your system prompt
    execute_tool=...,                 # your tool execution
    get_tool_definitions=lambda: tools.to_api_schema("anthropic"),
)

agent = AgentLoop(AnthropicProvider(api_key="..."), callbacks)
result = await agent.process_direct("Do the thing")
print(result.final_content)
```

## Why This Exists

| Option | Problem |
|--------|---------|
| **LangChain/LangGraph** | 300K+ lines, 50+ dependencies, constant API churn |
| **From scratch** | Rebuild loop, retry, registry, session, permissions... every time |
| **llm-harness** | ~10K lines. Read in an afternoon. Fork without fear. 290 tests |

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
  loop/             ReAct skeleton + concurrency (per-session Lock + Semaphore)
  tools/            24 built-in tools + config-driven builder
  providers/        Anthropic + OpenAI-compatible (25 backends), retry + backoff
  permissions/      Sensitive path protection, 3 modes, path/cmd rules
  hooks/            PreToolUse/PostToolUse, 4 hook types (cmd/http/prompt/agent)
  security/         SSRF protection (DNS + private IP blocking)
  sandbox/          OS-level isolation (srt CLI wrapper)
  session/          JSONL persistence + legal boundary alignment
  memory/           Two-tier (MEMORY.md + HISTORY.md) + LLM consolidation
  skills/           .md loading + dependency checking
  cron/             Scheduler (at/every/cron) + persistence
  mcp/              MCP stdio/SSE/HTTP, tools as BaseTool subclasses
  channels/         BaseChannel ABC + ChannelManager (WebSocket, Telegram...)
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
from pathlib import Path
from agent_harness import (
    AgentLoop, LoopCallbacks, ToolRegistry, BaseTool,
    ToolResult, ToolExecutionContext, AnthropicProvider,
)
from pydantic import BaseModel, Field

class GreetInput(BaseModel):
    name: str = Field(description="Who to greet")

class GreetTool(BaseTool):
    name = "greet"
    description = "Greet someone"
    input_model = GreetInput

    async def execute(self, args, ctx):
        return ToolResult(output=f"Hello, {args.name}!")

tools = ToolRegistry()
tools.register(GreetTool())

async def _exec(tools, name, args):
    tool = tools.get(name)
    parsed = tool.input_model.model_validate(args)
    result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
    return result.output

callbacks = LoopCallbacks(
    build_messages=lambda msg: [
        {"role": "system", "content": "You are a friendly assistant."},
        {"role": "user", "content": msg.content},
    ],
    execute_tool=lambda name, args: _exec(tools, name, args),
    get_tool_definitions=lambda: tools.to_api_schema("anthropic"),
    on_event=lambda e: print(f"[{type(e).__name__}]"),  # optional observability
)

agent = AgentLoop(AnthropicProvider(api_key="..."), callbacks)

async def main():
    result = await agent.process_direct("Greet Alice!")
    print(result.final_content)

asyncio.run(main())
```

### Config-Driven Setup

```json
{
  "agent": { "model": "claude-sonnet-4-6" },
  "tools": { "enabled": ["web_search", "message", "write_memory"] },
  "permission": { "mode": "default" },
  "observability": { "track_file": "~/.llm-harness/track.jsonl" }
}
```

```python
from agent_harness import load_config, build_tools_from_config, start_tracker_from_config

config = load_config()
tools = build_tools_from_config(config.tools)
tracker = await start_tracker_from_config(config)  # auto-starts if configured
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
290 passed, 9 skipped, 0 failed
```

9 skipped are optional dependency tests (ddgs, readability-lxml). Install those packages to enable them.

## Design Principles

1. **Callback injection, not inheritance.** `LoopCallbacks` dataclass holds all app-specific behavior. The loop knows nothing about your tools, channels, or prompts.

2. **Config-driven.** Switch agent behavior via JSON. Tools, permissions, provider, sandbox, observability — all configurable without code changes.

3. **Transport-agnostic.** `BaseChannel` defines the contract. WebSocket, HTTP, gRPC, Telegram — same interface.

4. **You own the code.** ~10,000 lines. Fork it. Modify it. No framework to learn.

5. **Production observability.** Structured events, EventBus, JSONL tracker, auto-start from config. Zero overhead when disabled.

## License

MIT — see [LICENSE](LICENSE).

## Credits

Extracted and refined from two mature open-source agent projects:

- [OpenHarness](https://github.com/HKUDS/OpenHarness) — tools, permissions, hooks, skills, sandbox, plugins, tasks
- nanobot — agent loop, providers, message bus, session, memory, cron, channels
