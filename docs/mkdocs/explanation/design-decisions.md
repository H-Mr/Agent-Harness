# 设计决策

本文档深入讨论 llm-harness 的关键设计决策——**为什么**这样设计，而不是"怎么做"。每个决策都附有对替代方案的对比和权衡分析。

---

## 为什么回调注入而不是继承

在 Agent 框架的架构选择中，有两种经典模式：

- **继承**：基类定义抽象方法，子类覆盖它们
- **回调注入**：基类接收 `dataclass` 或函数作为参数

llm-harness 选择了后者，具体体现在 [`LoopCallbacks`][agent-harness-loop-agent-loopcallbacks]：

```python
@dataclass
class LoopCallbacks:
    build_messages: Callable[..., list[dict[str, Any]]]
    execute_tool: Callable[[str, dict[str, Any]], Awaitable[str]]
    get_tool_definitions: Callable[[], list[dict[str, Any]]]
    on_progress: Callable[[str, bool], Awaitable[None]] | None = None
    on_stream: Callable[[str], Awaitable[None]] | None = None
    on_event: Callable[[object], Awaitable[None]] | None = None
    ...
```

### 为什么不继承

假设采用继承方式，`AgentLoop` 会是一个抽象基类：

```python
class AgentLoopBase(ABC):
    @abstractmethod
    async def build_messages(self, msg) -> list[dict]: ...
    @abstractmethod
    async def execute_tool(self, name, args) -> str: ...
    @abstractmethod
    def get_tool_definitions(self) -> list[dict]: ...

    async def run_react_loop(self, messages):
        # ReAct 循环逻辑
        ...
```

这种方式的三个问题：

1. **单一继承的僵化**：一个 Agent 只能继承一个基类。如果你想混合 Harness 的行为和另一种数据源的行为，你需要在继承链上做文章，或者在子类里硬编码新的逻辑。
2. **测试困难**：要测试 `run_react_loop` 的逻辑，你需要写一个完整的子类。超过行数的子类可能包含你的测试不需要的行为。
3. **无法热替换**：运行时无法替换回调。如果你在运行中想切换工具实现，继承帮不了你。

### 回调注入的优点

- **关注点分离**：`AgentLoop` 只关心 ReAct 循环的逻辑（"怎么做"），不关心工具是什么、消息如何组装（"做什么"）
- **组合优于继承**：`Agent._build_loop()` 可以从 Harness 的各个部分组合出回调
- **可测试性**：测试 `run_react_loop` 时，只需传一个模拟的 `LoopCallbacks`：

```python
callbacks = LoopCallbacks(
    build_messages=lambda *a, **kw: [{"role": "user", "content": "test"}],
    execute_tool=lambda name, args: f"fake result for {name}",
    get_tool_definitions=lambda: [],
)
loop = AgentLoop(provider, callbacks)
result = await loop.run_react_loop(initial_messages)
```

### 与 nanobot 和 OpenHarness 的对比

| 方案 | 耦合度 | 运行时替换 | 测试便利性 | 代码复杂度 |
|------|--------|-----------|-----------|-----------|
| **继承** (naive) | 高 | 不支持 | 需要建子类 | 低 |
| **继承 + 钩子** (nanobot) | 中 | 有限制 | 中等 | 中 |
| **插件** (OpenHarness) | 低 | 支持 | 容易 | 高（插件 API） |
| **回调注入** (llm-harness) | 极低 | 支持 | 极容易 | 极低 |

llm-harness 选择了最简单的方案——`LoopCallbacks` 只是一个 `dataclass`，没有任何框架性要求。你甚至可以在同一个进程中创建多个 `AgentLoop` 实例，每个传入不同的回调，实现完全不同的行为。

---

## 为什么 Pydantic `input_model` 而不是手写 JSON Schema

每个工具定义自己的输入格式：

```python
class ReadFileInput(BaseModel):
    path: str = Field(description="Path to the file to read")

class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a file"
    input_model = ReadFileInput

    async def execute(self, arguments: ReadFileInput, context) -> ToolResult:
        content = Path(arguments.path).read_text()
        return ToolResult(output=content)
```

### 手写 JSON Schema 有何问题

不采用 Pydantic 的方案通常需要手写 `parameters` 定义：

