# Day 1：总览 — 这个项目解决了什么问题

> **目标读者**：有 Python 基础、想深入理解 AI Agent 基础设施内部设计的开发者。
> **学完本节后，你应该能回答**：agent-harness 和 LangChain 的核心设计差异在哪？Harness 和 Agent 为什么分开？`agent.process(msg)` 调用一次，内部发生了什么？

---

## 一、深度解释

### 1.1 问题：构建一个生产级 Agent，到底难在哪？

写一个调用 LLM 的脚本很简单：

```python
response = client.chat.completions.create(model="gpt-4", messages=[...])
print(response.choices[0].message.content)
```

但把它变成一个**生产可用的 Agent**，问题就接踵而至：

- **工具调用**：LLM 返回 `tool_calls` 后，你要解析参数、调用真实函数、把结果塞回对话、再调 LLM —— 这个过程叫 **ReAct 循环**。你得自己写 `while` 循环、处理并发、截断过长的工具结果。
- **权限控制**：不是所有工具都该对 LLM 开放。`exec`（执行 shell 命令）不能随便调，`read_file` 不能读 `/etc/shadow`。你需要一个权限检查层。
- **多会话隔离**：用户 A 和用户 B 的对话不能互相干扰。同一用户的消息要串行处理，不同用户可以并行。你需要 per-session Lock + 全局 Semaphore。
- **持久化**：会话历史要存盘，重启后恢复。Agent 的记忆要在多次对话间 consolidated（合并）。
- **可观测性**：每次工具调用花了多久？每次 LLM 调用用了多少 token？哪个环节出错了？你需要事件追踪。
- **LLM Provider 抽象**：今天用 Claude，明天想换 GPT-4o，后天想用 DeepSeek。不能把 provider 硬编码在业务逻辑里。
- **配置驱动**：生产环境要能通过一个 JSON 文件切换所有行为，不能改代码。

每个问题单独看都不难，但把它们**组合在一起、保证 337 项测试全通过、并且只写 ~13,000 行代码**，就需要精心的架构设计了。

### 1.2 为什么不是 LangChain？

LangChain 是目前最流行的 Agent 框架，但 agent-harness 的作者做出了不同的选择。我们来看两段代码的对比：

**LangChain 的典型用法**：

```python
from langchain import ...
from langchain.agents import ...
from langchain.tools import ...
from langchain.memory import ...
# ... 需要导入十几个模块，理解 AgentExecutor、LLMChain、Toolkit、
#     AgentType、OutputParser、CallbackHandler 等概念
# ... 学习曲线以周计
```

**agent-harness 的典型用法**：

```python
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage

agent = Agent(
    Harness(
        provider=OpenAICompatProvider(api_key="...", api_base="..."),
        tools=["read_file", "write_file", "exec", "web_search"],
    ),
    model="gpt-4o",
)
result = await agent.process(InboundMessage(...))
```

核心差异在于**设计哲学**：

| 维度 | LangChain | agent-harness |
|------|-----------|---------------|
| 代码量 | 30 万+ 行，50+ 依赖 | ~13,000 行，零冗余依赖 |
| 学习曲线 | 以周计，API 频繁变动 | 一个下午读完核心代码 |
| 控制权 | 框架控制你的代码 | 你控制框架的代码（MIT 协议，放心 Fork） |
| 抽象方式 | 多层继承 + 抽象类 | **回调注入**（LoopCallbacks），循环对你的逻辑一无所知 |
| 配置 | 代码内配置 | 配置驱动，JSON 文件切换所有行为 |

agent-harness 的核心信念是：**Agent 基础设施不该比 Agent 本身更复杂**。一个 Agent 的核心就是一个 `while` 循环（LLM 调用 -> 工具执行 -> 再调 LLM），所有额外功能（权限、记忆、会话、钩子）都应该是**可插拔的管线**，而不是框架的固有部分。

### 1.3 Harness / Agent 分离：为什么要拆成两个类？

这是整个架构最核心的设计决策。把源码中的类定义放在一起对比：

**Harness** — 基础设施容器（`src/agent_harness/harness.py`）：

