# Day 5：子 Agent、调度与钩子

> **目标读者**：已理解 AgentLoop 的主循环与工具系统，想深入了解子 Agent 的并发模型、后台定时任务调度和生命周期钩子机制。
> **学完本节后，你应该能回答**：子 Agent 为什么跑在独立的 asyncio.Task 中？它的 mini ReAct loop 与主 AgentLoop 有什么本质区别？CronService 如何保证定时任务的持久性和准确性？Hook 的 interceptor 模式怎么拦截工具调用？

---

## 一、深度解释

### 1.1 SubagentManager：为什么子 Agent 要跑在独立的 asyncio.Task 里？

在 `src/agent_harness/coordinator/subagent.py` 中，`SubagentManager` 的 `spawn` 方法在被调用时会创建一个 `asyncio.Task`：

```python
async def spawn(self, task, label=None, origin_channel="cli",
                origin_chat_id="direct", session_key=None) -> str:
    task_id = str(uuid.uuid4())[:8]
    bg_task = asyncio.create_task(
        self._run_subagent(task_id, task, display_label, origin)
    )
    self._running_tasks[task_id] = bg_task
    if session_key:
        self._session_tasks.setdefault(session_key, set()).add(task_id)
    ...
    return f"Subagent [{display_label}] started (id: {task_id})."
```

核心决策：**子 Agent 必须与主 Agent 并发运行，而不是串行等待**。当一个子 Agent 正在执行 `web_search` 或 `read_file` 时，主 Agent 不应该阻塞——它需要继续处理用户的新输入。asyncio.Task 提供了 Python 协程层面的抢占式调度：当子 Agent 的 `await` 让出控制权时，主 Agent 的 Task 可以继续执行。

这与多线程方案的关键区别在于：
- **无 GIL 问题**：所有 Task 运行在同一个线程中，切换发生在 `await` 点，不需要锁。
- **取消安全**：`asyncio.Task.cancel()` 会注入 `CancelledError`，子 Agent 可以在 `try/finally` 中清理资源。
- **回调通知**：`add_done_callback` 在 Task 完成时自动触发清理。

### 1.2 子 Agent 的 mini ReAct loop 与主 AgentLoop 的区别

主 AgentLoop（见 Day 2）是一个复杂的有限状态机，支持暂停、恢复、流式输出和用户确认。子 Agent 的 `_run_subagent` 则是一个**简化的 while 循环**：

```python
while iteration < self.max_iterations:
    iteration += 1
    response = await self.provider.chat_with_retry(
        messages=messages,
        tools=self.tools.to_api_schema(api_format="openai"),
        model=self.model,
    )
    if response.has_tool_calls:
        # 执行工具，将结果追加回 messages
        for tool_call in response.tool_calls:
            result = await self._execute_tool(tool_call.name, tool_call.arguments, ctx)
            messages.append({"role": "tool", "tool_call_id": tool_call.id,
                             "name": tool_call.name, "content": result})
    else:
        final_result = response.content
        break
```

**为什么主 AgentLoop 复杂而子 Agent 简单？**

主 AgentLoop 需要处理：
1. **用户打断**：用户在 Agent 思考过程中输入新消息
2. **流式输出**：逐 token 推送到前端
3. **权限确认**：敏感操作需要用户点击确认
4. **会话持久化**：每轮对话保存到 JSONL

子 Agent 则完全不同：
- 它的执行是**后台**的，用户不直接与它交互
- 它的最终结果通过 MessageBus 发布为一条 `InboundMessage`，主 Agent 收到后再"自然地"转述给用户
- 它不需要流式输出——用户不会看到子 Agent"正在打字"

所以子 Agent 的循环是一个纯粹的函数式 pipeline：LLM 生成 -> 执行工具 -> 结果追加 -> 继续循环。没有状态机，没有中断处理。

### 1.3 spawn 的输入模型与 MessageBus 通信

`spawn` 方法的五个参数构成了**子 Agent 的上下文契约**：

| 参数 | 用途 |
|------|------|
| `task` | 子 Agent 要执行的任务描述（用户意图的自然语言） |
| `label` | 人类可读的标签，用于日志和通知 |
| `origin_channel` | 来源频道（如 `cli`、`telegram`），结果发布时原路返回 |
| `origin_chat_id` | 对话标识，与 origin_channel 组合成 `channel:chat_id` 格式的 chat_id |
| `session_key` | 用于按会话批量取消（通过 `cancel_by_session`） |