```python
# nanobot 中的 cast_params / validate_params
MANUAL_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the file to read"}
    },
    "required": ["path"],
}

# 还需要配套的 Python 类型校验（~170 行冗余代码）
def validate_read_file_args(args: dict) -> ReadFileInput:
    if "path" not in args:
        raise ValueError("path is required")
    ...
```

这将导致三个问题：

1. **两份定义**：JSON Schema 一份，Python 校验逻辑一份。它们总会不同步。
2. **重复的模式代码**：每个工具都要写类似的校验逻辑，累积 ~170 行冗余代码（如 nanobot 中 `cast_params` / `validate_params` 的辅助函数）。
3. **没有 IDE 支持**：手写 `dict` 无法获得自动补全和类型检查。

### Pydantic 的优势

- **单一事实源**：`input_model` 同时提供类型注解、校验规则、JSON Schema 生成
- **零额外代码**：[`BaseTool.to_api_schema()`][agent-harness-tools-base-basetool] 自动将 `input_model.model_json_schema()` 转换为 OpenAI 或 Anthropic 格式
- **Pydantic v2 性能**：原生 Rust 核心，校验速度是手写方案的数倍

```python
# 自动转换：OpenAI function calling 格式
def to_openai_schema(self) -> dict:
    return {
        "type": "function",
        "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
        },
    }
```

每种工具只需要关注 `input_model` 的类型定义，JSON Schema 的格式转换是自动化的——零手工劳动。

---

## 为什么 `process(msg)` 是唯一入口

```python
class Agent:
    async def process(self, msg: InboundMessage) -> OutboundMessage | None:
        ...
```

这看起来是一个武断的限制——为什么不是 `process_text(text)`、`process_stream(chunk)` 等？原因有三：

### 1. 通道无关性

`InboundMessage` 的设计是对所有输入通道的归一化：

| 通道 | 原始格式 | 归一化为 InboundMessage |
|------|---------|------------------------|
| CLI | `sys.stdin.readline()` | `channel="cli"` |
| HTTP | POST body | `channel="http"` |
| WebSocket | `ws.receive()` | `channel="ws"` |
| 微信 | XML 消息 | `channel="wechat"` |
| 飞书 | Event callback | `channel="feishu"` |
| Telegram | Update | `channel="telegram"` |

归一化的关键是 `session_key` 属性：

```python
@property
def session_key(self) -> str:
    return self.session_key_override or f"{self.channel}:{self.chat_id}"
```

这个 `session_key` 驱动了会话管理（`SessionManager.get_or_create(key)`）和并发控制（per-session Lock）。所有通道的会话隔离通过同一种机制完成。

### 2. 管线确定性

单一入口意味着 Agent 的处理管线是确定性的：

```
Session → Consolidation → Context → ReAct → Persist → OutboundMessage
```

不会有"绕过"某个步骤的路径。当你需要调试某个行为时，你知道它一定经过了这个管线。

### 3. 组合性

因为所有处理走同一个入口，你可以：

- **包装 Agent**：加缓存层、速率限制层、日志层
- **代理 Agent**：在 `process()` 前后插入自定义逻辑
- **路由消息**：根据 `msg.channel` 或 `msg.session_key` 路由到不同的 Agent 实例

```python
class RateLimitedAgent:
    def __init__(self, agent: Agent, rpm: int):
        self._agent = agent
        self._limiter = RateLimiter(rpm)

    async def process(self, msg: InboundMessage) -> OutboundMessage | None:
        async with self._limiter:
            return await self._agent.process(msg)
```

这种方式比多入口设计（`process_cli()`、`process_http()` 等）更简洁——不需要为每个通道写一个入口。

---

## 为什么 Memory/Sessions 默认不启用

```python
class Harness:
    def __init__(self, ..., memory=None, sessions=None):
        self.memory = self._resolve_memory(memory)     # → None
        self.sessions = self._resolve_sessions(sessions)  # → None
```

在 `Harness` 的构造函数中，`memory` 和 `sessions` 的默认值是 `None`。这意味着在最简单的使用场景下，Agent 是**无状态的**——每次 `process()` 调用都是独立的，没有历史、没有记忆。

### 显式优于隐式

如果默认启用持久化，用户会惊讶于：

