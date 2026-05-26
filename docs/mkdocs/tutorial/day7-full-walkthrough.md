# Day 7：贯通 — 一条消息的完整旅程

> **目标读者**：已完成前 6 天学习，理解 Agent 循环、工具系统、上下文组装、记忆合并、子代理调度和安全通道，希望看到所有子系统如何协作完成一次完整请求。
> **学完本节后，你应该能**：在脑中完整回放一条消息从 CLI 输入到最终响应的全过程，能在源码中定位每个环节的精确位置，能自主添加横切性能计时。

---

## 一、深度解释

### 1.1 全程鸟瞰图

过去 6 天我们逐个拆解了 agent-harness 的各个子系统。今天是最后一天 — 我们追踪一条真实的消息，从用户输入到最终输出，走遍所有环节。

```ascii
CLI/Channel 输入 "帮我读 README.md"
  │
  ├─ 1. MessageBus.publish_inbound(InboundMessage)
  │      — 消息标准化: channel/sender_id/chat_id/content → InboundMessage
  │      — session_key 自动生成 (channel:chat_id)
  │
  ├─ 2. Agent.process(msg)
  │      ├─ 2a. 并发控制: per-session asyncio.Lock + 全局 Semaphore
  │      ├─ 2b. SessionManager.get_or_create → 加载历史 JSONL
  │      ├─ 2c. MemoryConsolidator.maybe_consolidate_by_tokens
  │      │      — 检查消息数是否超过 token 阈值
  │      │      — LLM 摘要压缩 → 写入 MEMORY.md + HISTORY.md
  │      ├─ 2d. Harness.on_build_context(msg, history)
  │      │      — ContextBuilder.build_system_prompt()
  │      │      — 各 SectionProvider 按 priority 输出
  │      │      — ContextBuilder.build_messages() 组装 [system, ...history, user]
  │      │
  │      ├─ 2e. AgentLoop.run_react_loop(initial_messages)
  │      │      │
  │      │      ├─ Loop 1: LLM.chat_with_retry()
  │      │      │   — AnthropicProvider.chat() → Anthropic SDK → Claude API
  │      │      │   — LLMResponse: content=None, tool_calls=[read_file(path="README.md")]
  │      │      │
  │      │      ├─ PermissionChecker.evaluate("read_file", is_read_only=True)
  │      │      │   — 模式检查 → 只读放行
  │      │      │
  │      │      ├─ ReadFileTool.execute()
  │      │      │   — 路径解析 (workspace 限制)
  │      │      │   — 文件读取 (支持图片 magic bytes 检测)
  │      │      │   — 返回 ToolResult(output="文件内容...")
  │      │      │
  │      │      ├─ Tracker 记录: ToolExecutionStarted → ToolExecutionCompleted
  │      │      │
  │      │      └─ Loop 2: LLM.chat_with_retry()
  │      │          — 消息: [...system, user, assistant+tool_calls, tool_result]
  │      │          — LLMResponse: content="README.md 的内容是...", tool_calls=None
  │      │          — AssistantTurnComplete 事件触发
  │      │
  │      └─ TurnResult(final_content="README.md 的内容是...", messages=[...], usage={...})
  │
  ├─ 2f. _save_turn(session, result, initial_count)
  │      — 提取新消息: result.messages[initial_count:]
  │      — 截断超长 tool 结果 (16K 限制)
  │      — SessionManager.save(session)
  │
  └─ 3. 返回 OutboundMessage → ChannelManager._dispatch_outbound → Channel.send()
```

### 1.2 第 1 步：消息进入总线

当用户在 CLI 输入 "帮我读 README.md"，首先被包装为一个 `InboundMessage`：

```python
msg = InboundMessage(
    channel="cli",
    sender_id="user",
    chat_id="direct",
    content="帮我读 README.md",
)
```

这个对象通过 `MessageBus.publish_inbound(msg)` 进入异步队列。`MessageBus` 是两端解耦的桥梁 — 它的内部不过是两个 `asyncio.Queue`（`src/agent_harness/bus/queue.py:16-17`）：

```python
self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
```

`session_key` 属性（`src/agent_harness/bus/events.py:35-41`）自动生成为 `"cli:direct"`（`channel:chat_id` 格式）。这个键是后续所有会话管理和并发控制的基石。

