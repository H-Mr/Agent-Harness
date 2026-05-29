# 7 天掌握路线

通过结构化、动手实战的方式学习 llm-harness 框架。到第 7 天，你将亲手编写一个自定义后端适配器、部署多服务栈，并理解框架的每一个层次。

---

## 第 1 天：安装与第一个 Agent（3 小时）

### 理论（45 分钟）

**框架定位。** llm-harness 不是 LangChain 封装，不是 Dify 替代品，也不是 AutoGPT 克隆。它是一个纯异步、无状态、依赖注入驱动的 Agent 引擎内核。下表突出显示了关键差异：

| 维度 | llm-harness | LangChain | AutoGPT |
|---|---|---|---|
| 架构 | DI 容器 + Protocols | 回调链 | 单体循环 |
| 状态模型 | 无状态引擎；调用方持有 Session | 链携带状态 | 全局状态 |
| 异步 | 全程纯异步 | 同步/异步混合 | 同步 |
| 工具系统 | 类型化、Pydantic 校验 | 基于字符串 | 临时方案 |
| 扩展模型 | Protocols（结构子类型） | 抽象基类 | 插件系统 |
| 沙箱 | SRT（内核级）+ 业务层 | 无内置 | 无 |

**三层模型。** 每个 llm-harness Agent 由三个层次构成，每层有精确的职责边界：

1. **Harness**（组装器）—— 通过构造函数注入接收所有依赖（provider、工具、沙箱、内存、权限、技能、可观测性）。它编排回调、构建 consolidator，并返回一个可直接使用的 Agent。Harness 执行**零 I/O**：不触及文件系统、不读取环境变量、不进行网络调用。其 `create_agent()` 方法负责组合下层组件。

2. **Agent**（纯无状态引擎）—— 内部没有可变状态。每次 `process()` 调用是自包含的：它接收一个 Session、一条消息和一个工作区路径，返回一个 TurnResult。调用方负责管理会话持久化、并发和工作区生命周期。Agent 调用 `session.get_history()`、调用 consolidator、委托给 AgentLoop，并将本轮结果保存回 Session。

3. **AgentLoop**（ReAct 骨架）—— 驱动工具调用决策的循环。设置 `max_iterations=40`，它向 LLM 发送消息 + 工具架构，解析工具调用，通过 ToolRegistry 执行工具，追加结果，重复执行直到 LLM 返回最终文本响应或达到迭代上限。行为通过回调注入（`on_build_context`、`on_tool_check`、`on_error`、`on_event`）。

**单轮数据流：**

```
InboundMessage
  --> Agent.process()
    --> session.get_history()                   # 加载对话历史
    --> session.add_message("user", content)     # 追加用户消息
    --> consolidator.maybe_consolidate()         # 超出预算时归档旧消息
    --> AgentLoop.run()
      --> on_build_context(msg, history)         # 构建系统提示 + 历史 + 用户消息
      --> provider.chat_with_retry(messages, tools, model)
      --> [tool_calls?]                          # LLM 决定调用工具
        --> _execute_tool_call()
          --> tool_registry.get(name)
          --> pydantic_model(**args)
          --> permission_checker.evaluate()
          --> ToolExecutionContext(cwd, metadata)
          --> await tool.execute(parsed_args, ctx)
          --> 将结果截断至 16_000 字符
        --> 将结果追加到消息列表
        --> 循环回到 chat_with_retry
      --> [no tool_calls]                        # LLM 生成最终文本
    --> _save_turn(session, result)              # 持久化 assistant + tool 消息
    --> return TurnResult
```

### 动手实践（2 小时）

#### 练习 1：安装并验证

```bash
pip install llm-harness[openai]
```

然后验证导入是否正常：

```python
# verify_import.py
from llm_harness.core.harness import Harness
from llm_harness.core.agent import Agent
from llm_harness.core.loop import AgentLoop, TurnResult
print("All core imports OK -- framework installed")
```

运行：

```bash
python verify_import.py
# --> All core imports OK -- framework installed
```

#### 练习 2：直接创建 Provider + AgentLoop（不使用 Harness）

这个练习检验你在 Harness 抽象隐藏底层之前对原始层的理解：

```python
# raw_loop.py
import os
import asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.loop import AgentLoop

async def main():
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    tools = ToolRegistry()

    loop = AgentLoop(
        provider=provider,
        tools=tools,
        model="deepseek-chat",
        on_build_context=lambda msg, history: [
            {"role": "system", "content": "You are a helpful assistant."},
            *history,
            {"role": "user", "content": msg.content},
        ],
        on_tool_check=lambda name, tool, args: type("OK", (), {"allowed": True})(),
        on_error=lambda exc, ctx: print(f"Error in {ctx}: {exc}"),
    )

    result = await loop.run(
        type("Msg", (), {"content": "What is the capital of France?"})(),
        [],
        cwd=Path("."),
    )
    print("Reply:", result.final_content)

asyncio.run(main())
```

#### 练习 3：使用 Harness 进行组装并对比

```python
# with_harness.py
import os
import asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./workspace")
    ws.mkdir(exist_ok=True)

    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "web_search"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    # Harness 添加了权限回调、系统提示组装、技能列表、子 Agent 定义和错误处理。
    harness = Harness(
        provider=provider,
        model="deepseek-chat",
        tools=tools,
        sandbox=sandbox,
        system_prompt="You are a concise assistant.",
    )
    agent = harness.create_agent()
    session = Session(key="demo:chat1")

    msg = InboundMessage("cli", "alice", "c1", "Write 'hello.txt' with content 'Hello world'")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)
    print("Tools used:", result.tools_used)
    print("Session messages:", len(session.messages))
    print("hello.txt content:", (ws / "hello.txt").read_text())

asyncio.run(main())
```

#### 练习 4：使用错误的 API 密钥进行调试

```python
# debug_wrong_key.py
import asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./workspace")
    ws.mkdir(exist_ok=True)

    # 故意使用错误密钥 —— 观察重试行为
    provider = OpenAICompatProvider(
        api_key="sk-invalid-key-for-testing",
        api_base="https://api.deepseek.com",
    )
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox)
    agent = harness.create_agent()
    session = Session(key="debug:chat1")
    msg = InboundMessage("cli", "user", "c1", "Hello")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Result:", result.final_content)

asyncio.run(main())
```

观察：`chat_with_retry` 方法会记录每次临时错误尝试，应用 1s/2s/4s 退避策略，最终报告一个非临时错误。

### 交付物（15 分钟）

- `hello_agent.py` —— 由环境变量驱动，组装 Harness + Agent，发送一条消息，打印回复和会话消息数量。
- 验证：`LLM_HARNESS_API_KEY=sk-xxx python hello_agent.py` —— 输出连贯的回复。

### 课后反思

为什么 Harness 刻意避免在构造过程中执行任何 I/O？在生产级 SaaS 应用中，急切初始化会引发哪些问题？

---

## 第 2 天：工具系统（3.5 小时）

### 理论（45 分钟）

工具系统由五个协同工作的组件组成：

**1. BaseTool（抽象基类）。** 每个工具继承 `BaseTool` 并声明三个 `ClassVar` 字段：

- `name: ClassVar[str]` —— LLM 函数调用使用的唯一标识符
- `description: ClassVar[str]` —— 在 LLM 决定调用哪个工具时向其展示的描述
- `input_model: ClassVar[type[BaseModel]]` —— 在工具运行前校验参数的 Pydantic 模型

每个工具实现 `async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult`。