- 为什么磁盘上出现了 `.agent-harness/sessions/` 目录？
- 为什么每次对话都变慢（因为加载历史）？
- 为什么会有 token 消耗在记忆合并上？

llm-harness 的原则是：**你不显式要求的特性，不产生任何影响**。

```python
# 无状态：无额外开销
agent = Agent(Harness(provider=provider), model="gpt-4")

# 有状态：显式启用
agent = Agent(Harness(
    provider=provider,
    sessions=Path("~/.my-agent/sessions"),  # → SessionManager
    memory=Path("~/.my-agent/memory"),      # → MemoryStore
), model="gpt-4")
```

### 对代码的简化

当 `sessions=None` 时，`Agent.process()` 中的三个步骤被跳过：

1. **无会话管理**：不加载/创建 `Session` 对象
2. **无记忆合并**：`MemoryConsolidator` 对象不被创建
3. **无持久化**：`_save_turn()` 不执行

```python
async def process(self, msg: InboundMessage) -> OutboundMessage | None:
    async with lock, gate:
        session = None
        history = []

        if self.harness.sessions is not None:    # 可选：会话
            session = self.harness.sessions.get_or_create(msg.session_key)
            history = session.get_history()
            session.add_message("user", msg.content)

        if self._consolidator is not None and session is not None:  # 可选：记忆合并
            await self._consolidator.maybe_consolidate_by_tokens(session)

        messages = await self.harness.on_build_context(msg, history)
        result = await self._loop.run_react_loop(messages)

        if session is not None:                  # 可选：持久化
            self._save_turn(session, result)
        ...
```

这个设计带来的一个"副作用"是——`Agent` 的默认行为非常接近于一个无状态的 LLM 调用封装，这让初次使用者可以更快地理解核心概念，再逐步添加持久化。

---

## 为什么 `tzdata` 进入核心依赖

这是来自 Windows 用户的一个现实问题。Python 的 `datetime` 模块在 Windows 上没有内置的时区数据库——它依赖操作系统的时区信息。而 Windows 的时区数据库格式与 Python 的 `zoneinfo` 不兼容。

如果不在 `pyproject.toml` 中声明 `tzdata` 依赖，Windows 用户会看到：

```
ModuleNotFoundError: No module named 'tzdata'
```

这发生在所有涉及 `datetime.now(tz=...)` 的地方——而项目中有超过 20 处使用了带时区的 `datetime` 操作。

### 为什么不在文档中单独提一句"Windows 用户请安装 tzdata"

隐式依赖是糟糕的用户体验。`tzdata` 是纯 Python 包（~400KB），只提供时区数据，没有任何运行时开销。把它放到核心依赖中：

- **零心智负担**：所有平台开箱即用
- **零运行时成本**：`tzdata` 仅在你明确导入 `zoneinfo` 时才会被加载
- **消除一个常见的 "works on my machine" 问题**

```toml
# pyproject.toml
[project]
dependencies = [
    "pydantic>=2.0",
    "httpx>=0.27",
    "tzdata>=2024.1",  # Windows 兼容性
]
```

相比之下，很多 Python 项目把 `tzdata` 作为可选依赖或完全忽略 Windows 用户。llm-harness 选择显式处理这个问题，因为 Agent 框架的定位是"可运行的基座"，而不是"需要半天配置的开发环境"。

---

## 为什么选择 Material for MkDocs 而不是 Sphinx

| 维度 | Material for MkDocs | Sphinx (Read the Docs) |
|------|-------------------|----------------------|
| **配置** | 1 个 `mkdocs.yml`，~70 行 | `conf.py` + `.rst` 文件，~200 行 |
| **中文支持** | 原生，`language: zh` | 需要 `sphinx-intl` 扩展 |
| **Mermaid** | 内建支持（`pymdownx.superfences`） | 需要 `sphinxcontrib-mermaid` |
| **搜索** | 内建 lunr.js 搜索 | 内建搜索 |
| **主题** | Material Design，开箱即用 | 需要安装和配置主题扩展 |
| **Python API 文档** | 通过 `mkdocstrings` 插件 | 原生支持（`autodoc`） |
| **社区趋势** | 快速增长，尤其在中国开发者中 | 稳定但增长缓慢 |

### 生态趋势

