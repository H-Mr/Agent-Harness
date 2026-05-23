# agent-harness: The Missing Base Layer for AI Agents

*[中文版见下方](#中文版)*

---

Every AI agent project starts the same way — loop, tools, retry, session, memory, permissions. And every project builds them from scratch. Or worse, adopts a 300K-line framework just to get a ReAct loop. There should be a better way.

## The Problem

Building a production AI agent today has exactly three paths, none ideal:

| Path | What you get | What you pay |
|------|-------------|-------------|
| **LangChain / LangGraph** | Everything including the kitchen sink | 300K lines, 50+ deps, API churn, learning curve measured in weeks |
| **From scratch** | Exactly what you need | 2-4 weeks rebuilding: loop, retry, registry, session, permissions, hooks... |
| **Vendor SDK only** | Fast API calls | No agent loop, no tool pipeline, no session — you build the harness yourself |

The gap is obvious: there's no Flask for AI agents. No thin, well-tested base that handles the plumbing so you can focus on your business logic.

## What agent-harness Is

**~10,000 lines of Python. 290 tests. MIT license.**

It is not a framework. It is infrastructure — the layer between the LLM and your tools that every agent needs but nobody wants to write:

```
                    ┌──────────────────────┐
                    │   Your Business Logic │
                    │  (tools, skills, UI)  │
                    ├──────────────────────┤
                    │   agent-harness       │  ← You are here
                    │  loop · tools · retry │
                    │  session · memory     │
                    │  permissions · hooks  │
                    │  observability        │
                    ├──────────────────────┤
                    │   LLM Provider        │
                    └──────────────────────┘
```

**Every tool call goes through this pipeline, and you didn't write a single line of it:**

```
LLM → Permission.check → Hook.execute(PRE) → Tool.execute → Hook.execute(POST) → LLM
```

## What's Inside

| Layer | What | Why you need it |
|-------|------|----------------|
| **Loop** | ReAct skeleton with per-session lock + global semaphore | Deterministic concurrency, no race conditions |
| **Tools** | 24 built-in + config-driven builder | `tools.enabled: ["web_search", "message"]` in JSON |
| **Providers** | Anthropic + OpenAI-compatible (25 backends) | Retry with exponential backoff + image-strip fallback |
| **Permissions** | Sensitive path protection, 3 modes, path/cmd rules | Defense in depth for every tool call |
| **Hooks** | PreToolUse/PostToolUse, 4 types | Validation, logging, audit — pluggable |
| **Session** | JSONL persistence with legal boundary alignment | Survive restarts, resume conversations |
| **Memory** | Two-tier (MEMORY.md + HISTORY.md) + LLM consolidation | Long-running sessions without context explosion |
| **Observability** | 11 event types + EventBus + JSONL tracker | `track_file` in config, zero code to enable |
| **Security** | SSRF protection + OS sandbox | Block metadata service attacks, contain shell commands |
| **Cron** | at / every / cron scheduler | Scheduled tasks without external dependencies |
| **MCP** | stdio / SSE / HTTP transports | Model Context Protocol out of the box |

## By the Numbers

```
10,197 lines of source
    24 packages
   290 tests (0 failures)
     9 skipped (optional deps)
    25 provider backends
    24 built-in tools
    11 event types
     6 core dependencies
     1 design rule: everything is a callback, nothing is inherited
```

## A Real Example

This is a customer service agent. The harness handles the loop, retry, permissions, hooks, and observability. You only write the business:

```python
from agent_harness import (
    AgentLoop, LoopCallbacks, BaseTool, ToolRegistry,
    ToolResult, ToolExecutionContext, AnthropicProvider,
    Config, ToolsConfig, build_tools_from_config,
)

# 1. Your business tool
class OrderQueryTool(BaseTool):
    name = "order_query"
    description = "Look up an order by ID"
    input_model = OrderQueryInput

    async def execute(self, args, ctx):
        return ToolResult(output=f"Order {args.order_id}: Shipped")

# 2. Config-driven tool set
config = Config(
    tools=ToolsConfig(enabled=["order_query", "web_search", "message"]),
    observability=ObservabilityConfig(track_file="~/.agent-harness/track.jsonl"),
)
tools = build_tools_from_config(config.tools)
tools.register(OrderQueryTool())

async def _exec(tools, name, args):
    tool = tools.get(name)
    parsed = tool.input_model.model_validate(args)
    result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
    return result.output

# 3. Wire it up
callbacks = LoopCallbacks(
    build_messages=lambda msg: [
        {"role": "system", "content": "You are a helpful CS agent."},
        {"role": "user", "content": msg.content},
    ],
    execute_tool=lambda name, args: _exec(tools, name, args),
    get_tool_definitions=lambda: tools.to_api_schema("anthropic"),
)

agent = AgentLoop(AnthropicProvider(api_key="..."), callbacks)
result = await agent.process_direct("Where is order #001?")
```

The `process_direct` call triggers: LLM call → tool_call detected → permission check → hook execution → tool execution → result → LLM finalizes → structured events emitted. You wrote none of that pipeline.

## When You Should Use It

- You're building a production agent and don't want LangChain's weight
- You've built agents from scratch before and are tired of rewriting the same plumbing
- You need observability, permissions, and hooks — not as afterthoughts, but baked in
- You want to deploy one agent per scenario to K8s, each with different tools and skills

## When You Should Not

- You need LangGraph's graph-based multi-step orchestration today
- You're doing a quick hackathon demo where 50 lines of `while True:` is fine
- You want an all-in-one platform with built-in UI, channels, and auth flows

## Next Steps

```bash
pip install llm-harness[all]
```

GitHub: [github.com/H-Mr/Agent-Harness](https://github.com/H-Mr/Agent-Harness)

Read the source. Read the tests. Build something.

---

## 中文版

每个 AI agent 项目的起点都一样——循环、工具注册、重试、session、memory、权限。每个项目都从零造一遍。或者更糟，为了一个 ReAct 循环引入 30 万行的框架。

## 问题

现在做 AI agent 只有三条路：

| 路径 | 得到什么 | 代价 |
|------|---------|------|
| **LangChain/LangGraph** | 什么都有 | 30万行、50+依赖、API 频繁变动、学习曲线以周计 |
| **从零手写** | 刚好需要的 | 2-4周重复造：循环、重试、注册、session、权限、hook |
| **只用 SDK** | 快速调 API | 没有 agent 循环、没有工具管线、没有 session |

空白很明显：**AI agent 领域没有 Flask。** 没有一个轻量、经过测试的基座，帮你处理基础设施，让你专注于业务逻辑。

## agent-harness 是什么

**约 10,000 行 Python。290 个测试。MIT 许可证。**

不是框架。是基础设施——LLM 和你的业务工具之间的那一层，每个 agent 都需要但没人想写：

```
                    ┌──────────────────────┐
                    │   你的业务逻辑         │
                    │  (工具、技能、UI)      │
                    ├──────────────────────┤
                    │   agent-harness       │  ← 你在这里
                    │  循环·工具·重试       │
                    │  session·memory       │
                    │  权限·hook            │
                    │  观测系统             │
                    ├──────────────────────┤
                    │   LLM Provider        │
                    └──────────────────────┘
```

**每次工具调用都走这条管线，而你一行都没写：**

```
LLM → 权限检查 → Hook执行(前置) → 工具执行 → Hook执行(后置) → LLM
```

## 包含什么

| 层次 | 组件 | 用途 |
|------|------|------|
| 循环 | ReAct 骨架 + 并发控制（per-session Lock + Semaphore） | 确定性的并发，无竞态 |
| 工具 | 24 个内建 + 配置驱动 | JSON 里写 `"enabled": ["web_search"]` |
| Provider | Anthropic + OpenAI 兼容（25 个后端） | 指数退避重试 + image-strip 回退 |
| 权限 | 敏感路径保护 + 3 种模式 + 路径/命令规则 | 每次工具调用的纵深防御 |
| Hook | PreToolUse/PostToolUse + 4 种类型 | 校验、日志、审计——可插拔 |
| Session | JSONL 持久化 + 合法边界对齐 | 重启不丢，会话恢复 |
| Memory | 双层（MEMORY.md + HISTORY.md）+ LLM 摘要 | 长会话不爆上下文 |
| 观测 | 11 种事件 + EventBus + JSONL tracker | config 里配 `track_file`，零代码启用 |
| 安全 | SSRF 防护 + OS 沙箱 | 阻止 metadata service 攻击，隔离 shell 命令 |
| Cron | at/every/cron 调度 | 定时任务不依赖外部系统 |
| MCP | stdio/SSE/HTTP 传输 | Model Context Protocol 开箱即用 |

## 数据

```
10,197 行源码
    24 个包
   290 个测试（0 失败）
     9 个跳过（可选依赖）
    25 个 provider 后端
    24 个内建工具
    11 种事件类型
     6 个核心依赖
     1 条设计原则：一切走 callback 注入，零继承
```

## 什么时候用

- 做生产级 agent，不想背 LangChain 的重量
- 从零手写过 agent，厌倦了重复造基础设施
- 需要观测、权限、hook——不是事后补，而是内置
- 一个场景一个 K8s Deployment，每个挂不同工具和 skill

## 什么时候不用

- 现在就需要 LangGraph 的图编排
- 快速原型，50 行 `while True` 够用
- 想要一站式平台（自带 UI、channel、auth）

## 开始

```bash
pip install llm-harness[all]
```

GitHub: [github.com/H-Mr/Agent-Harness](https://github.com/H-Mr/Agent-Harness)

读源码。读测试。开始构建。