### 1.3 第 2 步：Agent.process — 并发控制

`Agent.process()` 是整个系统的中枢。它的第一件事是**并发控制**（`src/agent_harness/agent.py:174-177`）：

```python
lock = self._session_locks.setdefault(msg.session_key, asyncio.Lock())
gate = self._concurrency_gate or nullcontext()
async with lock, gate:
```

这里有两层节制：
- **per-session Lock**：同一会话的消息串行处理，不会乱序。
- **全局 Semaphore**（默认 `max_concurrent=3`）：不同会话可以并行，但限制总并发数以免压垮 LLM API。

这回答了 Day 1 的问题：「多用户同时使用会怎样？」答案就是：用户 A 和 B 互不阻塞，但用户 A 的两条连续消息不会交错。

### 1.4 第 2b 步：会话加载

如果配置了 sessions，Agent 从 `SessionManager` 加载或创建会话（`agent.py:183-189`）：

```python
session = self.harness.sessions.get_or_create(msg.session_key)
history = session.get_history()
session.add_message("user", msg.content)
self.harness.sessions.save(session)
```

`get_or_create()`（`src/agent_harness/session/manager.py:169-190`）先查内存缓存，没有则从磁盘 JSONL 文件加载。`get_history()`（同文件:88-112）返回 `last_consolidated` 之后的未合并消息，并自动对齐到合法的 tool_call 边界 — 避免因窗口截断导致 orphan tool result。

有趣的是：`add_message` 在此时就把用户消息添加到会话中了，但 `get_history()` 是在之前调用的。所以 `on_build_context` 看到的是**不含**当前消息的历史。这种"先读后写"的顺序是刻意的设计。

### 1.5 第 2c 步：记忆合并

如果同时开启了 memory 和 sessions，Agent 会在处理消息前触发记忆合并检查（`agent.py:192-193`）：

```python
if self._consolidator is not None and session is not None:
    await self._consolidator.maybe_consolidate_by_tokens(session)
```

`MemoryConsolidator.maybe_consolidate_by_tokens()`（`src/agent_harness/memory/consolidator.py:367-428`）的工作逻辑：

1. 计算预算：`context_window_tokens - max_completion_tokens - 1024`（安全缓冲）
2. 如果预估 token 低于预算 → 跳过
3. 超过预算 → 选择旧消息中的 user-turn 边界作为分块点
4. 最多 5 轮，每轮调用 LLM 对一块消息做摘要
5. LLM 调用 `save_memory` 工具，返回 `history_entry` 和 `memory_update`
6. `history_entry` → 追加到 `HISTORY.md`（可 grep 的日志）
7. `memory_update` → 覆盖 `MEMORY.md`（长期事实记忆）
8. 更新 `session.last_consolidated` 指针，下一次 `get_history()` 跳过已合并的消息

这就是 Day 4 学过的记忆系统在真实管线中的位置和触发条件。值得注意的是，这里的锁是独立的 `WeakValueDictionary`（`consolidator.py:307`），与 Agent 的并发锁互不冲突 — 这意味着会话处理继续时，记忆合并可能在并行进行（尽管合并本身持有 session 的合并锁）。

### 1.6 第 2d 步：上下文构建

Agent 调用 `harness.on_build_context(msg, history)`（`agent.py:196`），触发默认回调（`src/agent_harness/harness.py:397-410`）：

```python
async def _default_build_context(self, msg, history):
    system = await self.context.build_system_prompt()
    return self.context.build_messages(system, history, msg.content, ...)
```

**第一步**：`build_system_prompt()`（`src/agent_harness/context/base.py:46-56`）遍历所有已注册的 `SectionProvider`，按 `priority` 升序排列，逐个调用 `get_section()`：

- `EnvironmentSection`（priority=5）：操作系统、Shell、Python 版本、当前时间、Git 分支
- `IdentitySection`（priority=10）：Agent 身份定义
- `AgentsMDSection`（priority=20）：项目 AGENTS.md 指令
- `SkillsSection`（priority=30）：已注册的技能列表
- `MemorySection`（priority=40）：从 MEMORY.md 加载的长期记忆

各段用 `\n\n---\n\n` 连接，形成完整的 system prompt。