```python
class Harness:
    """Infrastructure container that holds all agent parts."""

    def __init__(self, *, provider, workspace, tools, permissions,
                 memory, sessions, context, skills, hooks, tracker,
                 on_tool_check, on_build_context, on_error, ...):
        # 所有参数都是可选的（除 provider 外），每种参数支持多种简写形式
        self.tools = self._resolve_tools(tools)           # list[str] -> ToolRegistry
        self.permissions = self._resolve_permissions(permissions)  # "default" -> PermissionChecker
        self.memory = self._resolve_memory(memory)         # str/Path -> MemoryStore
        self.sessions = self._resolve_sessions(sessions)   # str/Path -> SessionManager
        self.context = self._resolve_context(context)      # list[SectionProvider] -> ContextBuilder
        ...
```

**Agent** — 可运行的 Agent 实例（`src/agent_harness/agent.py`）：

```python
class Agent:
    """Harness + model = a runnable agent."""

    def __init__(self, harness: Harness, *, model: str | None = None,
                 max_iterations: int = 40, max_concurrent: int = 3):
        self.harness = harness
        self.model = model or harness.provider.get_default_model()
        self._loop = self._build_loop()         # 把 Harness 的组件注入 LoopCallbacks
        self._consolidator = ...                # 记忆合并器（仅在需要时创建）
```

**为什么这样设计？**

1. **关注点分离**：Harness 负责"有什么"（工具、权限、记忆...），Agent 负责"怎么用"（process 管线、ReAct 循环）。你可以创建一个 Harness，然后用它构造多个 Agent（不同 model、不同 max_iterations）。

2. **配置友好**：`Harness.from_config(config)` 从一个 JSON 配置对象创建完整的 Harness。这意味着你可以把基础设施配置写成文件，运行时加载，无需改代码。

3. **测试友好**：在测试中，你可以创建一个 Harness，注入 mock provider，然后验证 Agent 的行为 —— 不需要真实的 LLM。

4. **简写解析**：Harness 的构造函数接受多种"简写"形式 —— `tools=["read_file", "exec"]` 会自动展开成 `ToolRegistry`；`permissions="default"` 会自动创建 `PermissionChecker`。这让快速原型变得极其简洁。

### 1.4 `agent.process(msg)` 调用一次，内部发生了什么？

这是 Day 1 最重要的内容。我们把 `Agent.process()` 的完整管线画出来，然后逐步骤解释源码：

```
process(msg)
  │
  ├─ Step 1: 并发控制 ────────────────────────────────── agent.py:174-177
  │   lock = _session_locks[msg.session_key]   # per-session Lock
  │   gate = _concurrency_gate                 # 全局 Semaphore（默认 max=3）
  │   async with lock, gate:
  │
  ├─ Step 2-3: 会话管理 ──────────────────────────────── agent.py:183-189
  │   if self.harness.sessions:
  │       session = sessions.get_or_create(msg.session_key)
  │       history = session.get_history()      # 截取当前历史（不含本条消息）
  │       session.add_message("user", msg.content)
  │       sessions.save(session)
  │
  ├─ Step 4: 记忆合并 ───────────────────────────────── agent.py:192-193
  │   if self._consolidator:
  │       await _consolidator.maybe_consolidate_by_tokens(session)
  │
  ├─ Step 5: 构建消息 ────────────────────────────────── agent.py:196
  │   initial_messages = await harness.on_build_context(msg, history)
  │     ├─ context.build_system_prompt()        # 聚合所有 SectionProvider
  │     └─ context.build_messages(system, history, msg.content)
  │        → [system, *history, user_msg]
  │
  ├─ Step 6: ReAct 循环 ─────────────────────────────── agent.py:199-203
  │   result = await _loop.run_react_loop(initial_messages)
  │     ├─ 调 LLM → 有 tool_calls? ─→ 并发执行工具 → 再调 LLM
  │     └─ 调 LLM → 有 text? ───────→ break，返回 final_content
  │
  ├─ Step 7: 持久化 ─────────────────────────────────── agent.py:206-207
  │   if session:
  │       _save_turn(session, result)           # 保存 assistant + tool 消息
  │
  └─ Step 8: 返回 ───────────────────────────────────── agent.py:213-217
      return OutboundMessage(channel=..., chat_id=..., content=result.final_content)
```

**设计意图**：

