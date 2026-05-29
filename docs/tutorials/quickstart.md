# Quickstart

Get an Agent running in 5 minutes.

## 1. Install

```bash
pip install llm-harness[openai]
```

## 2. Set your API key

```bash
export LLM_HARNESS_API_KEY=sk-your-key-here
```

## 3. Create the Agent

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
    # 1. Create provider
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )

    # 2. Set up sandbox and tools
    sandbox = SRTSandboxBackend(Path("./workspace"))
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "web_search"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    # 3. Assemble
    harness = Harness(
        provider=provider,
        model="deepseek-chat",
        tools=tools,
        sandbox=sandbox,
    )
    agent = harness.create_agent()

    # 4. Create a session and send a message
    session = Session(key="quickstart:chat1")
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="chat1",
                         content="What is 2+2?")
    result = await agent.process(msg, session=session, cwd=Path("./workspace"))
    print(result.final_content)

asyncio.run(main())
```

## 4. Run it

```bash
python quickstart.py
# → 2+2 equals 4.
```

## Next Steps

- [7-Day Mastery Path](7-day-mastery.md) — structured learning
- [First Agent](first-agent.md) — deeper dive with more tools
