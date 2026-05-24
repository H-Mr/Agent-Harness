# llm-harness

[![PyPI version](https://img.shields.io/pypi/v/llm-harness)](https://pypi.org/project/llm-harness/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-337%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![Docs](https://img.shields.io/badge/docs-中文文档-3949ab)](https://h-mr.github.io/llm-harness/)

**生产级可复用的 AI Agent 基础设施基座 — 约 13,000 行 Python，337 项测试。**

```
Harness + LLM = Agent
```

Harness 处理 LLM 推理之外的一切：工具管线、权限检查、会话持久化、记忆合并、钩子系统、观测追踪。Agent 只有 `process(msg)` 一个方法。

```python
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage
from agent_harness.prompts.sections import IdentitySection

agent = Agent(
    Harness(
        provider=OpenAICompatProvider(api_key="sk-...", api_base="https://api.openai.com/v1"),
        tools=["read_file", "write_file", "exec", "web_search"],
        context=[IdentitySection("你是一个有用的助手。")],
    ),
    model="gpt-4o",
)

result = await agent.process(
    InboundMessage(channel="cli", sender_id="user", chat_id="c1", content="你好！")
)
print(result.content)
```

---

## 为什么选择 llm-harness？

| 方案 | 代价 |
|------|------|
| **LangChain / LangGraph** | 30 万+ 行，50+ 依赖，API 频繁变动，学习曲线以周计 |
| **从零手写** | 每次 2–4 周重写循环、重试、注册表、会话、权限、钩子 |
| **llm-harness** | ~13,000 行。一个下午读完。放心 Fork。MIT 协议。 |

---

## 快速导航

| 想做什么 | 去看 |
|---------|------|
| 5 分钟跑起第一个 Agent | [快速开始](https://h-mr.github.io/llm-harness/tutorials/quick-start/) |
| 写一个自定义工具 | [编写自定义工具](https://h-mr.github.io/llm-harness/tutorials/custom-tool/) |
| JSON 配置文件驱动 | [配置文件驱动](https://h-mr.github.io/llm-harness/tutorials/config-driven/) |
| 部署到 K8s | [部署到 K8s](https://h-mr.github.io/llm-harness/how-to/deploy-k8s/) |
| 对接微信/飞书 | [多通道接入](https://h-mr.github.io/llm-harness/how-to/multi-channel/) |
| 创建定时任务 | [使用 Cron](https://h-mr.github.io/llm-harness/how-to/use-cron/) |
| 开启观测追踪 | [观测系统](https://h-mr.github.io/llm-harness/how-to/enable-observability/) |
| 查 API 参考 | [API 参考](https://h-mr.github.io/llm-harness/api/harness/) |
| 理解设计决策 | [架构设计](https://h-mr.github.io/llm-harness/explanation/architecture/) |

**完整文档：** https://h-mr.github.io/llm-harness/

---

## 架构

每次工具调用流经一条管线：

```
LLM → Permission.check → Hook.execute(PRE) → Tool.execute → Hook.execute(POST) → LLM
```

```
llm-harness/
  harness.py        Harness — 基础设施容器 + from_config()
  agent.py          Agent — 唯一入口 process(msg)
  loop/             ReAct 骨架 + 并发控制 (per-session Lock + Semaphore)
  tools/            28 个内置工具 + 配置驱动构建器
  providers/        25 个 LLM 后端 (Anthropic + OpenAI 兼容)，重试 + 退避
  permissions/      敏感路径保护，3 种模式，路径/命令规则
  hooks/            PreToolUse/PostToolUse，4 种钩子类型
  security/         SSRF 防护 (DNS + 私有 IP 拦截)
  sandbox/          OS 级隔离 (srt CLI)，内建 ExecTool
  session/          JSONL 持久化 + 合法边界对齐
  memory/           双层记忆 (MEMORY.md + HISTORY.md) + LLM 合并
  channels/         BaseChannel ABC + 微信 + 飞书实现
  cron/             调度器 (at/every/cron) + 管理工具
  observability/    17 种事件 + EventBus + JSONL 追踪器
  config/           多层配置 (CLI > env > file > defaults)
```

---

## 安装

```bash
pip install llm-harness               # 基础
pip install llm-harness[anthropic]    # + Claude
pip install llm-harness[openai]       # + OpenAI
pip install llm-harness[all]          # 全部
pip install llm-harness[dev]          # + pytest, ruff
```

要求：Python >= 3.10

---

## 面向国内开发者

通过 `OpenAICompatProvider` 原生兼容国内主流平台，只需修改 `api_base`：

```python
# DeepSeek
OpenAICompatProvider(api_key="sk-...", api_base="https://api.deepseek.com/v1")

# 阿里云百炼 (DashScope)
OpenAICompatProvider(api_key="sk-...", api_base="https://dashscope.aliyuncs.com/compatible-mode/v1")

# 智谱 (Zhipu)
OpenAICompatProvider(api_key="...", api_base="https://open.bigmodel.cn/api/paas/v4")

# 硅基流动 (SiliconFlow)
OpenAICompatProvider(api_key="sk-...", api_base="https://api.siliconflow.cn/v1")

# 火山引擎 (Volcengine)
OpenAICompatProvider(api_key="sk-...", api_base="https://ark.cn-beijing.volces.com/api/v3")
```

---

## 测试

```
337 passed, 9 skipped, 0 failed
```

## 设计原则

1. **Harness + LLM = Agent。** Harness 处理一切非 LLM 推理。Agent 只有一个 `process(msg)` 方法。
2. **回调注入，非继承。** 所有行为通过 `LoopCallbacks` 注入，循环对你的工具和提示词一无所知。
3. **配置驱动。** 通过 JSON 切换行为。工具、权限、Provider、沙箱、观测——无需改代码。
4. **传输无关。** `BaseChannel` 定义契约。CLI、HTTP、WebSocket、微信、飞书——同一个接口。
5. **你掌控代码。** ~13,000 行。放心 Fork。随意修改。无需学习框架。

## License

MIT — see [LICENSE](LICENSE).

## Credits

提炼自两个成熟的开源 Agent 项目：

- [OpenHarness](https://github.com/HKUDS/OpenHarness) — tools, permissions, hooks, skills, sandbox, plugins, tasks
- [nanobot](https://github.com/HKUDS/nanobot) — agent loop, providers, message bus, session, memory, cron, channels