- **Step 1（并发控制）**：使用 per-session `asyncio.Lock` + 全局 `asyncio.Semaphore(3)`。同一 session 的消息串行处理，不同 session 的消息最多 3 个并行。`session_key` 默认由 `channel:chat_id` 组成（定义在 `InboundMessage.session_key` 属性中），来自同一个 IM 群聊的消息不会并发执行。
- **Step 4（记忆合并）**：这是 agent-harness 的特色功能。`MemoryConsolidator` 会检查当前 session 的 token 数是否接近 context window 上限，如果是，就用 LLM 把历史对话**压缩合并**成结构化的记忆（`MEMORY.md` + `HISTORY.md`），然后清空历史。这避免了无限增长的对话列表撑爆 context window。
- **Step 5（构建消息）**：`on_build_context` 是一个 pipeline callback，默认实现调用 `ContextBuilder.build_system_prompt()` —— 它会遍历所有注册的 `SectionProvider`（按 priority 排序），把它们的输出拼成一个 system prompt。这就是 Skills、Identity、运行时上下文（当前时间、channel 信息）被注入 prompt 的地方。
- **Step 6（ReAct 循环）**：这是 Agent 的核心引擎，封装在 `AgentLoop` 类中。它**只做一件事**：一个 `while` 循环，每次迭代调 LLM，如果返回 `tool_calls` 就并发执行工具并把结果塞回 messages，直到 LLM 返回纯文本或达到 `max_iterations`。

---

## 二、源码导读

### 2.1 `src/agent_harness/__init__.py` — 公共 API 表面

```python
# 文件顶部：16 行文档字符串，列出了所有公共导入路径
"""Agent Harness — reusable agent infrastructure base.

Usage:
    from agent_harness import AgentLoop, LoopCallbacks, TurnResult
    from agent_harness import BaseTool, ToolRegistry, ToolResult, ToolExecutionContext
    from agent_harness import LLMProvider, LLMResponse, ProviderSpec, detect_provider
    ...
"""

# 显式导入：所有"核心"依赖都在这里直接导入
from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from agent_harness.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from agent_harness.harness import Harness
from agent_harness.agent import Agent
# ... 约 40 个公有符号

# 惰性导入：需要可选 SDK（anthropic, openai）的 Provider 实现
def __getattr__(name: str):
    """Lazy-load provider implementations (optional SDKs: anthropic, openai)."""
    if name == "AnthropicProvider":
        from agent_harness.providers.anthropic_provider import AnthropicProvider as _cls
        return _cls
    if name == "OpenAICompatProvider":
        from agent_harness.providers.openai_compat_provider import OpenAICompatProvider as _cls
        return _cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**为什么这样设计？**

- **显式导入 vs 惰性导入的分界线**：所有"核心"类型（Harness、Agent、BaseTool、LLMProvider 等）都是直接导入的 —— 安装 `agent-harness` 时它们一定可用。`AnthropicProvider` 和 `OpenAICompatProvider` 则是惰性加载的，因为它们的导入会触发 `import anthropic` / `import openai`，这些是可选的 SDK 依赖。用户如果只用 OpenAI 兼容接口，就不需要安装 `anthropic` 包。

- **Python 3.7+ 的 `__getattr__` 技巧**：Python 3.7 引入了模块级别的 `__getattr__`，使得我们可以在**导入时**而不是**模块加载时**解析这些符号。效果是：
  ```python
  # 这行不会报 ImportError，即使 openai 没安装
  from agent_harness import OpenAICompatProvider  # 成功！
  # 但这行会报 ImportError
  OpenAICompatProvider(api_key="...")  # 如果 openai 没安装，这里才报错
  ```
  这让 `pip install llm-harness`（不带 extra）就可以导入所有 API 符号，只有实际实例化时才需要对应 SDK。

- **`__all__` 列表**：约 40 个符号的白名单。这不仅是为了 `from agent_harness import *`，更是为了 IDE 的类型提示和静态分析。

### 2.2 `src/agent_harness/harness.py` — Harness IoC 容器

```python
class Harness:
    """Infrastructure container that holds all agent parts."""

    def __init__(self, *, provider: LLMProvider, workspace: str | Path = ...,
                 tools: ToolRegistry | ToolsConfig | list[str] | None = None,
                 permissions: PermissionChecker | PermissionSettings | str | None = None,
                 memory: MemoryStore | str | Path | None = None,
                 sessions: SessionManager | str | Path | None = None,
                 context: ContextBuilder | list[SectionProvider] | None = None,
                 skills: SkillRegistry | list[str | Path] | None = None,
                 hooks: HookRegistry | str | Path | None = None,
                 tracker: str | Path | None = None,
                 ...):
        # 每种子系统都有一个 _resolve_xxx 方法处理简写
        self.tools = self._resolve_tools(tools)               # list[str] → 查 _TOOL_FACTORIES 字典
        self.permissions = self._resolve_permissions(permissions)  # "default" → PermissionMode.DEFAULT
        self.memory = self._resolve_memory(memory)             # str/Path → MemoryStore(路径)
        self.sessions = self._resolve_sessions(sessions)       # str/Path → SessionManager(路径)
        self.context = self._resolve_context(context)          # list[SectionProvider] → ContextBuilder
        self.skills = self._resolve_skills(skills)             # list[str|Path] → SkillRegistry
        self.hooks = self._resolve_hooks(hooks)                # str/Path → HookRegistry
        self.tracker = self._resolve_tracker(tracker)          # str/Path → Tracker
