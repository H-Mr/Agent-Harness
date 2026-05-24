# 教程：快速开始

本教程将带你**在 5 分钟内跑起第一个 AI Agent**。你只需要一个 Python 环境和 API Key。

---

## 安装

### 基础安装

```bash
pip install llm-harness
```

这只会安装核心依赖（Pydantic、httpx、MCP 等），不包含任何 LLM SDK。

### 完整安装（推荐）

```bash
pip install llm-harness[all]
```

这会一并安装：
- `anthropic` — Anthropic Claude SDK
- `openai` — OpenAI SDK（也用于所有兼容 OpenAI API 的提供商）
- `ddgs` — DuckDuckGo 搜索（Web Search 工具）
- `readability-lxml` + `chardet` — 网页内容提取

!!! tip "按需安装"
    如果你只用某一个 LLM 提供商，可以只装对应的依赖：
    ```bash
    pip install llm-harness[anthropic]   # 只用 Claude
    pip install llm-harness[openai]      # 只用 OpenAI 及兼容提供商
    pip install llm-harness[openai,tools]  # OpenAI + Web 搜索工具
    ```

---

## 第一个 Agent

创建 `agent.py`：

```python title="agent.py"
import asyncio
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage
from agent_harness.prompts.sections import IdentitySection

async def main():
    # ---- 第 1 步：创建 Harness ----
    harness = Harness(
        provider=OpenAICompatProvider(
            api_key="sk-...",              # 替换为你的 API Key
            api_base="https://api.openai.com/v1",
        ),
        tools=["read_file", "write_file", "exec", "web_search"],
        context=[IdentitySection("你是一个有用的助手。你可以读写文件、执行命令和搜索网络。")],
    )

    # ---- 第 2 步：创建 Agent ----
    agent = Agent(harness, model="gpt-4o")

    # ---- 第 3 步：发送消息 ----
    result = await agent.process(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="session-1",
            content="你好！请搜索一下今天 Python 的最新动态。",
        )
    )

    print("Agent 回复:", result.content)

asyncio.run(main())
```

### 逐行讲解

| 代码 | 说明 |
|------|------|
| `Harness(...)` | 基础设施容器。接收 LLM 提供者、工具列表、系统提示词等。 |
| `OpenAICompatProvider(api_key, api_base)` | LLM 提供者。所有兼容 OpenAI API 格式的模型都用这个类。 |
| `tools=[...]` | 内置工具列表。传入名字字符串，Harness 自动创建并注册。 |
| `context=[IdentitySection(...)]` | 系统提示词。`IdentitySection` 是最简单的形式。 |
| `Agent(harness, model="gpt-4o")` | 把 Harness 和模型名组合成一个可运行的 Agent。 |
| `agent.process(InboundMessage(...))` | **唯一的入口方法**。传入消息，返回回复。 |

