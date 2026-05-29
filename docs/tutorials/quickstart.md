# 快速入门

在 5 分钟内启动一个 Agent。

## 1. 安装

```bash
pip install llm-harness[openai]
```

## 2. 设置 API 密钥

```bash
export LLM_HARNESS_API_KEY=sk-your-key-here
```

## 3. 创建 Agent

```python
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
    # 1. 创建 provider
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )

    # 2. 设置沙箱和工具
    sandbox = SRTSandboxBackend(Path("./workspace"))
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "web_search"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    # 3. 组装
    harness = Harness(
        provider=provider,
        model="deepseek-chat",
        tools=tools,
        sandbox=sandbox,
    )
    agent = harness.create_agent()

    # 4. 创建会话并发送消息
    session = Session(key="quickstart:chat1")
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="chat1",
                         content="What is 2+2?")
    result = await agent.process(msg, session=session, cwd=Path("./workspace"))
    print(result.final_content)

asyncio.run(main())
```

## 4. 运行

```bash
python quickstart.py
# → 2+2 equals 4.
```

## 下一步

- [7 天掌握路线](7-day-mastery.md) —— 系统化学习
- [首个 Agent](first-agent.md) —— 深入探索更多工具