2023–2026 年间，Python 项目文档的偏好发生了显著变化：

- 大量新项目（FastAPI、Pydantic、SQLModel、LangChain）选择 MkDocs + Material
- Sphinx 的使用场景逐渐收缩到：需要 `.. autosummary::` 的深层嵌套 API 文档、大型 Python 库（如 Django、NumPy）
- MkDocs 的 `mkdocstrings` 插件已经能生成与 Sphinx `autodoc` 同等质量的 API 文档

对于 llm-harness 这样一个 ~13,000 行代码的项目，Material for MkDocs 的轻量级配置（70 行 `mkdocs.yml`）、原生 Mermaid 支持、和出色的移动端适配，使其成为没有悬念的选择。

### 一个务实的理由

llm-harness 的目标用户是**中文开发者**。Material for MkDocs 对中日韩（CJK）语言的内建支持（搜索分词、字体渲染）远好于 Sphinx 的默认配置。当你将 `language: zh` 在 Material 主题中设置，搜索自动使用适合中文的分词器——不需要额外配置。

---

## 为什么不做编排引擎（vs LangChain）

这是 llm-harness 最基本的设计哲学分歧。

LangChain 的核心价值是**编排**——它定义了一种编程模型（Chains、Runnables、LCEL），让你以声明方式组合 LLM 调用、工具调用和数据变换。LangGraph 把这个概念扩展到了有状态图。

llm-harness 的定位是**基座**，而不是编排引擎。这里的区别是：

### 基座 vs 编排引擎

| 维度 | 基座 (llm-harness) | 编排引擎 (LangChain) |
|------|-------------------|---------------------|
| **你得到** | 所有非 LLM 的基础设施：工具、权限、记忆、会话、观测 | 一种组织和组合 LLM 调用的范式 |
| **你需要** | 自己写或少量的 ReAct 循环 | 学习和适应编排范式 |
| **定制路径** | 替换零件的实现 | 理解和扩展框架的抽象层 |
| **升级风险** | 极低——接口稳定，零件独立 | 中高——抽象层经常变动 |
| **与你的代码的耦合** | 通过接口调用 | 通过继承/组合/LCEL 表达式 |

### 为什么 llm-harness 选择基座

1. **Agent 的核心逻辑极其简单**：循环调用 LLM、执行工具、返回结果。ReAct 循环的核心代码在 `AgentLoop.run_react_loop()` 中只有 ~130 行。它不需要被抽象成一个编排框架。

2. **基础设施才是难点**：实操中，构建一个生产级 Agent 的大部分工作不在循环逻辑，而在工具注册、权限管理、会话持久化、并发控制、错误重试、可观测性。llm-harness 专注解决这些问题。

3. **不替你决定编排方式**：你可以用 llm-harness 的零件配合任何循环逻辑——ReAct、Plan-and-Execute、Tree-of-Thought、甚至你自己的自定义循环。你只需要实现自己的 `AgentLoop` 并注入 `LoopCallbacks`。

```python
# 如果你想用 Plan-and-Execute 而非 ReAct：
class PlanExecuteLoop:
    """你自己的循环实现，复用 Harness 的零件"""
    async def run(self, msg):
        plan = await self.provider.chat(msg, tools=[make_plan])
        for step in plan.steps:
            result = await execute_tool(step.tool, step.args)
        return result

# 这完全可行——你不受 AgentLoop 的限制
```

### 现实的考虑

LangChain 有 300,000+ 行代码和 50+ 子包。即使只是理解它的依赖树就需要数天。对于大多数 Agent 开发场景，这引入了不必要的复杂度和维护成本。

llm-harness 的约 13,000 行代码可以在一个下午读完。如果某个部分不符合你的需求，你可以 fork 并修改它——因为 MIT 许可证给了你做任何事情的自由。

这不是说编排引擎没有价值——对于复杂的、需要细粒度控制的多步工作流，LangGraph 等工具有其适用场景。但对于构建一个 AI Agent（一个独立的、能与用户对话并执行工具的系统），llm-harness 的基座哲学提供了更低的复杂度和更好的可控性。

[agent-harness-loop-agent-loopcallbacks]: ../api/loop.md
[agent-harness-tools-base-basetool]: ../api/tools.md