**2. ToolRegistry（名称到实例的映射）。** 一个简单的基于字典的注册表。提供 `register(tool)`、`get(name)`、`unregister(name)`。`to_api_schema(api_format)` 方法返回 provider 所需格式的架构：

- `to_api_schema("openai")` 返回 `[{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]`
- `to_api_schema("anthropic")` 返回 `[{"name": ..., "description": ..., "input_schema": ...}]`

**3. ToolExecutionContext。** 一个包含 `cwd: Path` 和 `metadata: dict` 的数据类。传递给每个工具执行。metadata 携带会话上下文，如 `session_key`、`account` 和 `channel`。

**4. ToolResult。** 一个冻结数据类：`output: str`、`is_error: bool = False`、`metadata: dict`。标准化返回 —— 循环检查 `is_error` 以决定展示结果还是失败消息。

**5. ToolFactory。** 一个构建器注册表，提供 `register(name, builder_fn)` API。使用 `importlib.import_module` 实现延迟加载（工具模块仅在构建时才被导入）。工厂注入后端依赖：沙箱工具获得 `SandboxBackend`，内存工具获得 `MemoryBackend`，集群工具获得 `AgentBackend`。

**`_execute_tool_call` 内部工具调用的完整执行轨迹：**

```python
tool = tools.get(tc.name)                    # 1. 查找
parsed = tool.input_model(**tc.arguments)     # 2. Pydantic 解析 + 校验
decision = permission_checker.evaluate(...)   # 3. 权限检查（如果已配置）
ctx = ToolExecutionContext(cwd=cwd, metadata={...})
result = await tool.execute(parsed, ctx)      # 4. 执行
truncated = result.output[:16_000]            # 5. 截断
```

**内置工具（共 15 个）：**

| 工具 | 后端依赖 | 只读？ |
|---|---|---|
| `read_file` | SandboxBackend | 是 |
| `write_file` | SandboxBackend | 否 |
| `edit_file` | SandboxBackend | 否 |
| `exec` | SandboxBackend | 否 |
| `glob` | SandboxBackend | 是 |
| `grep` | SandboxBackend | 是 |
| `web_search` | 无 | 是 |
| `web_fetch` | 无 | 是 |
| `memory_read` | MemoryBackend | 是 |
| `memory_write` | MemoryBackend | 否 |
| `agent` | AgentBackend | 否 |
| `send_message` | AgentBackend | 否 |
| `task_stop` | AgentBackend | 否 |
| `skill` | SkillRegistry | 是 |
| `ask_user_question` | 无 | 是 |

### 动手实践（2.5 小时）

#### 练习 1：针对本地沙箱注册 read_file + write_file

```python
# ex1_file_ops.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./ws_files")
    ws.mkdir(exist_ok=True)
    (ws / "hello.md").write_text("# Hello\n\nThis is a test file.", encoding="utf-8")

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      system_prompt="Use tools to read and write files.")
    agent = harness.create_agent()
    session = Session(key="ex1:chat1")

    msg = InboundMessage("cli", "user", "c1", "Read hello.md, then create a file called summary.md with a 1-line summary.")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)
    print("Tools used:", result.tools_used)
    print("summary.md exists:", (ws / "summary.md").exists())

asyncio.run(main())
```

#### 练习 2：注册 glob + grep

```python
# ex2_glob_grep.py
# 设置同练习 1，在工具列表中添加 "glob" 和 "grep"。
# 提示："Find all .md files, then search for the word 'test' in them."
```

在工厂循环的工具名称列表中添加 `"glob"` 和 `"grep"`。

#### 练习 3：注册 exec

```python
# ex3_exec.py
# 设置同前，在工具列表中添加 "exec"。
# 提示："Run 'git status' and tell me the current branch."
```

#### 练习 4：注册 web_search + web_fetch

```python
# ex4_web.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./ws_web")
    ws.mkdir(exist_ok=True)
    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["web_search", "web_fetch"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      system_prompt="Use web_search then web_fetch to research.")
    agent = harness.create_agent()
    session = Session(key="ex4:chat1")

    msg = InboundMessage("cli", "user", "c1",
        "Search for 'Python 3.13 release date' and fetch the official Python blog result.")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)

asyncio.run(main())
```

#### 练习 5：注册 ask_user_question

```python
# ex5_ask_user.py
# 设置同前，在工具列表中添加 "ask_user_question"。
# 提示："I need to write a Python script. Ask me what it should do."
# 观察 LLM 调用 ask_user_question 工具来请求澄清。
```

#### 练习 6（调试）：通过 on_tool_check 回调观察工具调用

```python
# ex6_tool_logging.py
# 添加自定义 on_tool_check 回调，打印每次工具调用：
#
# harness = Harness(
#     ...
#     permissions=PermissionChecker(PermissionSettings(
#         # 不加限制 —— 仅观察
#     )),
# )
# 然后通过 monkey-patch 或扩展；更简洁的方式是使用 on_event：
# AgentLoop 接受一个 on_event 回调，触发 "tool:executing" 事件。
```

最简单的方法是使用带有 `on_event` 的自定义 `AgentLoop`：

```python
async def event_cb(event_type, payload):
    if event_type == "tool:executing":
        print(f"[TOOL] {payload['name']} args={payload.get('arguments', {})}")

loop = AgentLoop(
    ...
    on_event=event_cb,
)
```

#### 练习 7（错误处理）：无效的工具参数

```python
# ex7_tool_error.py
# 提示 agent："Read file that-does-not-exist.txt"
# 观察 ToolResult 中报告的 Pydantic 校验错误或工具自身的错误。
```

### 交付物（15 分钟）

- `tool_lab.py` —— 注册 8 个以上工具（read_file、write_file、glob、grep、exec、web_search、web_fetch、ask_user_question），发送一个需要链式调用至少 3 个工具的综合性多步骤任务。
- 验证：`LLM_HARNESS_API_KEY=sk-xxx python tool_lab.py` —— 链式调用 3 个以上工具，最终输出可见。

### 课后反思

为什么 ToolFactory 使用延迟的 importlib 加载，而不是在启动时急于导入所有工具模块？这种设计在哪些场景下有助于解决问题？

---

## 第 3 天：会话与内存（3.5 小时）

### 理论（1 小时）

**Session 数据类** —— 纯结构，无 I/O：

```python
@dataclass
class Session:
    key: str                                    # "channel:chat_id"
    messages: list[dict] = field(default_factory=list)
    created_at: datetime = field(...)
    updated_at: datetime = field(...)
    metadata: dict = field(default_factory=dict)
    last_consolidated: int = 0                  # 消息列表中的偏移量
```

关键方法：

- `add_message(role, content, **kwargs)` —— 追加一条带有自动生成 ISO 时间戳的消息字典。
- `get_history(max_messages=500)` —— 核心切片逻辑：
  1. 从 `last_consolidated` 开始（跳过已归档消息）
  2. 从该窗口中取最后 `max_messages` 条条目
  3. 向前搜索到第一个 `"user"` 角色的消息（对齐截断点）
  4. 仅提取 `role`、`content`、`tool_calls`、`tool_call_id`、`name` 键
- `remove_before(idx)` —— 从内存列表中移除 `idx` 之前的消息，并调整 `last_consolidated`。

**MemoryConsolidator** 在接近上下文窗口预算时协调旧消息的归档：

1. `estimate_session_prompt_tokens(session)` —— 构建探测上下文（系统提示 + 工具 + 历史），通过 `len(content) // 4` 估算 token 数量。
2. `pick_consolidation_boundary(session, tokens_to_remove)` —— 从 `last_consolidated` 开始向前扫描消息，累加 token 计数，返回在满足预算之前的最后一个 `"user"` 消息的索引。
3. `maybe_consolidate(session)` —— 获取每个会话的 `asyncio.Lock`（超时 30 秒），最多运行 `MAX_CONSOLIDATION_ROUNDS=5` 轮。每轮由策略决定是否归档，调用 `backend.consolidate()`，然后 `session.remove_before()`。

