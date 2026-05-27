# Agent — 可运行的 Agent

提供 `process(msg)` 接口用于执行消息并返回回复。

## 基本用法

```python
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage

agent = Agent(
    Harness(
        provider=OpenAICompatProvider(api_key="sk-...", api_base="..."),
        tools=["read_file", "write_file", "exec"],
    ),
    model="gpt-4o",
)
result = await agent.process(
    InboundMessage(channel="cli", sender_id="user", chat_id="c1", content="你好")
)
```

## 流式输出与进度回调

`Agent` 支持五个可选回调参数，透传给底层 `AgentLoop`：

```python
import asyncio

async def on_stream(delta: str):
    """LLM 每输出一段文本就触发一次。"""
    print(delta, end="", flush=True)

async def on_progress(hint: str, is_start: bool):
    """工具调用开始时触发，显示可读的提示。"""
    print(f"\n-- 工具调用: {hint} --")

async def on_stream_end(resuming: bool):
    """一段流式输出结束时触发，resuming=True 表示后面还有工具调用。"""
    if resuming:
        print("\n(等待工具执行...)")

async def on_event(event):
    """接收结构化可观测事件。"""
    match type(event).__name__:
        case "ToolExecutionStarted":
            print(f"[EVENT] 开始执行: {event.tool_name}")
        case "ToolExecutionCompleted":
            print(f"[EVENT] 执行完成: {event.tool_name}")

agent = Agent(
    harness,
    model="gpt-4o",
    on_stream=on_stream,
    on_progress=on_progress,
    on_stream_end=on_stream_end,
    on_event=on_event,
)
```

未传入的回调默认为 `None`，循环会自动回退到非流式模式。

## API 参考

::: agent_harness.agent.Agent
    options:
      show_root_heading: true
      heading_level: 2