```

**简写解析的精髓**：看 `_resolve_tools` 方法：

```python
@staticmethod
def _resolve_tools(tools: ToolRegistry | ToolsConfig | list[str] | None) -> ToolRegistry:
    if tools is None:
        return ToolRegistry()               # 默认：空工具箱
    if isinstance(tools, ToolRegistry):
        return tools                         # 已经组装好，直接返回
    if isinstance(tools, list):
        return _list_to_tool_registry(tools)  # ["read_file", "exec"] → 查工厂字典创建实例
    if isinstance(tools, ToolsConfig):
        return build_tools_from_config(tools)  # 配置对象 → 用配置驱动构建器
    raise TypeError(...)
```

**为什么这样设计？**

这种模式叫 **shorthand resolution**（简写解析），在 Python 中常用来实现"配置优于代码"。Harness 的构造函数接受同一个参数的多种形式：

- `tools=None`：生产环境中还没想好用什么工具？暂时不配。
- `tools=["read_file", "exec"]`：快速原型，一行搞定。
- `tools=my_tool_registry`：精细控制，手动组装 ToolRegistry。
- `tools=config.tools`：配置驱动，从 JSON 加载 ToolsConfig。

同样，`_resolve_permissions` 也支持简写：

```python
mode_map = {
    "default": PermissionMode.DEFAULT,   # 执行敏感操作时询问用户
    "plan": PermissionMode.PLAN,          # 计划模式，先展示再执行
    "auto": PermissionMode.FULL_AUTO,     # 全自动，不询问
    "full_auto": PermissionMode.FULL_AUTO,
}
```

以 `permissions="default"` 代替 `PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))`，原型期少打 60 个字符。

**`from_config` 工厂**的完整链路：

```python
@classmethod
def from_config(cls, config: Config, *, extra_tools=None) -> Harness:
    provider = cls._provider_from_config(config)       # auto-detect provider
    tools = build_tools_from_config(config.tools, ...)  # 配置驱动工具构建
    permissions = PermissionChecker(PermissionSettings(
        mode=config.permission.mode,
        allowed_tools=config.permission.allowed_tools,
        denied_tools=config.permission.denied_tools,
    ))
    memory = MemoryStore(workspace / "memory")          # 约定优于配置
    sessions = SessionManager(workspace)                # workspace 下自动创建
    return cls(provider=provider, workspace=workspace, tools=tools, ...)