子 Agent 完成后的结果通过 `_announce_result` 注入到 MessageBus：

```python
msg = InboundMessage(
    channel="system",
    sender_id="subagent",
    chat_id=f"{origin['channel']}:{origin['chat_id']}",
    content=announce_content,
)
await self.bus.publish_inbound(msg)
```

注意这里使用了 `channel="system"` —— 这是一个特殊通道，主 Agent 的 `_handle_system_messages` 会专门处理它。announce_content 的末尾包含一段元指令：

```
"Summarize this naturally for the user. "
"Keep it brief (1-2 sentences). "
"Do not mention technical details like 'subagent' or task IDs."
```

这保证了主 Agent 不会机械地复读技术细节，而是用自然语言告知用户结果。

### 1.4 _build_subagent_prompt 的模板组装

子 Agent 的 system prompt 在 `_build_subagent_prompt` 中动态组装：

```python
def _build_subagent_prompt(self) -> str:
    time_ctx = ContextBuilder._build_runtime_context(None, None)
    parts = [
        f"# Subagent\n{time_ctx}\n"
        f"You are a subagent spawned by the main agent to complete a specific task.\n"
        f"Stay focused on the assigned task. "
        f"Your final response will be reported back to the main agent.\n"
        ...
    ]
    # 从 workspace/skills 目录加载可用技能
    if self.workspace:
        skills_dir = self.workspace / "skills"
        if skills_dir.exists():
            skills = load_skills_from_dirs([skills_dir])
            ...
    return "\n\n".join(parts)
```

这里有个重要的设计取舍：**子 Agent 的 prompt 比主 Agent 的 system prompt 短得多**。主 Agent 的 system prompt 由 ContextBuilder 的 SectionProvider 链组装（包含环境信息、身份定义、AGENTS.md、技能列表、记忆摘要等），而子 Agent 只包含时间上下文、角色定义、工作空间路径和可选的技能列表。原因是子 Agent 的 token 预算应该尽可能留给任务执行本身。

### 1.5 清理机制：add_done_callback 与 cancel_by_session

子 Agent 的 Task 注册了一个 `_cleanup` 回调：

```python
def _cleanup(_: asyncio.Task) -> None:
    self._running_tasks.pop(task_id, None)
    if session_key and (ids := self._session_tasks.get(session_key)):
        ids.discard(task_id)
        if not ids:
            del self._session_tasks[session_key]

bg_task.add_done_callback(_cleanup)
```

`add_done_callback` 在 Task 正常完成、被取消或抛出异常时都会触发。这保证了 `_running_tasks` 字典不会泄漏已退出的 Task。

`cancel_by_session` 用于批量取消某个会话的所有子 Agent：

```python
async def cancel_by_session(self, session_key: str) -> int:
    tasks = [
        self._running_tasks[tid]
        for tid in self._session_tasks.get(session_key, [])
        if tid in self._running_tasks and not self._running_tasks[tid].done()
    ]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    return len(tasks)
```

关键点：`async def` + `asyncio.gather` 保证了取消是**异步等待**的——调用者知道所有子 Agent 何时真正停止。

### 1.6 CronService 的定时轮询架构

`src/agent_harness/cron/service.py` 的 CronService 不使用 while True + sleep 轮询，而是使用**事件驱动的单次定时器**：

```python
def _arm_timer(self) -> None:
    if self._timer_task:
        self._timer_task.cancel()
    next_wake = self._get_next_wake_ms()
    if not next_wake or not self._running:
        return
    delay_ms = max(0, next_wake - _now_ms())
    delay_s = delay_ms / 1000

    async def tick():
        await asyncio.sleep(delay_s)
        if self._running:
            await self._on_timer()

    self._timer_task = asyncio.create_task(tick())
```

每次 `tick` 执行后，`_arm_timer` 被再次调用，安排下一次唤醒。这比固定间隔轮询更高效：如果下一个任务在 24 小时后，系统不会在这 24 小时内空转。

CronJob 的三种调度类型在 `cron/types.py` 中定义：

```python
@dataclass
class CronSchedule:
    kind: Literal["at", "every", "cron"]
    at_ms: int | None = None       # 一次性时间戳
    every_ms: int | None = None    # 固定间隔（毫秒）
    expr: str | None = None        # cron 表达式，如 "0 9 * * *"
```