**TokenBudgetPolicy（默认策略）：**

```
budget = context_window_tokens - max_completion_tokens - safety_buffer(1024)
if estimated < budget: return None  # 无需归档
boundary = pick_consolidation_boundary(session, (estimated - budget) // 2)
```

**MessageCountPolicy** 是另一种策略：当活跃消息数超过 `max_messages` 时触发归档。

**MemoryBackend Protocol（5 个方法）：**

```python
class MemoryBackend(Protocol):
    async def get_context(self, namespace: str) -> str: ...
    async def read_section(self, namespace: str, section: str) -> str: ...
    async def append_section(self, namespace: str, section: str, entry: str) -> None: ...
    async def add_history(self, namespace: str, entry: str) -> None: ...
    async def consolidate(self, namespace, messages, provider=None, model="") -> bool: ...
```

### 动手实践（2 小时）

#### 练习 1：观察多轮对话中消息的增长

```python
# ex1_session_growth.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./ws_session")
    ws.mkdir(exist_ok=True)
    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["write_file", "read_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox)
    agent = harness.create_agent()
    session = Session(key="growth:chat1")

    prompts = [
        "Create a file called log.txt with content 'step 1'",
        "Append 'step 2' to log.txt",
        "Append 'step 3' to log.txt",
        "Append 'step 4' to log.txt",
        "Read log.txt and tell me all steps",
    ]
    for i, prompt in enumerate(prompts):
        msg = InboundMessage("cli", "user", "c1", prompt)
        result = await agent.process(msg, session=session, cwd=ws)
        print(f"Turn {i+1}: final_content={result.final_content[:60] if result.final_content else '(tool)'}  "
              f"messages={len(session.messages)}  "
              f"tools_used={result.tools_used}")

asyncio.run(main())
```

#### 练习 2：打印 get_history() 并验证向前搜索行为

```python
# ex2_history.py
from llm_harness.core.session.session import Session

session = Session(key="test:demo")
session.add_message("system", "You are a bot")
session.add_message("user", "Hello")
session.add_message("assistant", "Hi there")
session.add_message("user", "How are you?")
session.add_message("assistant", "I'm great!")
session.add_message("tool", "some_result", tool_call_id="call_1", name="read_file")

print("Full history:")
for m in session.get_history(max_messages=500):
    print(f"  {m['role']}: {str(m.get('content', ''))[:60]}")

# 验证："system" 消息不会出现在 get_history() 输出中
# 因为 get_history() 从 last_consolidated (0) 开始，
# 但会向前搜索到第一个 "user" 角色的消息。
print("\nNotice: system message is excluded by the forward-search to first 'user'.")
```

#### 练习 3：手动 remove_before

```python
# ex3_remove_before.py
from llm_harness.core.session.session import Session

s = Session(key="test:demo")
s.add_message("user", "msg1")
s.add_message("assistant", "resp1")
s.add_message("user", "msg2")
s.add_message("assistant", "resp2")
s.add_message("user", "msg3")

print(f"Before remove: {len(s.messages)} messages, last_consolidated={s.last_consolidated}")

# 移除前 3 条消息
s.remove_before(3)
print(f"After remove:  {len(s.messages)} messages, last_consolidated={s.last_consolidated}")

history = s.get_history()
print(f"History contains {len(history)} messages")
for m in history:
    print(f"  {m['role']}: {m.get('content', '')}")
```

#### 练习 4：使用 mock 后端进行内存归档

```python
# ex4_consolidation.py
import asyncio
from unittest.mock import AsyncMock
from llm_harness.core.session.session import Session
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.memory.policy import TokenBudgetPolicy

async def main():
    backend = AsyncMock()
    backend.consolidate = AsyncMock(return_value=True)

    consolidator = MemoryConsolidator(
        backend=backend,
        context_window_tokens=128_000,
        max_completion_tokens=4096,
        build_messages=lambda **kw: [
            {"role": "system", "content": "test system"},
            {"role": "user", "content": kw.get("current_message", "")},
        ],
        get_tool_definitions=lambda: [],
        policy=TokenBudgetPolicy(
            context_window_tokens=128_000,
            max_completion_tokens=4096,
        ),
    )

    session = Session(key="consolidation:test")
    # 添加大量消息以触发归档
    for i in range(20):
        session.add_message("user", "hello " * 100)   # 每条约 250 tokens
        session.add_message("assistant", "world " * 100)

    print(f"Messages before: {len(session.messages)}")
    print(f"last_consolidated before: {session.last_consolidated}")

    await consolidator.maybe_consolidate(session)

    print(f"Messages after:  {len(session.messages)}")
    print(f"last_consolidated after: {session.last_consolidated}")
    print(f"Backend.consolidate called: {backend.consolidate.called}")

asyncio.run(main())
```

#### 练习 5：估算消息 token 数

```python
# ex5_token_estimate.py
from llm_harness.adapters.memory.consolidator import estimate_message_tokens

messages = [
    {"role": "user", "content": "Hello, how are you?"},            # ~5 tokens
    {"role": "assistant", "content": "I'm doing well, thank you!"}, # ~7 tokens
    {"role": "user", "content": "What is the meaning of life?" * 10},  # ~90 tokens
]

for m in messages:
    tokens = estimate_message_tokens(m)
    print(f"[{m['role']}] ~{tokens} tokens  content_len={len(m['content'])}")
```

### 交付物（15 分钟）

- `session_lab.py` —— 一个 10 轮模拟程序，每轮打印：轮次数、session.messages 数量、token 估算值、是否触发了归档。
- 验证：`python session_lab.py` —— 显示 token 数增长以及归档触发点（根据消息长度，大约在第 8 轮或更早）。

### 课后反思

`get_history()` 向前搜索到第一条 `"user"` 消息，意味着系统消息被排除在历史记录之外。这种设计的 rationale 是什么？在什么情况下会导致问题？

---

## 第 4 天：Providers 与配置（3.5 小时）

### 理论（1 小时）

**LLMProvider 抽象基类。** 抽象基类定义了：

- `chat()` —— 每个 provider 必须实现的抽象方法
- `chat_with_retry()` —— 模板方法，封装 `chat()` 并带有指数退避（1s、2s、4s）、临时错误检测和图片回退机制

`_TRANSIENT_ERROR_MARKERS` 元组包含 14 个用于识别可重试错误的关键词模式：

```python
_TRANSIENT_ERROR_MARKERS = (
    "429", "rate limit", "rate_limit", "too many requests",
    "503", "502", "500", "504", "service unavailable",
    "overloaded", "internal server error", "bad gateway",
    "timeout", "temporarily",
)
```

如果发生非临时错误且请求包含 `image_url` 内容块，provider 会移除图片并重试一次（图片回退路径）。

`_SENTINEL` 哨兵值模式在整个框架中用于区分"未提供"和 `None`：

```python
_SENTINEL = object()
```

**消息清理管道**在每次请求上运行：

1. `_sanitize_empty_content()` —— 将空字符串替换为 `"(empty)"`（或对带有 tool_calls 的 assistant 消息替换为 `None`），移除空内容块，将 dict 类型的内容转换为列表。
2. `_sanitize_request_messages(messages, allowed_keys)` —— 将每条消息字典过滤为只包含 provider 支持的键（例如，Anthropic 使用的键与 OpenAI 不同）。
3. `_apply_cache_control()` —— 在系统消息、最后一条非最终用户消息和最后一个工具结果上添加 Anthropic `cache_control` 标记。