```

注意 `memory` 和 `sessions` 的默认路径：工作目录下的 `memory/` 子目录。这是**约定优于配置**（convention over configuration）—— 最常见的设置被编码为默认值，用户不需要显式指定。

### 2.3 `src/agent_harness/agent.py` — Agent.process() 管线

这是最值得细读的部分。我们从入口开始逐行分析：

```python
async def process(self, msg: InboundMessage) -> OutboundMessage | None:
    # ── Step 1：并发控制 ──
    lock = self._session_locks.setdefault(msg.session_key, asyncio.Lock())
    gate = self._concurrency_gate or nullcontext()
    async with lock, gate:
        try:
            # ── Step 2-3：会话管理 ──
            session = None
            history: list[dict[str, Any]] = []
            if self.harness.sessions is not None:
                session = self.harness.sessions.get_or_create(msg.session_key)
                # 关键：在 add_message 之前获取历史，避免重复
                history = session.get_history()
                session.add_message("user", msg.content)
                self.harness.sessions.save(session)

            # ── Step 4：记忆合并（可选） ──
            if self._consolidator is not None and session is not None:
                await self._consolidator.maybe_consolidate_by_tokens(session)

            # ── Step 5：构建消息 ──
            initial_messages = await self.harness.on_build_context(msg, history)

            # ── Step 6：ReAct 循环 ──
            result = await self._loop.run_react_loop(
                initial_messages, channel=msg.channel, chat_id=msg.chat_id,
            )

            # ── Step 7：持久化 ──
            if session is not None:
                self._save_turn(session, result, len(initial_messages))

            # ── Step 8：返回 ──
            if result.final_content is None:
                return None
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content=result.final_content,
            )
```

**三步注意的设计细节**：

1. **`history = session.get_history()` 的时机**：在 `session.add_message("user", msg.content)` **之前**拿到历史。这样 `on_build_context` 拿到的 history 就不包含当前消息，`context.build_messages()` 会在最后追加 `{"role": "user", "content": msg}`，保证消息顺序正确。这是一个很容易写 bug 的细节。

2. **`_save_turn` 中的 `initial_count` 参数**：
   ```python
   def _save_turn(self, session, result, initial_count):
       new_messages = result.messages[initial_count:]
       for msg in new_messages:
           # 只保存本轮 ReAct 循环产生的新消息（assistant + tool）
           ...
           # 截断过长的 tool 结果
           if role == "tool" and len(content) > _TOOL_RESULT_MAX_CHARS:
               content = content[:_TOOL_RESULT_MAX_CHARS]
   ```
   用 `result.messages[initial_count:]` 精确切分出"本轮新增的消息"，而不是"全部消息"。避免重复保存。

3. **`_build_loop` 中注入的回调**：
   ```python
   def _build_loop(self) -> AgentLoop:
       async def execute_tool(tool_name, args_dict):
           tool = harness.tools.get(tool_name)
           parsed = tool.input_model.model_validate(args_dict)  # Pydantic 验证
           permission = await harness.on_tool_check(tool_name, tool, parsed)
           if not permission.allowed:
               return f"Error: Permission denied: {permission.reason}"
           context = ToolExecutionContext(cwd=harness.workspace)
           result = await tool.execute(parsed, context)
           return result.output
   ```
   Agent 不直接知道工具怎么执行、权限怎么检查 —— 这些都通过 `LoopCallbacks` 注入。AgentLoop 的职责极其纯粹：**协调 LLM 和工具之间的对话循环**。

---

## 三、动手练习：Trace 一次 process() 调用

这个练习的目的是让你**亲手验证**上面学到的管线知识。你会写一个脚本，在 Agent.process() 的每个步骤插入日志，然后发送一条假消息，观察数据如何流经整个系统。

### 3.1 创建一个 tracing agent

在你的工作目录下创建 `trace_process.py`：

```python
"""
Trace Agent.process() pipeline — 验证各步骤正确触发。

用法：
    python trace_process.py

预期输出（按顺序看到 8 个 TRACE 日志）：
    [TRACE] Step 1: Acquired lock for session=cli:c1
    [TRACE] Step 2-3: Session loaded, history has N messages
    [TRACE] Step 4: Memory consolidation check done
    [TRACE] Step 5: Context built, system_prompt=X chars, messages=Y
    [TRACE] Step 6: ReAct loop started, initial_messages=Y
    [TRACE] Step 6: ReAct loop completed, tools_used=[], final_content=...
    [TRACE] Step 7: Turn saved, N new messages persisted
    [TRACE] Step 8: Returning OutboundMessage(content=...)
"""

import asyncio
import logging
import sys
from pathlib import Path

# 配置日志：只输出我们的 TRACE 行，屏蔽库日志
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    stream=sys.stdout,
)
trace_log = logging.getLogger("trace")
trace_log.setLevel(logging.INFO)