`_compute_next_run` 对 `cron` 类型的解析使用了 `croniter` 库，支持带时区的标准 crontab 表达式。`_validate_schedule_for_add` 在添加时区相关任务时立即验证 ZoneInfo 合法性，而不是等到运行时才报错。

CronStore 的持久化采用 JSON 文件，每次状态变更后 `_save_store` 将完整状态写盘。这种"全量写入"策略在小规模场景（几十个任务）下足够高效，且避免了增量日志的合并复杂度。

### 1.7 Hook 系统：四种执行模式

Hook 系统在 `src/agent_harness/hooks/` 下分为三个层次：

**事件定义** (`events.py`)：
```python
class HookEvent(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
```

四种事件覆盖了整个 Agent 会话的生命周期。`PRE_TOOL_USE` 和 `POST_TOOL_USE` 是工具调用前后的拦截点。

**钩子类型** (`schemas.py`) 定义了四种执行模式：

| 类型 | 执行方式 | 典型用途 |
|------|----------|----------|
| `command` | 创建 subprocess 执行 shell 命令 | 通知部署系统、写入监控日志 |
| `http` | 用 httpx POST 事件载荷到 URL | Webhook 回调 |
| `prompt` | 用 LLM 验证条件，返回 `{"ok": true/false}` | 内容安全审查 |
| `agent` | 同 prompt 但更严格（提示 LLM "thorough"） | 高风险操作二次确认 |

**为什么需要 matcher？**

`_matches_hook` 函数使用 fnmatch 匹配 `tool_name` 或 `prompt` 字段：

```python
def _matches_hook(hook: HookDefinition, payload: dict[str, Any]) -> bool:
    matcher = getattr(hook, "matcher", None)
    if not matcher:
        return True
    subject = str(payload.get("tool_name") or payload.get("prompt") or ...)
    return fnmatch.fnmatch(subject, matcher)
```

这意味者你可以为 `pre_tool_use` 注册一条钩子，但只让它对 `shell` 工具有效：`matcher="shell"`。fnmatch 还支持通配符，例如 `matcher="web_*"` 匹配所有 web 相关工具。

**block_on_failure 的语义**：如果设为 `True`，该钩子返回 `success=False` 时，`AggregatedHookResult` 中的 `blocked` 字段为 True，调用者（如 PermissionChecker 或 AgentLoop）应当停止执行。这实现了"审批门"模式——某条钩子不通过，整个工具调用被拒绝。

### 1.8 Hooks 的边界：什么场景不该用 Hook

Hooks 是强大的拦截器，但它们只在**四个事件**（`SESSION_START`、`SESSION_END`、`PRE_TOOL_USE`、`POST_TOOL_USE`）触发。以下场景 Hook 无法覆盖，需要使用 `LoopCallbacks` 或 `Agent` 的回调参数：

| 需求 | 正确方案 | 说明 |
|------|---------|------|
| LLM 流式文本输出 | `Agent(on_stream=...)` 或 `LoopCallbacks.on_stream` | Hooks 不参与 LLM 调用过程 |
| 工具开始时的进度提示 | `Agent(on_progress=...)` 或 `LoopCallbacks.on_progress` | 不存在对应的 Hook 事件 |
| 自定义循环终止条件 | 直接使用 `AgentLoop` | Hooks 只能阻断单个工具执行 |
| 动态修改工具列表 | `LoopCallbacks.get_tool_definitions` | Hooks 在工具调用后才触发 |
| Token 用量监控 | `Agent(on_event=...)` 或 `LoopCallbacks.on_event` | Hooks 不接触 LLM 响应 |

**核心判断**：需要"工具执行前/后插入逻辑"用 Hook；需要"介入循环控制流或 LLM 输出"用回调。

---

## 二、源码导读

### 2.1 `coordinator/subagent.py` — Spawn 到完成的完整流程 (364 行)

从 `spawn()` 入口到结果返回主 Agent，整体流程如下：

1. **spawn()** (L91-127)：生成 task_id，创建 asyncio.Task，注册 `_cleanup` 回调，记录到 `_session_tasks`，返回确认消息
2. **_run_subagent()** (L150-240)：构建 subagent prompt → 初始化消息列表 → while 循环（LLM 调用 → 工具执行 → 结果追加）→ 循环结束或达到 max_iterations → 调用 `_announce_result`
3. **_execute_tool()** (L242-260)：从 ToolRegistry 查找工具 → `input_model(**arguments)` 类型校验 → `tool.execute()` 执行
4. **_announce_result()** (L266-305)：构建 system 通道的 InboundMessage，发布到 MessageBus

