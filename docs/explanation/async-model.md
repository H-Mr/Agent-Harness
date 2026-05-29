# 异步模型

llm-harness 是**完全异步的**。所有 I/O 操作——LLM API 调用、文件读取、子进程执行、HTTP 请求——都使用 `async`/`await`。

## 为什么选择异步？

Agent 工作负载是 **I/O 密集型**的，而非 CPU 密集型。一次 Agent 交互的大部分时间都在等待：LLM API 延迟（1-30 秒）、网络调用（网络搜索、网页抓取）和子进程 I/O。异步让单个进程无需线程开销即可处理多个并发会话。

## 并发模型

llm-harness 是**单线程、协作式**的：

- 一个 `Agent` 实例一次处理一次交互
- 多个会话可以通过创建多个 `Agent` 实例（每个 asyncio Task 一个）并发运行
- `MemoryConsolidator` 使用基于会话的 `asyncio.Lock`，超时时间为 30 秒
- `MessageBus` 使用有界 `asyncio.Queue(maxsize=10_000)`

## 调用者职责

llm-harness 不为你管理并发。由调用者决定：

```python
# 顺序执行 — 简单、安全
for msg in messages:
    await agent.process(msg, session=session, cwd=cwd)

# 并发执行 — 每个 Task 一个 Agent
async def handle_session(session_key):
    agent = harness.create_agent()
    session = await load_session(session_key)
    ...
tasks = [handle_session(k) for k in session_keys]
await asyncio.gather(*tasks)
```

`Agent` 的文档字符串声明："每个线程创建一个 Agent，或者串行使用。"

## 避免常见陷阱

1. **不要在并发的 Agent.process() 调用之间共享同一个 Session。**
   `session.add_message()` 和 `session.remove_before()` 会修改消息列表。没有外部锁的并发访问会破坏历史记录。

2. **不要阻塞事件循环。** 框架的所有 I/O 都是异步的。如果你的自定义工具调用了同步库，请使用 `asyncio.to_thread()` 包装它。

3. **务必设置队列限制。** `MessageBus(maxsize=10_000)` 防止负载下的内存耗尽。默认值已经设置。

4. **务必处理 CancelledError。** 框架通过 `_safe_chat` 和 `_safe_chat_stream` 传播 `asyncio.CancelledError`。LLM 调用期间的任务取消是安全的。

## 超时与重试

| 组件 | 超时 | 重试 |
|-----------|---------|-------|
| LLM API | 每次请求 | 3 次重试，1s/2s/4s 退避 |
| 工具执行 | 每个工具（可配置） | 无 |
| 内存合并锁 | 30 秒 | 跳过本次交互 |
| 子进程执行 | 默认 60 秒 | 无 |
| 网页抓取 | 15 秒（Jina）/ 30 秒（readability） | 回退至 readability |
| MCP 工具调用 | 30 秒 | 无 |