**AnthropicProvider 与 OpenAICompatProvider 对比：**

| 方面 | AnthropicProvider | OpenAICompatProvider |
|---|---|---|
| SDK | `anthropic` | `openai` |
| 消息格式 | 将 OpenAI 聊天格式转换为 Anthropic Messages API | 原生 OpenAI 格式 |
| 系统消息 | 从消息列表中提取，作为 `system` 参数发送 | 在消息中保留为 `role: "system"` |
| 工具格式 | `{"name": ..., "input_schema": ...}` | `{"type": "function", "function": {...}}` |
| 提示缓存 | 通过 `cache_control` 标记支持 | 不支持 |
| 思考模式 | 支持（含预算映射） | 不支持 |
| API 格式字符串 | `"anthropic"` | `"openai"` |

**ProviderSpec 注册表**包含 29 个 provider 定义。`detect_provider()` 函数使用三步匹配流程：

1. 通过 API 密钥前缀匹配（例如 `sk-or-` 对应 OpenRouter）
2. 通过基础 URL 关键词匹配（例如 URL 中包含 `openrouter`）
3. 通过模型名称关键词匹配（例如模型名中包含 `gpt`）

```python
def detect_provider(model, api_key=None, api_base=None) -> ProviderSpec | None:
    # 1. API 密钥前缀
    # 2. 基础 URL 关键词
    # 3. 模型名称关键词
```

**配置加载链**（CLI 参数 > 环境变量 > YAML > 默认值）：

```
CLI 参数（--model, --provider）
  > LLM_HARNESS_MODEL, LLM_HARNESS_API_KEY 环境变量
    > harness.yaml（YAML 文件）
      > Pydantic 默认值（Config()）
```

`Config` Pydantic 模型包含以下部分：`agent`、`tools`、`permission`、`sandbox`、`memory`、`observability`、`channels`、`workspace`。

```yaml
# harness.yaml
agent:
  model: deepseek-chat
  provider: auto
  api_key: ""           # 优先使用环境变量 LLM_HARNESS_API_KEY
  api_base: https://api.deepseek.com
  max_tokens: 4096
  context_window_tokens: 64000
tools:
  enabled:
    - read_file
    - write_file
    - web_search
    - web_fetch
permission:
  mode: full_auto      # default | plan | full_auto
sandbox:
  backend: srt
workspace: .
```

### 动手实践（2 小时）

#### 练习 1：创建完整配置的 harness.yaml

创建 `harness.yaml`：

```yaml
agent:
  model: deepseek-chat
  provider: auto
  api_base: https://api.deepseek.com
  max_tokens: 4096
  context_window_tokens: 64000
tools:
  enabled:
    - read_file
    - write_file
    - exec
    - glob
    - grep
    - web_search
    - web_fetch
permission:
  mode: full_auto
sandbox:
  backend: srt
workspace: .
```

#### 练习 2：使用 CLI 覆盖加载配置

```python
# ex2_load_config.py
from llm_harness.config.loader import load_config

cfg = load_config(model="claude-sonnet-4-6")
print(f"Model: {cfg.agent.model}")
print(f"Provider: {cfg.agent.provider}")
print(f"Workspace: {cfg.workspace}")
print(f"Tools enabled: {cfg.tools.enabled}")
print(f"Permission mode: {cfg.permission.mode}")
```

运行：

```bash
python ex2_load_config.py
# --> Model: claude-sonnet-4-6
# --> Provider: auto
```

#### 练习 3：对比 Anthropic 和 OpenAI provider

```python
# ex3_compare_providers.py
import os, asyncio
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.providers.anthropic_provider import AnthropicProvider

async def main():
    messages = [
        {"role": "user", "content": "What is 2+2? Answer in one word."}
    ]

    # OpenAI 兼容（DeepSeek）
    oai = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    resp = await oai.chat_with_retry(messages, model="deepseek-chat")
    print(f"OpenAICompat: {resp.content}  finish={resp.finish_reason}")

    # Anthropic（Claude）
    anth = AnthropicProvider(
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
    resp2 = await anth.chat_with_retry(messages, model="claude-sonnet-4-20250514")
    print(f"Anthropic:    {resp2.content}  finish={resp2.finish_reason}")

asyncio.run(main())
```

#### 练习 4：模拟临时错误并观察重试

```python
# ex4_retry.py
import os, asyncio
from unittest.mock import AsyncMock, patch
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider

async def main():
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )

    # 将 _safe_chat 临时替换为先失败两次（临时错误），再成功
    original = provider._safe_chat
    call_count = 0

    async def flaky_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            from llm_harness.adapters.providers.base import LLMResponse
            return LLMResponse(
                content="", finish_reason="error",
                error="429 Too Many Requests",
            )
        return await original(*args, **kwargs)

    with patch.object(provider, "_safe_chat", flaky_chat):
        resp = await provider.chat_with_retry(
            [{"role": "user", "content": "Hello"}],
            model="deepseek-chat",
        )
        print(f"Attempts needed: {call_count}")
        print(f"Final response: {resp.content}")

asyncio.run(main())
```

#### 练习 5：测试 detect_provider

```python
# ex5_detect.py
from llm_harness.adapters.providers.registry import detect_provider

tests = [
    ("gpt-4", "sk-...", ""),                          # OpenAI
    ("claude-sonnet-4-6", "", ""),                    # Anthropic
    ("deepseek-chat", "", ""),                        # DeepSeek
    ("gemini-pro", "", ""),                           # Google
    ("qwen-max", "", ""),                             # Qwen（DashScope）
    ("", "sk-or-v1-abc", ""),                         # OpenRouter（密钥前缀）
    ("", "", "https://openrouter.ai/api/v1"),         # OpenRouter（基础 URL）
]

for model, key, base in tests:
    spec = detect_provider(model, key if key else None, base if base else None)
    name = spec.name if spec else "None"
    print(f"model={model:<25} key={key:<15} base={base:<35} -> {name}")
```

#### 练习 6：创建自定义 ProviderSpec

```python
# ex6_custom_provider.py
from llm_harness.adapters.providers.registry import ProviderSpec, PROVIDERS

# 为私有 LLM 网关创建自定义 spec
custom = ProviderSpec(
    name="my-gateway",
    keywords=("my-gpt", "my-model"),
    env_key="MY_GATEWAY_API_KEY",
    display_name="My Private Gateway",
    backend="openai_compat",
    is_gateway=True,
    default_api_base="https://my-gateway.internal.company.com/v1",
)

# 检查是否尚未在 PROVIDERS 中
existing_names = [s.name for s in PROVIDERS]
if custom.name not in existing_names:
    print(f"Custom spec '{custom.name}' ready for registration")
    print(f"  keywords: {custom.keywords}")
    print(f"  env_key: {custom.env_key}")
    print(f"  api_base: {custom.default_api_base}")
else:
    print(f"Spec '{custom.name}' already exists")
```

### 交付物（15 分钟）

- `config_lab.py` —— 使用 `harness.yaml` 调用 `load_config()`，从配置值构建所有组件，创建 Agent，发送一条消息。
- `provider_test.py` —— 通过 3 种不同的 provider 配置运行同一条消息，打印响应对比。
- 验证：`LLM_HARNESS_API_KEY=sk-xxx python config_lab.py` —— Agent 从 YAML 配置加载并返回连贯回复。

### 课后反思