关键设计观察：`_execute_tool` 中的 `input_model(**arguments)` 校验发生在每次工具调用之前。如果子 Agent 传入了非法参数（如类型错误），`Pydantic` 的验证错误会被捕获并返回给 LLM 的 messages，而不是让整个 Task 崩溃。这意味着 LLM 可以"看到"自己的错误并自我修正。

### 2.2 `cron/service.py` — 定时轮询与任务调度 (418 行)

CronService 的生命周期：

1. **start()** (L197-204)：设置 `_running = True`，从磁盘加载 CronStore，重算所有任务的 next_run_at，写入磁盘，启动定时器
2. **_on_timer()** (L249-265)：重新加载 store（检视文件是否被外部修改）→ 找出所有到期任务 → 依次执行 → 保存 store → 重新 arm 定时器
3. **_execute_job()** (L267-312)：记录开始时间 → 调用 `on_job` 回调 → 记录状态/错误 → 更新 run_history（保留最近 20 条）→ 处理一次性任务（enabled=False 或删除）
4. **stop()** (L206-210)：取消定时器 Task，设置 `_running = False`

`_load_store` 的**外部修改检测**很实用：它检查 `store_path.stat().st_mtime`，如果文件 mtime 变了就重新加载。这让你可以手动编辑 jobs.json 添加任务，CronService 在下一次 timer tick 时自动识别。

### 2.3 `hooks/executor.py` — subprocess 执行与超时控制 (240 行)

`_run_command_hook` 是核心方法：

```python
async def _run_command_hook(self, hook, event, payload) -> HookResult:
    command = _inject_arguments(hook.command, payload, shell_escape=True)
    process = await asyncio.create_subprocess_shell(
        command, cwd=self._context.cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "AGENT_HARNESS_HOOK_EVENT": event.value,
             "AGENT_HARNESS_HOOK_PAYLOAD": json.dumps(payload)},
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=hook.timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        ...
```

使用 `asyncio.create_subprocess_shell` 而不是 `subprocess.run` 的原因是**非阻塞**：Hook 执行不应该阻塞主事件循环。`asyncio.wait_for` 提供超时控制——command 钩子的默认超时是 30 秒。

`_inject_arguments` 负责将事件 payload 注入到命令模板中：

```python
def _inject_arguments(template: str, payload, *, shell_escape=False) -> str:
    serialized = json.dumps(payload, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)
    return template.replace("$ARGUMENTS", serialized)
```

这意味着你可以在 hook 配置中写 `curl -X POST http://example.com/hook -d '$ARGUMENTS'`，运行时 `$ARGUMENTS` 会被替换为 JSON 序列化的事件载荷。

### 2.4 `hooks/loader.py` — JSON 解析与 HookRegistry 组装 (62 行)

HookLoader 的逻辑分布在两个位置：`load_hook_registry` 和 `HookRegistry`。

```python
def load_hook_registry(settings, plugins=None) -> HookRegistry:
    registry = HookRegistry()
    for raw_event, hooks in settings.hooks.items():
        try:
            event = HookEvent(raw_event)
        except ValueError:
            continue
        for hook in hooks:
            registry.register(event, hook)
    ...
    return registry
```

`HookRegistry` 使用 `defaultdict(list)` 存储 `HookEvent -> list[HookDefinition]`。注册时按事件类型分组，执行时 `_registry.get(event)` 获取该事件的所有钩子。四种钩子类型（command/prompt/http/agent）在 `schemas.py` 中定义为 Union 类型，Pydantic 的 discriminated union 根据 `type` 字段自动派发到正确的 Definition 类。

---

## 三、动手练习：给 SubagentManager 添加并发限制

当前的 `SubagentManager` 没有并发限制——用户可以随意 spawn 子 Agent，可能导致数百个 LLM 请求同时运行。让我们加入 `asyncio.Semaphore` 控制最大并发数。

### 3.1 修改 SubagentManager

编辑 `src/agent_harness/coordinator/subagent.py`：

