# Agent

`Agent` 是 **纯无状态引擎** — 零内部状态，零副作用。调用者在每次调用时提供 `Session`、`cwd` 和可选的 `account`。

源码位置：`llm_harness.core.agent`

## 构造函数

```python
Agent(
    loop: AgentLoop,
    consolidator: MemoryConsolidator | None = None,
    emitter: EventEmitter | None = None,
)
```

| 参数 | 类型 | 说明 |
|-----------|------|-------------|
| `loop` | `AgentLoop` | 已配置的 ReAct 循环 |
| `consolidator` | `MemoryConsolidator` 或 `None` | 记忆整合引擎 |
| `emitter` | `EventEmitter` 或 `None` | 可观测性事件发射器 |

## 方法

### process(msg, *, session, cwd, account="") → TurnResult

```python
async def process(
    self,
    msg: InboundMessage,
    *,
    session: Session,
    cwd: Path,
    account: str = "",
) -> TurnResult
```

运行一个完整的回合：

1. 发射 `SessionOpened` 事件（如果配置了 emitter）
2. 调用 `session.get_history()` 获取消息历史
3. 调用 `session.add_message("user", msg.content)`
4. 运行 `MemoryConsolidator.maybe_consolidate()`（如果配置了）
5. 运行 `AgentLoop.run(msg, history, cwd=cwd)`
6. 调用 `_save_turn(session, result)` 持久化新消息
7. 发射 `SessionClosed` 事件（如果配置了 emitter）
8. 返回 `TurnResult`

| 参数 | 类型 | 说明 |
|-----------|------|-------------|
| `msg` | `InboundMessage` | 传入的用户消息 |
| `session` | `Session` | 此对话的会话 |
| `cwd` | `Path` | 文件工具的工作目录 |
| `account` | `str` | 租户隔离的账户标识符 |

### close()

```python
async def close(self) -> None
```

释放资源。当前为空操作（无状态引擎）。为将来与可能持有资源的子组件兼容而添加。

## 内部方法

### _save_turn(session, result)

遍历 `result.messages[result.new_messages_start:]` 并将 assistant 和 tool 消息持久化到 `session`。跳过：
- 非 `assistant` 或 `tool` 角色的消息
- 没有 `tool_calls` 的空 assistant 消息

## 并发

Agent 是无状态的，从多个任务调用是安全的，前提是：
- 每次调用使用不同的 `Session` 实例
- 或者调用者为共享的 Session 提供外部同步

## 用法

```python
agent = harness.create_agent()
session = Session(key="user:chat-1")

msg = InboundMessage(channel="cli", sender_id="alice", chat_id="c1",
                     content="What is the capital of France?")
result = await agent.process(msg, session=session, cwd=Path("/workspace"))
print(result.final_content)
# → "The capital of France is Paris."
```
