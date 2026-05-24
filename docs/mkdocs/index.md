# llm-harness

**生产级 AI Agent 开发基座 — 25 行代码构建一个 Agent。**

```
Harness + LLM = Agent
```

llm-harness 是一个 MIT 开源的 Python 框架（~13,000 行，337 个测试），核心理念是：**将 Agent 开发中与 LLM 推理无关的一切基础设施抽离出来**，让你只关注 `process(msg)` 这一个方法。

<div class="grid cards" markdown>

- :material-rocket-launch: **25 行到 Agent** — Harness 处理工具、权限、记忆、会话、观测……`Agent(Harness(...), model="gpt-4").process(msg)` 就是全部。
- :material-puzzle: **28 个内置工具** — 文件 I/O、Shell 执行、Web 搜索、glob/grep、笔记本编辑、定时任务……配置驱动，开箱即用。
- :material-shield-check: **纵深防御** — SSRF 防护、敏感路径拦截、3 种权限模式、Pre/Post 工具钩子、OS 级沙箱。
- :material-chart-line: **观测优先** — 17 种结构化事件类型、异步 EventBus、JSONL 追踪器。配置即启动，关闭时零开销。

</div>

## 25 行代码跑一个 Agent

```python
import asyncio
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage
from agent_harness.prompts.sections import IdentitySection

async def main():
    # 1. 创建 Harness — 一切基础设施的容器
    harness = Harness(
        provider=OpenAICompatProvider(  # 也可用 AnthropicProvider
            api_key="sk-...",
            api_base="https://api.openai.com/v1",
        ),
        tools=["read_file", "write_file", "exec", "web_search"],  # 开箱即用的工具
        context=[IdentitySection("你是一个有用的助手。")],  # 系统提示词
    )

    # 2. 创建 Agent — Harness + 模型名 = 可运行的 Agent
    agent = Agent(harness, model="gpt-4o")

    # 3. 调用 process(msg) — 唯一的入口
    result = await agent.process(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="c1",
            content="Hello! 帮我搜索今天的 AI 新闻。",
        )
    )
    print(result.content)

asyncio.run(main())
```

!!! tip "一行都不用多写"
    这 25 行已经包含了：会话管理、记忆合并、权限检查、工具执行、错误处理、重试逻辑、成本追踪。无需额外代码。

---

## 为什么选择 llm-harness？

| 方案 | 代价 |
|------|------|
| **LangChain / LangGraph** | 30 万+ 行代码，50+ 依赖，API 频繁变更，学习周期数周 |
| **从零手写** | 每次 2–4 周重复造轮子：循环、重试、注册表、会话、权限、钩子 |
| **llm-harness** | ~13,000 行，一个下午读完。MIT 许可证，可自由修改。 |

---

## 核心架构

### 一次工具调用的完整管线

```
LLM → 权限检查 → Hook(PRE) → 工具执行 → Hook(POST) → LLM
```

每一步都是可插拔的。你不需要写任何管线代码 — Harness 已经帮你接好。

### 系统总览

```
┌──────────────────────────────────────────────────┐
│  Agent.process(msg) → OutboundMessage            │
├──────────────────────────────────────────────────┤
│  Harness                                         │
│                                                  │
│  消息管线:                                        │
│    会话 → 记忆合并 → 上下文构建 → ReAct 循环       │
│                                                  │
│  工具管线:                                        │
│    查找 → 校验 → 权限 → 执行                      │
├──────────────────────────────────────────────────┤
│  组件库                                           │
│  工具 │ LLM 提供者 │ 权限系统 │ 钩子              │
│  会话 │ 记忆 │ 观测 │ 定时 │ MCP                 │
│  消息通道 │ 命令 │ 插件 │ 沙箱                   │
└──────────────────────────────────────────────────┘
```

---

## 快速导航

<div class="grid cards" markdown>

-   :fontawesome-solid-graduation-cap: **教程**

    ---

    跟我做，5 分钟跑起第一个 Agent。

    [快速开始 →](tutorials/quick-start.md){ .md-button .md-button--primary }
    [编写自定义工具 →](tutorials/custom-tool.md){ .md-button }
    [配置文件驱动 →](tutorials/config-driven.md){ .md-button }

-   :fontawesome-solid-book: **指南**

    ---

    解决具体问题：部署、通道、定时、观测。

    [部署到 K8s](how-to/deploy-k8s.md){ .md-button }
    [对接微信/飞书](how-to/multi-channel.md){ .md-button }
    [创建定时任务](how-to/use-cron.md){ .md-button }
    [开启观测追踪](how-to/enable-observability.md){ .md-button }

-   :fontawesome-solid-book-open: **API 参考**

    ---

    完整的模块、类、方法参考文档。

    [Harness](api/harness.md){ .md-button }
    [Agent](api/agent.md){ .md-button }
    [工具](api/tools.md){ .md-button }
    [配置](api/config.md){ .md-button }

-   :fontawesome-solid-diagram-project: **解释**

    ---

    理解设计决策、架构原理、并发模型。

    [架构设计](explanation/architecture.md){ .md-button }
    [设计决策](explanation/design-decisions.md){ .md-button }
    [工具执行管线](explanation/pipeline.md){ .md-button }
    [记忆模型](explanation/memory-model.md){ .md-button }

</div>