**第二步**：`build_messages()`（同文件:58-74）组装最终的 LLM 消息数组：

```python
[
    {"role": "system", "content": system_prompt},
    *history,              # 之前会话的历史（已跳过已合并的旧消息）
    {"role": "user", "content": "Current time: ...\nChannel: cli | Chat ID: direct\n\n帮我读 README.md"},
]
```

注意 `_build_runtime_context()`（同文件:77-83）在用户消息前注入了当前时间和会话标识。每个 SectionProvider 可以独立扩展，这正是 Day 4 强调的「可插拔管线」设计。

### 1.7 第 2e 步：ReAct 循环

这是全系统的核心 — AgentLoop 的 `run_react_loop()`（`src/agent_harness/loop/agent.py:136-273`）。

**Loop 1 — 第一次 LLM 调用**（`loop/agent.py:159-177`）：

```python
response = await self.provider.chat_with_retry(
    messages=messages,
    tools=tool_defs,
    model=self.model,
)
```

使用 AnthropicProvider（`src/agent_harness/providers/anthropic_provider.py`）调用 Anthropic SDK。`chat_with_retry` 是 `LLMProvider` 的模板方法（`src/agent_harness/providers/base.py:397-445`），内置最多 3 次重试，对 429/5xx/timeout 等瞬时错误做指数退避。

LLM 返回 `LLMResponse(content=None, tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "README.md"})])`。

**工具执行**（`loop/agent.py:200-238`）：

工具调用的决策路径经过两层代码。

首先 Agent 的 `execute_tool` 回调（`agent.py:90-110`）被调用：

```python
tool = harness.tools.get(tool_name)          # agent.py:91 — 从 ToolRegistry 获取工具实例
parsed = tool.input_model.model_validate(args_dict)  # agent.py:96 — Pydantic 参数校验
permission = await harness.on_tool_check(tool_name, tool, parsed)  # agent.py:100 — 权限检查
result = await tool.execute(parsed, context) # agent.py:106 — 真实执行
```

**权限检查**委派给 `PermissionChecker.evaluate()`（`src/agent_harness/permissions/checker.py:75-146`）。因为 `read_file` 是只读操作，走第三层决策后返回 `allowed=True`（`checker.py:131-132`）：

```python
if is_read_only:
    return PermissionDecision(allowed=True, reason="read-only tools are allowed")
```

**`ReadFileTool.execute()`**（`src/agent_harness/tools/filesystem.py:185-248`）：
1. 路径解析：`_resolve()`（同文件:96-111）检查路径是否在 workspace 内，越界则抛出 `PermissionError`
2. 读取字节：`fp.read_bytes()`
3. Magic bytes 检测：`detect_image_mime()`（同文件:57-66）检查 PNG/JPEG/GIF/WebP 签名
4. 如果是图片 → 返回 Base64 编码的 image block
5. 文本文件 → UTF-8 解码，按 offset/limit 截取行号，返回编号行

同时，ReAct 循环在工具执行前后发出可观测性事件（`loop/agent.py:211,227-231`）：

```python
await self._emit(ToolExecutionStarted(tc.name, tc.arguments))     # 工具开始
await self._emit(ToolExecutionCompleted(tc.name, result, ...))     # 工具完成
```

**Loop 2 — 第二次 LLM 调用**：工具结果以 `{"role": "tool", "tool_call_id": "...", ...}` 格式追加到 messages 列表后，再次调用 LLM。这一次 LLM 看到完整上下文（system + 用户请求 + 自己的工具调用 + 工具结果），生成最终回答。

```python
messages.append(self._build_assistant_msg(response))  # loop/agent.py:256
final_content = response.content                       # loop/agent.py:257
await self._emit(AssistantTurnComplete(final_content, self._last_usage))  # loop/agent.py:258
```

当 LLM 返回纯文本（无 tool_calls）时循环退出，返回 `TurnResult`。

### 1.8 第 2f 步：持久化

ReAct 循环返回后，Agent 保存新消息到会话（`agent.py:206-207`）：

```python
if session is not None:
    self._save_turn(session, result, len(initial_messages))
```