配置加载链赋予 CLI 参数最高优先级。在多租户 SaaS 部署中，你会添加哪些额外的优先级层级（例如，按账户、按会话、按请求）？

---

## 第 5 天：扩展系统（3.5 小时）

### 理论（1 小时）

扩展系统有四个不同的扩展点：

**1. MCP（模型上下文协议）。** 通过 stdio、SSE 或可流式 HTTP 传输暴露工具的外部工具服务器。

- `MCPServerConnection` —— 快速单服务器连接。用法：`async with MCPServerConnection(command=[...]) as srv: registry.register(tool)`。
- 从 JSON Schema 动态创建 Pydantic 模型（工具通过 MCP 协议定义其输入 schema）。
- 支持通过 `enabled_tools` 列表和 `*` 通配符进行工具过滤。

**2. Skills（技能）。** 渐进式披露知识系统：

- `SkillDefinition` 数据类：`name`、`description`、`content`、`source`、`path`。
- 系统提示中只列出技能名称和描述（保持上下文小巧）。
- 当 LLM 调用 `skill` 工具时，完整的技能内容被加载到上下文中。
- `DirectorySkillLoader._scan()` 遍历目录，查找带有 YAML 前置元数据的 `<name>/SKILL.md` 文件：

```markdown
---
name: my-skill
description: What my skill does
---
Full skill content here...
```

**3. Hooks（钩子）。** 生命周期钩子，包含 4 种类型并支持 `fnmatch` 模式匹配：

- `CommandHookDefinition` —— 执行 shell 命令
- `HttpHookDefinition` —— 发送 HTTP 请求
- `PromptHookDefinition` —— 向 LLM 发送提示
- `AgentHookDefinition` —— 生成子 Agent

`HookEvent` 枚举覆盖了整个生命周期：`PreToolUse`、`PostToolUse`、`PreMessage`、`PostMessage`、`PreProcess`、`PostProcess`、`PreSessionCreate`、`PostSessionCreate`、`PreAgentSpawn`、`PostAgentSpawn`、`PreShutdown`。

`HookExecutor.execute(event, payload)` 根据事件类型 + payload 上的 fnmatch 模式匹配钩子，执行它们，并支持 `block_on_failure` 以中止管道。

**4. Channels（通道）。** 入站/出站通信适配器：

- `BaseChannel` 抽象基类：`start()`、`stop()`、`send()`、`send_delta()`、`is_allowed()`。
- `WebSocketChannel` —— 基于 JSON-over-WebSocket，支持可选的 `auth_callback`、流式 delta、ping/pong。
- `CLIChannel` —— 用于终端交互的 stdin/stdout 通道。
- `ChannelManager` 协调生命周期（`start_all()` / `stop_all()`）、带重试的出站分发（`send_max_retries=3`）以及 `allow_from` 验证。

### 动手实践（2 小时）

#### 练习 1：连接 MCP 服务器

```python
# ex1_mcp.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.extensions.mcp.client import MCPServerConnection

async def main():
    ws = Path("./ws_mcp")
    ws.mkdir(exist_ok=True)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)

    # 构建本地沙箱工具
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "exec"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    # 连接 MCP 服务器（示例：文件系统 MCP 服务器）
    async with MCPServerConnection(command=["npx", "-y", "@modelcontextprotocol/server-filesystem", str(ws)]) as mcp:
        for mcp_tool in mcp.tools:
            print(f"MCP tool: {mcp_tool.name} -- {mcp_tool.description[:60]}")
            tools.register(mcp_tool)

        harness = Harness(provider=provider, model="deepseek-chat",
                          tools=tools, sandbox=sandbox)
        agent = harness.create_agent()
        session = Session(key="mcp:chat1")

        msg = InboundMessage("cli", "user", "c1", "List files in the workspace and create a new file called mcp_demo.txt")
        result = await agent.process(msg, session=session, cwd=ws)
        print("Final:", result.final_content)

asyncio.run(main())
```

#### 练习 2：创建并加载技能

创建 `skills/hello-skill/SKILL.md`：

```markdown
---
name: hello-skill
description: A demo skill that explains the llm-harness greeting protocol
---

# Hello Skill

When a user greets the assistant, respond with a friendly welcome message
that includes the current UTC time. Always ask if they would like a tour
of available skills and tools.
```

然后加载并使用它：

```python
# ex2_skills.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.extensions.skills.loader import load_skills_from_dirs
from llm_harness.extensions.skills.registry import SkillRegistry

async def main():
    ws = Path("./ws_skills")
    ws.mkdir(exist_ok=True)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["write_file", "read_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    # 从目录加载技能
    skill_defs = load_skills_from_dirs(["./skills"])
    skill_registry = SkillRegistry()
    for sd in skill_defs:
        skill_registry.register(sd)
        print(f"Loaded skill: {sd.name} -- {sd.description}")

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      skills=skill_registry)
    agent = harness.create_agent()
    session = Session(key="skills:chat1")

    msg = InboundMessage("cli", "user", "c1", "Hello! What skills do you have?")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)

asyncio.run(main())
```

#### 练习 3：配置并运行钩子

```python
# ex3_hooks.py
import asyncio
from pathlib import Path
from llm_harness.extensions.hooks.events import HookEvent
from llm_harness.extensions.hooks.schemas import CommandHookDefinition, HttpHookDefinition
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext
from llm_harness.extensions.hooks.loader import HookRegistry

async def main():
    registry = HookRegistry()
    registry.register(
        HookEvent.PRE_TOOL_USE,
        CommandHookDefinition(
            command="echo 'PreToolUse: {tool_name}' >> hooks_log.txt",
            block_on_failure=False,
            timeout_seconds=10,
        ),
    )
    registry.register(
        HookEvent.POST_TOOL_USE,
        HttpHookDefinition(
            url="https://httpbin.org/post",
            method="POST",
            headers={"Content-Type": "application/json"},
            body='{"tool": "{tool_name}", "status": "{success}"}',
            block_on_failure=False,
            timeout_seconds=10,
        ),
    )

    context = HookExecutionContext(cwd=Path("."))
    executor = HookExecutor(registry, context)

    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": "read_file", "file_path": "test.txt"},
    )
    print(f"PreToolUse hooks: {len(result.results)} executed, blocked={result.blocked}")

    result2 = await executor.execute(
        HookEvent.POST_TOOL_USE,
        {"tool_name": "read_file", "success": "true"},
    )
    print(f"PostToolUse hooks: {len(result2.results)} executed, blocked={result2.blocked}")

    log = Path("hooks_log.txt")
    if log.exists():
        print(f"Hook log:\n{log.read_text()}")

asyncio.run(main())
```

#### 练习 4：WebSocket 通道

```python
# ex4_websocket.py
# 终端 1：启动 Agent
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage, OutboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.extensions.channels.websocket import WebSocketChannel

async def main():
    ws = Path("./ws_wss")
    ws.mkdir(exist_ok=True)

    bus = MessageBus(maxsize=10_000)
    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox)
    agent = harness.create_agent()

    # 配置 WebSocket 通道
    config = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8082,
        "allow_from": ["*"],
        "streaming": True,
    }
    ws_channel = WebSocketChannel(config, bus)

    # 在后台启动通道
    import asyncio
    channel_task = asyncio.create_task(ws_channel.start())

    # 处理来自总线的入站消息
    async for msg in bus.inbound_messages():
        print(f"Received: {msg.content[:50]}...")
        session = Session(key=f"websocket:{msg.chat_id}")
        result = await agent.process(msg, session=session, cwd=ws)
        outbound = OutboundMessage(channel="websocket", chat_id=msg.chat_id,
                                    content=result.final_content or "")
        await bus.publish_outbound(outbound)

    ws_channel.stop()

asyncio.run(main())
```