```python
class SubagentManager:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        bus: MessageBus,
        model: str | None = None,
        max_iterations: int = 15,
        workspace: Path | None = None,
        max_concurrent: int = 5,  # 新增：最大并发数
    ):
        ...
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)  # 新增：信号量

    async def spawn(self, task, label=None, origin_channel="cli",
                    origin_chat_id="direct", session_key=None) -> str:
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        # 在创建 Task 之前检查信号量
        if self._semaphore.locked():
            logger.warning(
                "Subagent concurrency limit reached (%d/%d), queuing task %s",
                self.max_concurrent - self._semaphore._value,  # 注意：_value 是 Semaphore 内部属性
                self.max_concurrent,
                task_id,
            )

        bg_task = asyncio.create_task(
            self._run_subagent_with_semaphore(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)
        logger.info("Spawned subagent [%s]: %s", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id})."

    async def _run_subagent_with_semaphore(
        self, task_id: str, task: str, label: str, origin: dict[str, str]
    ) -> None:
        """在信号量控制下运行子 Agent。"""
        async with self._semaphore:
            await self._run_subagent(task_id, task, label, origin)
```

### 3.2 添加状态查询方法

```python
@property
def concurrency_info(self) -> dict:
    """返回当前并发状态。"""
    return {
        "max_concurrent": self.max_concurrent,
        "running": len(self._running_tasks),
        "available_slots": self.max_concurrent - (
            self.max_concurrent - self._semaphore._value
        ),
    }
```

### 3.3 编写测试

创建 `tests/test_subagent_concurrency.py`：

```python
"""Test subagent concurrency limiting."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_harness.coordinator.subagent import SubagentManager
from agent_harness.bus.queue import MessageBus


class MockProvider:
    """A provider that simulates slow LLM calls."""
    async def chat_with_retry(self, messages, tools, model):
        await asyncio.sleep(0.5)  # 模拟耗时
        mock = MagicMock()
        mock.has_tool_calls = False
        mock.content = "done"
        return mock

    def get_default_model(self):
        return "mock-model"


@pytest.mark.asyncio
async def test_concurrency_limit():
    """Verify that at most max_concurrent subagents run simultaneously."""
    bus = MessageBus()
    tools = MagicMock()
    tools.to_api_schema.return_value = []
    tools.get.return_value = None

    manager = SubagentManager(
        provider=MockProvider(),  # type: ignore
        tools=tools,
        bus=bus,
        max_concurrent=2,  # 限制为 2 个并发
    )

    # 启动 5 个子 Agent
    tasks = []
    for i in range(5):
        t = asyncio.create_task(manager.spawn(f"task {i}"))
        tasks.append(t)

    # 给子 Agent 一点时间启动
    await asyncio.sleep(0.3)

    # 此时最多只有 2 个实际运行
    running = manager.get_running_count()
    assert running <= 2, f"Expected <= 2 running, got {running}"

    # 等待所有完成
    await asyncio.gather(*tasks)
    assert manager.get_running_count() == 0


@pytest.mark.asyncio
async def test_no_limit_without_semaphore():
    """Without semaphore (max_concurrent=0), all spawn immediately."""
    bus = MessageBus()
    tools = MagicMock()
    tools.to_api_schema.return_value = []
    tools.get.return_value = None

    manager = SubagentManager(
        provider=MockProvider(),  # type: ignore
        tools=tools,
        bus=bus,
        max_concurrent=0,  # 0 表示不限制
    )

    # 重写 spawn，跳过信号量
    original_spawn = manager.spawn

    async def noop_spawn(task, label=None, **kw):
        return await original_spawn(task, label, **kw)

    tasks = []
    for i in range(10):
        t = asyncio.create_task(manager.spawn(f"task {i}"))
        tasks.append(t)

    await asyncio.sleep(0.2)
    assert manager.get_running_count() >= 1
    await asyncio.gather(*tasks)
```

### 3.4 运行测试

```bash
cd E:/work-space/agent-harness
python -m pytest tests/test_subagent_concurrency.py -v -x
```

这个练习让你理解了：
1. `asyncio.Semaphore` 作为并发控制原语，在 async with 块中自动管理计数
2. 子 Agent 的 Task 生命周期：spawn -> 排队 -> 获取信号量 -> 执行 -> 释放信号量 -> 清理
3. 为什么信号量放在 `_run_subagent_with_semaphore` 中而不是 `spawn` 中：信号量控制的是**实际执行**的并发，而不是 spawn 调用的并发
4. `get_running_count()` 返回的是已 spawn 的总数（包括正在排队等待信号量的），要获取真实并发数需额外方法