def main():
    """创建 Harness + Agent + trace 脚本的入口。"""
    # 1. 创建 Mock Provider（不调真实 LLM，返回固定回复）
    from agent_harness.providers.base import LLMProvider, LLMResponse

    class MockProvider(LLMProvider):
        """模拟 LLM：收到任何消息都返回一句固定文本。"""

        async def chat(self, messages, tools, model, **kwargs):
            return LLMResponse(content="Hello from mock LLM!")

        async def chat_stream(self, messages, tools, model,
                              on_content_delta, **kwargs):
            on_content_delta("Hello from mock LLM!")
            return LLMResponse(content="Hello from mock LLM!")

        def get_default_model(self):
            return "mock-model"

    # 2. 创建 Harness（使用 mock provider）
    from agent_harness import Harness
    from agent_harness.bus.events import InboundMessage

    harness = Harness(
        provider=MockProvider(),
        tools=["read_file", "echo"],  # echo 不存在，验证 "Unknown tool" 逻辑
        permissions="auto",            # 全自动权限，不询问
        workspace=Path.cwd() / ".trace-workspace",
    )

    # 3. 创建 Agent（覆盖 _build_loop 和 process 以注入跟踪）
    from agent_harness import Agent

    # ── 核心技巧：通过 monkey-patch Agent 类来注入 TRACE 日志 ──
    # 我们不修改源码，而是在创建 Agent 实例后替换其 process 方法
    # 在原始 process 的每个步骤前后插入日志

    original_process = Agent.process

    async def traced_process(self, msg):
        """包装原始 process，在每个步骤插入 TRACE 日志。"""
        # Step 1
        trace_log.info("[TRACE] Step 1: Acquired lock for session=%s",
                       msg.session_key)

        # 获取 session（如果存在）
        from agent_harness.session.manager import Session
        session = None
        history = []
        if self.harness.sessions is not None:
            session = self.harness.sessions.get_or_create(msg.session_key)
            history = session.get_history()
            trace_log.info(
                "[TRACE] Step 2-3: Session loaded, history has %d messages",
                len(history),
            )

        # Step 4
        if self._consolidator is not None and session is not None:
            trace_log.info("[TRACE] Step 4: Memory consolidation check ...")
            await self._consolidator.maybe_consolidate_by_tokens(session)
            trace_log.info("[TRACE] Step 4: Memory consolidation check done")

        # Step 5
        initial_messages = await self.harness.on_build_context(msg, history)
        system_prompt = initial_messages[0]["content"] if initial_messages else ""
        trace_log.info(
            "[TRACE] Step 5: Context built, system_prompt=%d chars, messages=%d",
            len(system_prompt),
            len(initial_messages),
        )

        # Step 6
        trace_log.info(
            "[TRACE] Step 6: ReAct loop started, initial_messages=%d",
            len(initial_messages),
        )
        result = await self._loop.run_react_loop(
            initial_messages,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )
        trace_log.info(
            "[TRACE] Step 6: ReAct loop completed, tools_used=%s, "
            "final_content=%r",
            result.tools_used,
            (result.final_content or "")[:80],
        )

        # Step 7
        if session is not None:
            self._save_turn(session, result, len(initial_messages))
            trace_log.info(
                "[TRACE] Step 7: Turn saved, %d new messages persisted",
                len(result.messages) - len(initial_messages),
            )

        # Step 8
        if result.final_content is None:
            trace_log.info("[TRACE] Step 8: No content, returning None")
            return None

        out = InboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=result.final_content,
        )
        trace_log.info(
            "[TRACE] Step 8: Returning message, content=%r",
            out.content[:80],
        )
        return out

    # 应用 monkey-patch
    Agent.process = traced_process

    # 4. 创建 Agent 实例并发送测试消息
    agent = Agent(harness)
    trace_log.info("=" * 60)
    trace_log.info("Agent created. Sending test message...")
    trace_log.info("=" * 60)

    msg = InboundMessage(
        channel="cli",
        sender_id="tester",
        chat_id="c1",
        content="Hello, agent! What tools do you have?",
    )

    result = asyncio.run(agent.process(msg))

    trace_log.info("=" * 60)
    trace_log.info("Done! Final result: %r", result)
    trace_log.info("=" * 60)

    # 5. 清理临时工作区
    import shutil
    workspace_path = Path.cwd() / ".trace-workspace"
    if workspace_path.exists():
        shutil.rmtree(workspace_path)