然后在另一个终端：`websocat ws://127.0.0.1:8082` 并发送 `{"type":"message","content":"Hello!"}`。

#### 练习 5：双通道（CLI + WebSocket）

`ChannelManager` 处理多个通道。同时接入 `CLIChannel` 和 `WebSocketChannel` 以演示双通道消息路由。

```python
# ex5_dual_channels.py
# 使用 ChannelManager，设置 channel_types={"cli": CLIChannel, "websocket": WebSocketChannel}
# 以及包含两者的 channels_config。
```

### 交付物（15 分钟）

- `extended_agent.py` —— 同时激活 MCP + Skills + Hooks + WebSocket 的 Agent。日志显示每个扩展正在初始化。
- `skills/hello-skill/SKILL.md` —— 带有 YAML 前置元数据的技能定义文件。
- 验证：`python extended_agent.py` —— 启动日志显示所有扩展已激活。

### 课后反思

技能采用渐进式披露（系统提示中仅包含名称，内容按需加载）。与将所有技能内容包含在每次系统提示中相比，这种方法有哪些权衡？

---

## 第 6 天：可观测性、权限与子 Agent（3 小时）

### 理论（1 小时）

**事件系统。** 11 种事件类型，分为两类：

循环事件（在 `AgentLoop.run` 内部触发）：
- `AssistantTextDelta` —— 流式文本块
- `AssistantTurnComplete` —— 完成响应及使用统计
- `ToolExecutionStarted` —— 工具执行之前
- `ToolExecutionCompleted` —— 工具执行完成（含输出和耗时）
- `ErrorEvent` —— 错误（默认可恢复）
- `StatusEvent` —— 状态消息

系统事件（由基础设施触发）：
- `SessionOpened` / `SessionClosed` —— 会话生命周期
- `SubagentSpawned` / `SubagentCompleted` —— 子 Agent 生命周期
- `MemoryConsolidated` —— 消息已归档

`EventEmitter` 封装了一个 `ObservabilityBackend`，提供类型化的 `send()` 方法。

`DefaultObservabilityBackend` 是一个内存中的发布-订阅模式，支持 `on_emit` 回调：

```python
backend = DefaultObservabilityBackend(
    on_emit=lambda event_type, payload: print(f"{event_type}: {payload}")
)
```

**权限系统。** `PermissionMode` 定义了三种模式：

- `DEFAULT` —— 只读工具允许，修改工具需要用户确认
- `PLAN` —— 所有修改工具被阻止
- `FULL_AUTO` —— 所有工具允许

`PermissionChecker.evaluate()` 实现了 9 步检查顺序：

1. 敏感路径拒绝列表（SSH/AWS/GCP/Azure/GPG/Docker/K8s 密钥）—— 始终生效，不可覆盖
2. 检查 `denied_tools` —— 显式拒绝列表
3. 检查 `allowed_tools` —— 显式允许列表
4. 检查 `path_rules` —— 基于 fnmatch 的路径权限
5. 检查 `denied_commands` —— 命令模式拒绝列表
6. `FULL_AUTO` 模式 —— 允许所有
7. 只读检查 —— 允许只读工具
8. `PLAN` 模式 —— 阻止修改工具
9. `DEFAULT` 模式 —— 修改工具需要确认

**Swarm 子系统。** `AgentDefinition` 指定一个命名的 Agent 配置文件：

```python
@dataclass
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    tools_allow: list[str] | None = None
    tools_deny: list[str] | None = None
    tools_extra: list[str] | None = None
    model: str = ""
```

内置 5 个定义：`general-purpose`、`researcher`、`planner`、`executor`、`reviewer`。

`AgentBackend` Protocol 有 3 个方法：`spawn(config)`、`send_message(agent_id, message)`、`stop(agent_id)`。

`SubprocessBackend` —— 将每个子 Agent 作为独立的 OS 进程生成。使用 `Mailbox`（基于文件，使用 `os.replace` 的原子写入，基于游标的轮询）进行跨进程消息传递。子 Agent 生命周期：

```
AgentTool.execute() 
  -> SubprocessBackend.spawn(config) 
    -> create_subprocess_exec(python -m llm_harness --worker ...)
    -> 通过 stdin 发送提示
    -> _watch() 等待进程完成
    -> SubagentSpawned 事件
    -> 进程运行
    -> 捕获 stdout
    -> SubagentCompleted 事件
    -> InboundMessage(task-notification) 发布到 MessageBus
```

每个子 Agent 的工具集：`(harness_tools ∩ allow) - deny + extra`。

### 动手实践（1.5 小时）

#### 练习 1：将所有事件记录到 JSONL

```python
# ex1_events_jsonl.py
import os, json, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.adapters.observability.default import DefaultObservabilityBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./ws_events")
    ws.mkdir(exist_ok=True)
    events_file = Path("./events.jsonl")

    # 带有 on_emit 的可观测性后端，写入 JSONL
    async def write_event(event_type: str, payload: dict):
        line = json.dumps({"type": event_type, **payload}, ensure_ascii=False)
        events_file.open("a", encoding="utf-8").write(line + "\n")
        print(f"[EVENT] {event_type}")

    obs = DefaultObservabilityBackend(on_emit=write_event)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["write_file", "read_file", "web_search"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      observability=obs)
    agent = harness.create_agent()
    session = Session(key="events:chat1")

    msg = InboundMessage("cli", "user", "c1", "Search for 'Python asyncio' and write a summary to summary.txt")
    result = await agent.process(msg, session=session, cwd=ws)
    print(f"Final: {result.final_content}")

    # 解析并统计事件
    events = [json.loads(l) for l in events_file.read_text().strip().split("\n") if l]
    print(f"\nTotal events recorded: {len(events)}")
    from collections import Counter
    types = Counter(e["type"] for e in events)
    for t, count in types.most_common():
        print(f"  {t}: {count}")

asyncio.run(main())
```

#### 练习 2：exec 权限被拒绝

```python
# ex2_permission_deny.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.core.permissions.checker import PermissionChecker
from llm_harness.core.permissions.settings import PermissionSettings
from llm_harness.core.permissions.modes import PermissionMode

async def main():
    ws = Path("./ws_perm")
    ws.mkdir(exist_ok=True)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["exec", "read_file", "write_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    # 显式拒绝 exec 工具
    settings = PermissionSettings(
        mode=PermissionMode.FULL_AUTO,
        denied_tools=["exec"],
    )
    checker = PermissionChecker(settings)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      permissions=checker)
    agent = harness.create_agent()
    session = Session(key="perm:chat1")

    # Agent 会尝试使用 exec，但会被拒绝
    msg = InboundMessage("cli", "user", "c1", "Run 'echo hello' on the command line")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)
    print("Tools used:", result.tools_used)

asyncio.run(main())
```

#### 练习 3：基于路径的权限拒绝

```python
# ex3_path_deny.py
# 设置同练习 2，但添加 path_rules 以拒绝 *.env：
# settings = PermissionSettings(
#     mode=PermissionMode.FULL_AUTO,
#     path_rules=[{"pattern": "*.env", "allow": False}],
# )
# 提示："Read the .env file and tell me its contents"
# 预期：权限被拒绝，并显示路径规则匹配的原因。
```

#### 练习 4：生成一个研究员子 Agent

