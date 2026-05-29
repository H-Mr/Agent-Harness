# 你的第一个 Agent

一个完整示例：文件操作、网络搜索和多轮对话。

## 设置

```python
import os, asyncio, tempfile
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path(tempfile.mkdtemp())

    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "exec", "glob", "grep", "web_search"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    harness = Harness(
        provider=provider, model="deepseek-chat",
        tools=tools, sandbox=sandbox,
        system_prompt="You are a coding assistant. Be concise.",
    )
    agent = harness.create_agent()
    session = Session(key="demo:chat1")

    # 第一轮：创建文件
    msg1 = InboundMessage("cli", "alice", "c1",
        'Create a Python file called hello.py that prints "Hello from llm-harness!"')
    r1 = await agent.process(msg1, session=session, cwd=ws)
    print("Turn 1:", r1.final_content[:100])

    # 第二轮：运行它
    msg2 = InboundMessage("cli", "alice", "c1", "Now run hello.py and tell me the output")
    r2 = await agent.process(msg2, session=session, cwd=ws)
    print("Turn 2:", r2.final_content[:100])

    print(f"\nMessages in session: {len(session.messages)}")
    print(f"Tools used: {r2.tools_used}")

asyncio.run(main())
```

## 执行过程

1. `Harness` 将 provider、工具、沙箱和系统提示组装成 Agent
2. 第一轮：Agent 收到消息 → LLM 决定使用 `write_file` → 工具执行 → LLM 确认
3. 第二轮：Agent 收到后续消息 → LLM 使用 `exec` 运行 `python hello.py` → LLM 报告输出
4. Session 累积所有轮次的消息
