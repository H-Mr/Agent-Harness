# llm-harness

**生产级可复用的 AI 智能体基础设施。**

```
Harness + LLM = Agent
```

llm-harness 是连接 LLM 与业务逻辑的基础设施层 — 每个智能体都需要的管道工程，但没人愿意从头编写。约 13,000 行 Python，337 项测试，MIT 开源协议。

<div class="grid cards" markdown>

-   **25 行代码构建智能体**

    ---

    Harness 帮你处理好工具、权限、记忆、会话和可观测性。`Agent(Harness(...), model="gpt-4o").process(msg)` 即可启动。

-   **28 个内置工具**

    ---

    文件 I/O、Shell 执行、Web 搜索、Glob/Grep、Notebook 编辑、定时任务。配置驱动 — 用 `["*"]` 一键启用全部。

-   **纵深防御**

    ---

    SSRF 防护、敏感路径拦截、3 种权限模式、Pre/Post 工具钩子、基于 `srt` 的 OS 级沙箱。

-   **可观测性优先**

    ---

    17 种结构化事件类型、异步 EventBus、JSONL 追踪器。配置即自动启用，关闭时零开销。

</div>

---

## 为什么选择 llm-harness？

| 方案 | 代价 |
|------|------|
| **LangChain / LangGraph** | 30 万+ 行代码，50+ 依赖，API 频繁变更，学习成本数周 |
| **从零自建** | 2–4 周重新实现交互循环、重试、注册表、会话、权限、钩子 |
| **llm-harness** | ~13,000 行。一个下午读完。放心 Fork。MIT 协议。 |

---

## 面向国内开发者

llm-harness 通过 `OpenAICompatProvider` 原生兼容国内主流大模型平台，无需额外适配：

| 平台 | 接入方式 |
|------|----------|
| **DeepSeek** | `OpenAICompatProvider(api_key="sk-...", api_base="https://api.deepseek.com/v1")` |
| **阿里云百炼 (DashScope)** | `OpenAICompatProvider(api_key="sk-...", api_base="https://dashscope.aliyuncs.com/compatible-mode/v1")` |
| **智谱 (Zhipu)** | `OpenAICompatProvider(api_key="sk-...", api_base="https://open.bigmodel.cn/api/paas/v4")` |
| **硅基流动 (SiliconFlow)** | `OpenAICompatProvider(api_key="sk-...", api_base="https://api.siliconflow.cn/v1")` |
| **火山引擎 (Volcengine)** | `OpenAICompatProvider(api_key="sk-...", api_base="https://ark.cn-beijing.volces.com/api/v3")` |

只需修改 `api_base` 即可切换模型提供商，现有工具链、权限策略和可观测性系统完全复用，无需任何额外适配工作。

---

## 架构

每次工具调用都会流经一条你从未需要编写的管道：

```
LLM → Permission.check → Hook.execute(PRE) → Tool.execute → Hook.execute(POST) → LLM
```

每条消息流经 8 步处理管道：

```
Session → Consolidation → Context → ReAct → Persist → OutboundMessage
```

```mermaid
block-beta
  columns 1
  block:agent["Agent.process(msg) → OutboundMessage"]
  block:harness["Harness<br/>消息管线: Session→Memory→Context<br/>工具管线: Lookup→Validate→Execute"]
  block:parts["零件库: tools · providers · permissions · hooks · session · memory · observability · cron · mcp · channels"]
  agent --> harness --> parts
```

---

## 快速导航

<div class="grid cards" markdown>

-   :material-school-outline:{ .lg .middle } **教程**

    ---

    按照分步指南，在 5 分钟内运行你的第一个智能体。

    [:octicons-arrow-right-24: 快速入门](tutorials/quick-start.md){ .md-button }

-   :material-book-open-page-variant-outline:{ .lg .middle } **操作指南**

    ---

    解决具体问题：部署、添加渠道、定时任务、启用链路追踪。

    [:octicons-arrow-right-24: 部署到 K8s](how-to/deploy-k8s.md){ .md-button }

-   :material-bookshelf:{ .lg .middle } **API 参考**

    ---

    完整的模块、类和函数参考，从源码自动生成。

    [:octicons-arrow-right-24: Harness API](api/harness.md){ .md-button }

-   :material-graph-outline:{ .lg .middle } **原理说明**

    ---

    理解设计决策、架构、并发模型和记忆系统。

    [:octicons-arrow-right-24: 架构设计](explanation/architecture.md){ .md-button }

</div>
