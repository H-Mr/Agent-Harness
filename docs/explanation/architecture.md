# 架构

llm-harness 被构建为**三层内核**，配合**协议驱动的适配器**和**调用者管理的状态**。

## 三层结构

```
InboundMessage
      │
      ▼
┌──────────────┐
│    Agent     │  纯无状态引擎 — 调用者提供 Session + cwd
└──────┬───────┘
       │ 委托给 AgentLoop，在此之前：
       │   session.get_history()
       │   MemoryConsolidator.maybe_consolidate()
       │
       ▼
┌──────────────┐
│  AgentLoop   │  ReAct 骨架 — 通过回调注入
└──────┬───────┘
       │ 每次迭代：
       │   build_context → LLM API → 是否有 tool_calls？
       │   是 → 权限检查 → 执行工具 → 追加结果 → 循环
       │   否  → 返回 final_content
       │
       ▼
┌──────────────┐
│   Harness    │  装配器 — 连接组件，返回 Agent
└──────────────┘
  构造函数接收 ALL 依赖项，显式传入
  _build_consolidator()
  _build_system() — 组装系统提示词
  create_agent() — 创建 AgentLoop + Agent
```

### Harness（装配器）

`Harness` 接收所有依赖作为构造函数参数。关键组件（provider、model、tools、sandbox）没有默认值。它负责：

1. 如果提供了 `memory`，则创建 `MemoryConsolidator`
2. 向 `AgentLoop` 注入回调：
   - `on_build_context` — 组装系统消息 + 历史记录 + 用户消息
   - `on_tool_check` — 包装 `PermissionChecker.evaluate()`
   - `on_error` — 记录异常日志
3. 使用配置好的循环创建 `Agent`

### Agent（纯引擎）

`Agent` 是**完全无状态的**。每次对 `process()` 的调用都是自包含的：

```python
async def process(self, msg, *, session, cwd, account="") -> TurnResult:
    history = session.get_history()
    session.add_message("user", msg.content)
    if self._consolidator:
        await self._consolidator.maybe_consolidate(session, account=account)
    result = await self._loop.run(msg, history, cwd=cwd)
    self._save_turn(session, result)
    return result
```

调用者负责会话持久化、并发控制和工作区解析。

### AgentLoop（ReAct 骨架）

`AgentLoop` 实现了标准的 ReAct 模式，通过回调处理所有因部署环境而异的行为：

| 回调 | 用途 |
|----------|---------|
| `on_build_context` | 从用户消息和历史记录组装消息 |
| `on_tool_check` | 工具执行前的权限检查 |
| `on_error` | 错误日志记录 / 报告 |
| `on_event` | 遗留事件发射 |
| `emitter` | 结构化可观测性事件 |

## 数据流：单次交互

```
1. InboundMessage 到达
2. Agent.process():
   a. 发射 SessionOpened
   b. session.get_history() → 过滤后的消息列表
   c. session.add_message("user", msg.content)
   d. MemoryConsolidator.maybe_consolidate() — 如果已配置
   e. AgentLoop.run():
      - on_build_context(msg, history) → 消息列表
      - provider.chat_with_retry(messages, tools) → LLMResponse
      - 如果有 tool_calls：权限检查 → 执行 → 追加结果 → 循环
      - 如果没有 tool_calls：追加助手消息，返回 TurnResult
   f. _save_turn(session, result) — 持久化助手和工具消息
   g. 发射 SessionClosed
3. 返回 TurnResult
```

## 适配器协议

所有后端均使用 Python `Protocol` 类（结构子类型）。调用者实现协议方法时无需继承基类：

| 协议 | 方法数 | 用途 |
|----------|---------|---------|
| `SandboxBackend` | 8 个方法 | 文件 I/O + 子进程执行 |
| `MemoryBackend` | 5 个方法 | 上下文检索 + 合并 |
| `AgentBackend` | 3 个方法 | 子代理生命周期 |
| `SessionBackend` | 3 个方法 | 会话持久化 |
| `ObservabilityBackend` | 3 个方法 | 事件发布-订阅 |
| `SkillLoader` | 1 个方法 | 技能加载 |