!!! warning "请替换 API Key"
    运行前务必将 `api_key` 替换为你自己的有效 API Key。如使用 OpenAI，可在 [platform.openai.com/api-keys](https://platform.openai.com/api-keys) 获取。

### 运行

```bash
python agent.py
```

你会看到 Agent 调用 `web_search` 工具搜索网络，然后返回结果。

---

## 加入记忆和会话

上面的例子每次运行都是"失忆"的。加上会话和记忆，Agent 就能记住上下文：

```python hl_lines="3-5 10 17"
async def main():
    harness = Harness(
        provider=OpenAICompatProvider(api_key="sk-...", api_base="https://api.openai.com/v1"),
        tools=["read_file", "write_file", "exec", "web_search"],
        memory="~/.my-agent/memory",        # 持久化记忆目录
        sessions="~/.my-agent/sessions",    # 会话存储目录
        context=[IdentitySection("你是一个有用的助手。")],
    )

    agent = Agent(harness, model="gpt-4o")

    # 第一次对话
    r1 = await agent.process(InboundMessage("cli", "user", "c1", "我叫小明"))
    print(r1.content)

    # 第二次对话 — Agent 还记得你叫小明！
    r2 = await agent.process(InboundMessage("cli", "user", "c1", "我叫什么名字？"))
    print(r2.content)  # 应该回答：你叫小明
```

!!! note "会话与记忆的区别"
    - **会话**（Session）：保存完整的对话历史（消息列表），用于多轮对话。
    - **记忆**（Memory）：保存长期事实（`MEMORY.md`），Agent 会自动归纳和更新。

---

## 配置文件驱动

把配置写在 `config.json` 里，代码可以更简洁：

```json title="config.json"
{
    "agent": {
        "model": "gpt-4o",
        "api_key": "sk-...",
        "api_base": "https://api.openai.com/v1",
        "workspace": "~/.my-agent"
    },
    "tools": {
        "enabled": ["read_file", "write_file", "exec", "web_search"]
    }
}
```

```python title="run.py"
import asyncio
from agent_harness import Agent, Harness, load_config

async def main():
    config = load_config()  # 自动读取 config.json
    harness = Harness.from_config(config)
    agent = Agent(harness)

    # 创建 InboundMessage 可以用更简洁的方式
    from agent_harness import InboundMessage as Msg

    result = await agent.process(Msg("cli", "user", "c1", "Hello!"))
    print(result.content)

asyncio.run(main())
```

!!! tip "默认配置路径"
    `load_config()` 默认读取 `~/.agent-harness/config.json`，也可以通过环境变量 `HARNESS_CONFIG_PATH` 指定路径。

配置文件驱动的详细教程请参见[配置文件驱动](config-driven.md)。

---

## 切换 LLM 提供者

llm-harness 支持**几乎所有的 LLM 提供商**。切换只需修改 provider 和 model 参数：

=== "OpenAI"
    ```python
    OpenAICompatProvider(
        api_key="sk-...",
        api_base="https://api.openai.com/v1",
    )
    # model: "gpt-4o", "gpt-4o-mini", "gpt-4.1" ...
    ```

=== "Anthropic Claude"
    ```python
    from agent_harness import AnthropicProvider

    AnthropicProvider(
        api_key="sk-ant-...",
    )
    # model: "claude-sonnet-4-20250514", "claude-3-5-sonnet-latest" ...
    ```

=== "DeepSeek"
    ```python
    OpenAICompatProvider(
        api_key="sk-...",
        api_base="https://api.deepseek.com",
    )
    # model: "deepseek-chat", "deepseek-reasoner"
    ```

=== "阿里百炼 (DashScope)"
    ```python
    OpenAICompatProvider(
        api_key="sk-...",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    # model: "qwen-max", "qwen-plus" ...
    ```

=== "智谱 (Zhipu)"
    ```python
    OpenAICompatProvider(
        api_key="xxx",
        api_base="https://open.bigmodel.cn/api/paas/v4",
    )
    # model: "glm-4-plus", "glm-4v" ...
    ```

=== "本地模型 (Ollama)"
    ```python
    OpenAICompatProvider(
        api_base="http://localhost:11434/v1",
    )
    # model: "llama3", "qwen2.5", "nemotron" ...
    ```

!!! tip "自动检测"
    如果 `provider` 设为 `"auto"`（默认值），Harness 会根据模型名、API Key 前缀和 API Base URL 自动判断提供商。大多数情况下你只需要设置 `model` 和 `api_key`。

---

## 本地预览文档

如果你想在本地查看这份文档：

```bash
# 安装 MkDocs 和 Material 主题
pip install mkdocs mkdocs-material mkdocstrings[python]

# 在项目根目录启动
mkdocs serve

# 浏览器打开 http://127.0.0.1:8000
```

---

## 下一步

- [编写自定义工具](custom-tool.md) — 扩展 Agent 的能力
- [配置文件驱动](config-driven.md) — 用 JSON 配置整个 Agent
- [架构设计](../explanation/architecture.md) — 理解整体设计