`_save_turn()`（`agent.py:237-269`）：
1. 用 `result.messages[initial_count:]` 提取本轮新增消息
2. 跳过空的 assistant 消息（无 content 也无 tool_calls）
3. 截断超长工具结果 >16K 字符
4. 保留 `tool_calls`、`tool_call_id`、`name` 等额外字段
5. 调用 `SessionManager.save(session)` 写回 JSONL

### 1.9 第 3 步：输出返回

```python
return OutboundMessage(                     # agent.py:213-217
    channel=msg.channel,
    chat_id=msg.chat_id,
    content=result.final_content,
)
```

`OutboundMessage` 传回调用方。如果是通过 `ChannelManager` 路由的（`src/agent_harness/channels/manager.py:134-160`），`_dispatch_outbound` 从 `MessageBus.outbound` 队列消费消息，查找匹配的 `BaseChannel`，调用 `channel.send()`。如果消息包含 `_stream_delta` 元数据，则走 `send_delta()` 实现流式输出。

### 1.10 各子系统如何连接 — 全景总结

| 前 6 天主题 | 在完整旅程中的位置 | 关键文件 |
|---|---|---|
| Day 1 架构总览 | Agent + Harness 分离，process() 入口 | `agent.py`, `harness.py` |
| Day 2 ReAct 循环 | AgentLoop.run_react_loop，LLM 调用 | `loop/agent.py` |
| Day 3 工具系统 | ToolRegistry 查找、Pydantic 校验、权限检查、执行 | `tools/base.py`, `tools/filesystem.py` |
| Day 4 上下文与记忆 | SectionProvider 拼接 system prompt，MemoryConsolidator 压缩 | `context/base.py`, `memory/consolidator.py` |
| Day 5 子代理与钩子 | 在工具层和事件层可插入子代理和 Hook | `coordinator/subagent.py`, `hooks/` |
| Day 6 安全与通道 | PermissionChecker 三层防御、ChannelManager 路由 | `permissions/checker.py`, `channels/manager.py` |

---

## 二、源码导读

以下按管线顺序标注关键代码路径。所有行号基于当前 `main` 分支源码。

### 2.1 入口与并发控制

```text
src/agent_harness/agent.py:164      process() 方法定义
src/agent_harness/agent.py:174      per-session Lock 获取
src/agent_harness/agent.py:175      全局 Semaphore 获取
src/agent_harness/agent.py:177      async with lock, gate — 同时持有
```

`src/agent_harness/agent.py:60-63` 展示了这两个并发控制原语的初始化：

```python
self._session_locks: dict[str, asyncio.Lock] = {}
self._concurrency_gate = (
    asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None
)
```

`max_concurrent=0` 时会跳过 Semaphore（`nullcontext`），允许无限并行。

### 2.2 会话加载

```text
src/agent_harness/agent.py:183-184  SessionManager.get_or_create(msg.session_key)
src/agent_harness/agent.py:187      session.get_history() — 获取已合并历史
src/agent_harness/agent.py:188-189  添加当前消息并持久化
```

`SessionManager.get_or_create()` 的实现：

```text
src/agent_harness/session/manager.py:169-190  get_or_create() — 缓存优先
src/agent_harness/session/manager.py:192-228  _load() — 从 JSONL 反序列化
src/agent_harness/session/manager.py:230-247  save() — 写回 JSONL
src/agent_harness/session/manager.py:88-112   get_history() — 边界对齐
```

JSONL 格式首行是 `_type: "metadata"`，后续每行一条消息。这种设计支持 append-only 写入和按行流式读取。

### 2.3 记忆合并

```text
src/agent_harness/agent.py:192-193  MemoryConsolidator.maybe_consolidate_by_tokens(session)
```

内部实现链：

```text
src/agent_harness/memory/consolidator.py:367-428  maybe_consolidate_by_tokens()
src/agent_harness/memory/consolidator.py:317-337  pick_consolidation_boundary() — 选 user-turn 边界
src/agent_harness/memory/consolidator.py:339-356  estimate_session_prompt_tokens() — 预估 token
src/agent_harness/memory/consolidator.py:124-256  MemoryStore.consolidate() — LLM 摘要调用
src/agent_harness/memory/consolidator.py:137-141  MemoryStore.read_long_term() — 读 MEMORY.md
src/agent_harness/memory/consolidator.py:147-150  MemoryStore.append_history() — 写 HISTORY.md
```