if __name__ == "__main__":
    main()
```

### 3.2 运行并观察输出

```bash
cd /path/to/agent-harness
python trace_process.py
```

你应该看到类似这样的输出：

```
============================================================
Agent created. Sending test message...
============================================================
[TRACE] Step 1: Acquired lock for session=cli:c1
[TRACE] Step 2-3: Session loaded, history has 0 messages
[TRACE] Step 4: Memory consolidation check done
[TRACE] Step 5: Context built, system_prompt=0 chars, messages=2
[TRACE] Step 6: ReAct loop started, initial_messages=2
[TRACE] Step 6: ReAct loop completed, tools_used=[], final_content='Hello from mock LLM!'
[TRACE] Step 7: Turn saved, 1 new messages persisted
[TRACE] Step 8: Returning message, content='Hello from mock LLM!'
============================================================
Done! Final result: content='Hello from mock LLM!'
============================================================
```

### 3.3 验证你的理解

1. **Step 2-3 为什么 history 是 0 条消息？** 因为这是我们第一次发送消息，session 刚被创建。再发一条，history 就会包含上一条的 assistant 回复。

2. **Step 5 的 system_prompt 为什么是 0 chars？** 因为我们没有添加任何 SectionProvider。试试创建 Harness 时加上 `context=[IdentitySection("你是测试助手。")]`，看看 system_prompt 长度是否变化。

3. **Step 6 的 tools_used 为什么是空的？** 因为 MockProvider 总是返回纯文本，从不返回 tool_calls。如果 MockProvider 改成返回 tool_calls，你会看到 tools_used 被填充。

4. **试试把 `permissions` 从 `"auto"` 改成 `"default"`**，然后让 MockProvider 返回一个工具调用，观察 `on_tool_check` 是否会阻止执行。

### 3.4 进阶：验证管线中的权限检查

创建一个工具调用的 MockProvider 并观察权限检查过程：

```python
class ToolCallingMockProvider(LLMProvider):
    """模拟 LLM 返回工具调用。"""

    async def chat(self, messages, tools, model, **kwargs):
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="read_file",
                    arguments={"path": "/etc/passwd"},
                )
            ],
        )

    async def chat_stream(self, messages, tools, model,
                          on_content_delta, **kwargs):
        return await self.chat(messages, tools, model, **kwargs)

    def get_default_model(self):
        return "mock-model"
```

替换 `MockProvider` 为 `ToolCallingMockProvider`，你会看到：

- Step 6 中 `tools_used=['read_file']`
- 如果 permissions 是 "default"，需要在终端确认
- 如果 permissions 是 "auto"，工具会直接执行（但在 mock 中仍然返回 mock 结果）

---

## 本节小结

| 概念 | 核心要点 |
|------|---------|
| **Harness** | 基础设施 IoC 容器，管理所有子系统（工具、权限、记忆、会话...），支持简写解析 |
| **Agent** | 可运行实例，组合 Harness + model，提供唯一的 `process(msg)` 入口 |
| **AgentLoop** | 纯粹的 ReAct 循环骨架，通过 `LoopCallbacks` 注入所有业务行为 |
| **process 管线** | Lock → Session → Memory → Context → AgentLoop → Persist → OutboundMessage |
| **设计哲学** | 回调注入非继承；配置驱动；传输无关；~13,000 行，放心 Fork |

**Day 1 的目标**是建立对整个项目的全局认知。从 Day 2 开始，我们会逐个深入每个子系统：

- Day 2：LLM Provider 抽象层 — 为什么需要 ProviderSpec？retry + backoff 怎么实现的？
- Day 3：Tool 系统 — BaseTool 的 input_model/output_model 设计，ToolRegistry 的注册机制
- Day 4：Context Builder — SectionProvider 的插件式设计，system prompt 的组装过程
- Day 5：Session + Memory — JSONL 持久化，双文件记忆合并策略
- Day 6：Permission + Hook — 三种权限模式，PreToolUse/PostToolUse 钩子系统
- Day 7：Config + Observability — 多层配置覆盖，17 种事件追踪