```python
# ex4_swarm.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.swarm.subprocess import SubprocessBackend

async def main():
    ws = Path("./ws_swarm")
    ws.mkdir(exist_ok=True)

    bus = MessageBus(maxsize=10_000)
    swarm_backend = SubprocessBackend(bus=bus, workspace_root=ws)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox, swarm=swarm_backend, bus=bus,
                          harness_tool_names=["read_file", "write_file", "web_search"])
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "web_search", "agent"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      swarm=swarm_backend)
    agent = harness.create_agent()
    session = Session(key="swarm:chat1")

    msg = InboundMessage("cli", "user", "c1",
        "Use the researcher sub-agent to search for 'Python 3.13 new features' and summarize them.")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)

    # 清理
    await swarm_backend.stop()

asyncio.run(main())
```

#### 练习 5：观察子 Agent 生命周期事件

```python
# ex5_subagent_lifecycle.py
# 添加 DefaultObservabilityBackend，配置 on_emit 打印：
#   agent:spawned, agent:completed
# 观察顺序：
#   session:opened -> agent:spawned -> agent:completed -> task-notification -> session:closed
```

### 交付物（15 分钟）

- `observability_lab.py` —— JSONL 事件记录，附带事件类型计数器。
- `permission_lab.py` —— 演示所有三种权限模式以及基于路径的拒绝。
- `swarm_lab.py` —— 主 Agent 生成一个研究员子 Agent 并返回结果。
- 验证：`python swarm_lab.py` —— 子 Agent 被生成，结果返回给主 Agent。

### 课后反思

权限系统有一个硬编码的敏感路径拒绝列表，无法被覆盖。这是设计缺陷还是必要的安全措施？你会如何在保留内置保护的同时添加按租户的覆盖机制？

---

## 第 7 天：自定义适配器与生产部署（3.5 小时）

### 理论（1 小时）

**四个核心 Protocol 签名。** 框架使用结构子类型（PEP 544）——无需继承，类型检查器在使用点进行验证：

```python
# SandboxBackend Protocol（8 个方法）
@runtime_checkable
class SandboxBackend(Protocol):
    async def create_session(self, session_key: str) -> SandboxSession: ...
    async def destroy_session(self, session_key: str) -> None: ...
    async def read_file(self, session_key: str, path: str) -> str: ...
    async def write_file(self, session_key: str, path: str, content: str) -> None: ...
    async def list_dir(self, session_key: str, path: str) -> list[str]: ...
    async def glob(self, session_key: str, pattern: str) -> list[str]: ...
    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]: ...
    async def execute(self, session_key, command, *, cwd="/workspace", env=None, timeout=60) -> ExecResult: ...

# MemoryBackend Protocol（5 个方法）
@runtime_checkable
class MemoryBackend(Protocol):
    async def get_context(self, namespace: str) -> str: ...
    async def read_section(self, namespace: str, section: str) -> str: ...
    async def append_section(self, namespace: str, section: str, entry: str) -> None: ...
    async def add_history(self, namespace: str, entry: str) -> None: ...
    async def consolidate(self, namespace, messages, provider=None, model="") -> bool: ...

# AgentBackend Protocol（3 个方法）
class AgentBackend(Protocol):
    async def spawn(self, config: SpawnConfig, **kw) -> SpawnResult: ...
    async def send_message(self, agent_id: str, message: str) -> bool: ...
    async def stop(self, agent_id: str) -> bool: ...

# SessionBackend Protocol（3 个方法）
class SessionBackend(Protocol):
    async def load(self, session_key: str) -> dict | None: ...
    async def save(self, session_key: str, state: dict) -> None: ...
    async def list_keys(self) -> list[str]: ...
```

**Protocol 设计理念：**
- 结构子类型：任何具有匹配方法签名的对象都满足该 Protocol —— 无需导入或继承框架代码。
- 零耦合：后端实现不需要 `import llm_harness`。
- 最小接口：只包含框架实际会调用的方法。

**生产检查清单：**

| 关注点 | 配置 |
|---|---|
| 消息总线容量 | `MessageBus(maxsize=10_000)` |
| 归档锁超时 | `asyncio.wait_for(lock.acquire(), timeout=30)` |
| 最大归档轮数 | `MAX_CONSOLIDATION_ROUNDS=5` |
| 最大 ReAct 迭代次数 | `AgentLoop(max_iterations=40)` |
| 工具结果截断 | `TOOL_RESULT_MAX_CHARS=16_000` |
| 日志记录 | `logging.getLogger(__name__)`（每个模块） |
| 优雅关闭 | `Agent.close()` / `ChannelManager.stop_all()` / `SubprocessBackend.stop()` |
| 沙箱隔离 | `SRTSandboxBackend` 配合按账户的工作区 |
| 权限路由 | 按会话路由的 `PermissionChecker` |

**性能特性：**
- 纯异步：热路径上没有任何同步阻塞
- 延迟导入：`ToolFactory` 使用 lambda + `importlib.import_module`
- 提示缓存：同时支持 Anthropic 和 OpenAI 兼容 provider
- HTTP 客户端复用：`httpx.AsyncClient` 在请求间共享

### 动手实践（2 小时）

#### 练习 1：实现 RedisMemoryBackend

```python
# redis_memory.py
"""基于 Redis 的 MemoryBackend 实现。

满足 MemoryBackend Protocol，无需从 llm-harness 导入任何内容。
测试使用 fakeredis，生产环境使用 redis-py。
"""
from __future__ import annotations

import json
from typing import Any


class RedisMemoryBackend:
    """在 Redis 中存储上下文和历史记录的内存后端。

    Namespace -> Redis 键前缀。
    上下文存储为普通字符串键。
    章节存储为哈希字段。
    历史记录存储为有序集合（基于时间戳排序）。
    """

    def __init__(self, redis_client: Any, key_prefix: str = "memory"):
        self._redis = redis_client
        self._prefix = key_prefix

    def _key(self, namespace: str) -> str:
        return f"{self._prefix}:{namespace}"

    def _section_key(self, namespace: str, section: str) -> str:
        return f"{self._prefix}:{namespace}:section:{section}"

    def _history_key(self, namespace: str) -> str:
        return f"{self._prefix}:{namespace}:history"

    async def get_context(self, namespace: str) -> str:
        val = await self._redis.get(self._key(namespace))
        return val or ""

    async def read_section(self, namespace: str, section: str) -> str:
        val = await self._redis.hget(self._section_key(namespace, section), "content")
        return val or ""

    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        key = self._section_key(namespace, section)
        existing = await self._redis.hget(key, "content") or ""
        await self._redis.hset(key, "content", existing + "\n" + entry)

    async def add_history(self, namespace: str, entry: str) -> None:
        import time
        key = self._history_key(namespace)
        await self._redis.zadd(key, {entry: time.time()})

    async def consolidate(self, namespace: str, messages: list[dict[str, Any]],
                          provider: Any = None, model: str = "") -> bool:
        key = self._history_key(namespace)
        serialized = json.dumps(messages, ensure_ascii=False)
        import time
        await self._redis.zadd(key, {serialized: time.time()})
        return True
```

#### 练习 2：RedisMemoryBackend 的单元测试