预算计算逻辑（`consolidator.py:378`）：

```python
budget = self.context_window_tokens - self.max_completion_tokens - self._SAFETY_BUFFER
target = budget // 2  # 目标：压缩到预算的一半
```

### 2.4 上下文构建

```text
src/agent_harness/agent.py:196      initial_messages = await self.harness.on_build_context(msg, history)
```

默认回调的实现：

```text
src/agent_harness/harness.py:397-410  _default_build_context()
src/agent_harness/harness.py:403      context.build_system_prompt() — 组装 system prompt
src/agent_harness/harness.py:404      context.build_messages() — 组装完整消息列
```

ContextBuilder 内部：

```text
src/agent_harness/context/base.py:46-56    build_system_prompt() — 按 priority 排序各 section
src/agent_harness/context/base.py:58-74    build_messages() — 构建 [system, ...history, user]
src/agent_harness/context/base.py:77-83    _build_runtime_context() — 时间+频道信息
```

SectionProvider 实现类：

```text
src/agent_harness/prompts/sections.py:13-39   EnvironmentSection  (priority=5)
src/agent_harness/prompts/sections.py:119-132 IdentitySection     (priority=10)
src/agent_harness/prompts/sections.py:42-53   AgentsMDSection     (priority=20)
src/agent_harness/prompts/sections.py:81-116  SkillsSection       (priority=30)
src/agent_harness/prompts/sections.py:56-78   MemorySection       (priority=40)
```

### 2.5 ReAct 循环

```text
src/agent_harness/agent.py:199-203  loop.run_react_loop(initial_messages, channel=..., chat_id=...)
src/agent_harness/loop/agent.py:136-273  run_react_loop() — 全函数可见
```

循环体中的关键子步骤：

**LLM 调用**：
```text
src/agent_harness/loop/agent.py:173-177  provider.chat_with_retry() — 首次 LLM 调用
src/agent_harness/providers/base.py:397-445  chat_with_retry() — 重试包装器
src/agent_harness/providers/anthropic_provider.py  — Anthropic SDK 实现
```

**工具执行（经 Agent 回调）**：
```text
src/agent_harness/agent.py:91       tool = harness.tools.get(tool_name) — 查注册表
src/agent_harness/tools/base.py:89-90   ToolRegistry.get()
src/agent_harness/agent.py:96      parsed = tool.input_model.model_validate(args_dict)
src/agent_harness/agent.py:100     permission = await harness.on_tool_check(tool_name, tool, parsed)
```

**权限检查**：
```text
src/agent_harness/permissions/checker.py:75-146  PermissionChecker.evaluate()
src/agent_harness/permissions/checker.py:131-132  只读放行
```

**ReadFileTool 执行**：
```text
src/agent_harness/tools/filesystem.py:185-248  ReadFileTool.execute()
src/agent_harness/tools/filesystem.py:96-111   _resolve_path() — 路径安全解析
src/agent_harness/tools/filesystem.py:57-66    detect_image_mime() — magic bytes 检测
```

**事件追踪**：
```text
src/agent_harness/loop/agent.py:211     _emit(ToolExecutionStarted(...))
src/agent_harness/loop/agent.py:227-231 _emit(ToolExecutionCompleted(...))
src/agent_harness/loop/agent.py:258     _emit(AssistantTurnComplete(...))
src/agent_harness/observability/events.py:42-55  事件定义
```

**可观测性事件总线**：
```text
src/agent_harness/loop/agent.py:126-130  全局 EventBus 发布
src/agent_harness/observability/bus.py    EventBus 实现
```

**退出条件**：
```text
src/agent_harness/loop/agent.py:241-258  LLM 返回纯文本 → 记录 final_content
src/agent_harness/loop/agent.py:261-266  max_iterations 耗尽 → 错误提示
src/agent_harness/loop/agent.py:268-273  返回 TurnResult
```

### 2.6 持久化

```text
src/agent_harness/agent.py:206-207  _save_turn(session, result, len(initial_messages))
src/agent_harness/agent.py:237-269  _save_turn() — 消息提取、截断、保存
src/agent_harness/agent.py:258-259  工具结果 >16K → 截断
src/agent_harness/agent.py:267-268  session.add_message(role, content, **extra)
src/agent_harness/agent.py:269      sessions.save(session)
```

### 2.7 输出返回

```text
src/agent_harness/agent.py:210-217  if result.final_content is None → 返回 None；否则 OutboundMessage
src/agent_harness/bus/events.py:44-60   OutboundMessage 定义
src/agent_harness/channels/manager.py:134-160  _dispatch_outbound() — 分发到对应 Channel
src/agent_harness/channels/manager.py:162-168  _send_once() — 流式或普通发送
src/agent_harness/channels/base.py             BaseChannel — 各通道基类
```

### 2.8 错误处理

如果管线中任何环节抛出异常（`CancelledError` 除外），`Agent.process()` 的异常处理器会捕获并调用 `harness.on_error()`：

```text
src/agent_harness/agent.py:222-231  except 块 → on_error() → 返回用户友好的 OutboundMessage
src/agent_harness/harness.py:412-415  _default_on_error() — 日志 + 通用错误消息
```

---

## 三、动手练习：给整个管线加端到端性能计时

你已经读完了全部源码。现在来做一个真实的改动 — 为 `Agent.process()` 添加一个 `PerformanceMonitor`，记录每个阶段的耗时，输出一份性能报告。

### 3.1 要求

在 `src/agent_harness/agent.py` 中创建一个包裹类（或修改现有代码），要求在以下至少 **6 个计时点** 打桩：

1. **会话加载** — `SessionManager.get_or_create` 到 `save` 完成
2. **记忆合并** — `maybe_consolidate_by_tokens` 的总耗时
3. **上下文构建** — `on_build_context` 耗时
4. **每次 LLM 调用** — ReAct 循环中每次 `chat_with_retry` 的耗时
5. **每次工具执行** — 每个工具从开始到完成的耗时
6. **持久化** — `_save_turn` 耗时

### 3.2 输出格式

当消息处理完成后，打印（`logger.info` 级别）性能报告：

```text
[Performance Report] session=cli:direct
  session_load:    12.3 ms
  memory_consolid:  0.0 ms  (skipped — no consolidator)
  context_build:    5.7 ms
  llm_calls:        2
    [1] chat:      1234.5 ms  (tools: read_file)
    [2] chat:       987.6 ms  (tools: none)
  tool_executions:  1
    [1] read_file:  15.2 ms
  turn_save:        3.1 ms
  ─────────────────────────
  total:          2258.4 ms
```

### 3.3 实现提示

- 最简单的做法：在 `process()` 方法中用 `time.monotonic()` 记录时间戳，在关键步骤前后插桩
- 对于 LLM 调用耗时，可以通过在 `_build_loop` 中的 `execute_tool` 回调里或在 `run_react_loop` 的结果中提取
- 如果不想修改现有代码，可以创建一个 `PerformanceMonitor` 上下文管理器，包裹整个 `process()` 调用
- 注意 `_consolidator` 可能为 `None`，需跳过并显示 "skipped"

### 3.4 测试

创建一个临时脚本测试你的实现：

```python
import asyncio
from pathlib import Path
from agent_harness import Agent, Harness, load_config
from agent_harness.bus.events import InboundMessage

config = load_config()  # 从默认配置加载
harness = Harness.from_config(config)
agent = Agent(harness, model=config.agent.model)

msg = InboundMessage(
    channel="cli",
    sender_id="test",
    chat_id="direct",
    content="列出当前目录的文件",
)

result = await agent.process(msg)
print(result.content)
```

运行并观察性能报告。

### 3.5 验证标准

- 至少 6 个计时点（建议 7 个 — 包括总计）
- skipped 的环节明确标注
- 多次 LLM 调用按序号编号
- 输出可读，对齐格式
- 不破坏任何现有功能（特别是 `CancelledError` 传播和错误路径）

---

**恭喜！** 你完成了 agent-harness 的 7 天系统学习。从 Day 1 的架构总览到 Day 7 的完整管线贯通，你已经掌握了这个 ~13,000 行 Agent 框架的每个核心子系统。

你现在可以：
- 在脑中回放一条消息从入口到出口的完整旅程
- 在源码中定位每个环节的精确位置
- 在任意环节注入横切逻辑（计时、监控、钩子）
- 自信地 fork 和定制这个项目