```python
# test_redis_memory.py
"""RedisMemoryBackend 的测试，使用 fakeredis。"""
import pytest
from redis_memory import RedisMemoryBackend


@pytest.fixture
async def backend():
    import fakeredis
    r = fakeredis.FakeAsyncRedis()
    b = RedisMemoryBackend(r)
    yield b
    await r.flushall()


class TestRedisMemoryBackend:
    @pytest.mark.asyncio
    async def test_get_context_returns_empty_for_new_namespace(self, backend):
        ctx = await backend.get_context("test:ns1")
        assert ctx == ""

    @pytest.mark.asyncio
    async def test_append_and_read_section(self, backend):
        await backend.append_section("test:ns1", "memory", "first entry")
        await backend.append_section("test:ns1", "memory", "second entry")
        content = await backend.read_section("test:ns1", "memory")
        assert "first entry" in content
        assert "second entry" in content

    @pytest.mark.asyncio
    async def test_add_history(self, backend):
        await backend.add_history("test:ns1", "user hello")
        await backend.add_history("test:ns1", "assistant hi")
        key = backend._history_key("test:ns1")
        count = await backend._redis.zcard(key)
        assert count == 2

    @pytest.mark.asyncio
    async def test_consolidate(self, backend):
        messages = [{"role": "user", "content": "hello"}]
        ok = await backend.consolidate("test:ns1", messages)
        assert ok is True

    @pytest.mark.asyncio
    async def test_read_section_empty_for_new_section(self, backend):
        content = await backend.read_section("test:ns1", "rules")
        assert content == ""

    @pytest.mark.asyncio
    async def test_multiple_namespaces_isolated(self, backend):
        await backend.append_section("ns1", "memory", "data1")
        await backend.append_section("ns2", "memory", "data2")
        c1 = await backend.read_section("ns1", "memory")
        c2 = await backend.read_section("ns2", "memory")
        assert c1 == "\ndata1"
        assert c2 == "\ndata2"
        assert c1 != c2
```

#### 练习 3：实现 DockerSandboxBackend

```python
# docker_sandbox.py
"""基于 Docker 的 SandboxBackend —— 每个会话一个容器。"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SandboxSession:
    session_key: str
    volume_path: str
    sandbox_id: str


@dataclass
class ExecResult:
    output: str
    exit_code: int = 0
    is_error: bool = False


class DockerSandboxBackend:
    """每个会话一个 Docker 容器，销毁时自动移除。"""

    def __init__(self, image: str = "python:3.12-slim", workspace_root: str | Path = "./workspace"):
        self._image = image
        self._root = Path(workspace_root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._containers: dict[str, str] = {}  # session_key -> container_id

    async def create_session(self, session_key: str) -> SandboxSession:
        vol = str(self._root / session_key.replace(":", "_"))
        Path(vol).mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "-d", "--rm",
            "-v", f"{vol}:/workspace",
            "-w", "/workspace",
            self._image,
            "sleep", "infinity",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        container_id = stdout.decode().strip()
        self._containers[session_key] = container_id
        return SandboxSession(
            session_key=session_key,
            volume_path="/workspace",
            sandbox_id=container_id,
        )

    async def destroy_session(self, session_key: str) -> None:
        cid = self._containers.pop(session_key, None)
        if cid:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", cid,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()

    async def read_file(self, session_key: str, path: str) -> str:
        cid = self._containers.get(session_key)
        if not cid:
            return ""
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", cid, "cat", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode(errors="replace")

    async def write_file(self, session_key: str, path: str, content: str) -> None:
        cid = self._containers.get(session_key)
        if not cid:
            raise RuntimeError(f"No container for session {session_key}")
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", cid, "sh", "-c", f"mkdir -p $(dirname {path}) && cat > {path}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(input=content.encode())

    async def execute(self, session_key: str, command: str, *,
                      cwd: str = "/workspace", env: dict | None = None,
                      timeout: int = 60) -> ExecResult:
        cid = self._containers.get(session_key)
        if not cid:
            return ExecResult(output="No container", exit_code=-1, is_error=True)
        cmd = ["docker", "exec", "-w", cwd]
        if env:
            for k, v in env.items():
                cmd.extend(["-e", f"{k}={v}"])
        cmd.extend([cid, "sh", "-c", command])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecResult(
                output=stdout.decode(errors="replace"),
                exit_code=proc.returncode or 0,
                is_error=proc.returncode != 0,
            )
        except asyncio.TimeoutError:
            return ExecResult(output="Command timed out", exit_code=-1, is_error=True)
```

#### 练习 4：实现 SQLiteSessionBackend

```python
# sqlite_session.py
"""基于 SQLite 的 SessionBackend —— 满足 SessionBackend Protocol。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteSessionBackend:
    """在本地 SQLite 数据库中持久化会话状态。"""

    def __init__(self, db_path: str | Path = "./sessions.db"):
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  key TEXT PRIMARY KEY,"
            "  state TEXT NOT NULL,"
            "  updated_at TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    async def load(self, session_key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT state FROM sessions WHERE key = ?", (session_key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    async def save(self, session_key: str, state: dict[str, Any]) -> None:
        from datetime import datetime, timezone
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (key, state, updated_at) VALUES (?, ?, ?)",
            (session_key, json.dumps(state), datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    async def list_keys(self) -> list[str]:
        rows = self._conn.execute("SELECT key FROM sessions ORDER BY updated_at DESC").fetchall()
        return [row[0] for row in rows]

    def close(self):
        self._conn.close()
```

#### 练习 5：生产级 docker-compose.yml

创建 `deploy/docker-compose.yml`：

```yaml
version: "3.9"

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s

  tencentdb:
    image: tencentdb/memory:latest
    ports:
      - "8420:8420"
    environment:
      DB_PATH: /data/tencentdb
    volumes:
      - tencentdb_data:/data

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: sessions
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: changeme
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent -d sessions"]
      interval: 5s

  agent:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8080:8080"
    environment:
      LLM_HARNESS_REDIS_URL: redis://redis:6379/0
      LLM_HARNESS_MEMORY_URL: http://tencentdb:8420
      LLM_HARNESS_DB_URL: postgresql://agent:changeme@postgres:5432/sessions
      LLM_HARNESS_API_KEY: ${LLM_HARNESS_API_KEY}
      LLM_HARNESS_MODEL: ${LLM_HARNESS_MODEL:-deepseek-chat}
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    volumes:
      - agent_workspace:/workspace

volumes:
  redis_data:
  tencentdb_data:
  postgres_data:
  agent_workspace:
```

### 交付物（15 分钟）

- `redis_memory.py` —— 完整的 RedisMemoryBackend 实现，包含所有 5 个 MemoryBackend 方法。
- `test_redis_memory.py` —— 6 个以上使用 fakeredis 的测试。
- `docker_sandbox.py` —— 完整的 DockerSandboxBackend 实现，包含所有 8 个 SandboxBackend 方法。
- `deploy/docker-compose.yml` —— 多服务生产栈。
- 验证：`pytest test_redis_memory.py -v` —— 所有测试通过。

### 课后反思

框架在其后端接口中使用结构子类型（Protocols）而不是抽象基类。对于一个想要贡献新后端的团队来说，这在实际中有哪些影响？这对 IDE 自动补全和类型检查有什么影响？

---

## 每日检查点

```
Day 1 -- LLM_HARNESS_API_KEY=sk-xxx python hello_agent.py       -> outputs coherent reply
Day 2 -- LLM_HARNESS_API_KEY=sk-xxx python tool_lab.py           -> 3+ tools invoked in chain
Day 3 -- python session_lab.py                                   -> consolidation triggered by round 8
Day 4 -- LLM_HARNESS_API_KEY=sk-xxx python config_lab.py         -> Agent loaded from YAML
Day 5 -- python extended_agent.py                                -> MCP + Skills + WebSocket all active
Day 6 -- python swarm_lab.py                                     -> sub-agent spawned and result returned
Day 7 -- pytest test_redis_memory.py -v                          -> all tests pass
```

每个检查点是一个"继续/停止"的门禁。如果当天的交付物未通过，请在继续之前重新审视相关练习。
