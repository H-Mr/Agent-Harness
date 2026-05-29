# Your First Agent

A complete example: file operations, web search, and multi-turn conversation.

## Setup

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

    # Turn 1: create a file
    msg1 = InboundMessage("cli", "alice", "c1",
        'Create a Python file called hello.py that prints "Hello from llm-harness!"')
    r1 = await agent.process(msg1, session=session, cwd=ws)
    print("Turn 1:", r1.final_content[:100])

    # Turn 2: run it
    msg2 = InboundMessage("cli", "alice", "c1", "Now run hello.py and tell me the output")
    r2 = await agent.process(msg2, session=session, cwd=ws)
    print("Turn 2:", r2.final_content[:100])

    print(f"\nMessages in session: {len(session.messages)}")
    print(f"Tools used: {r2.tools_used}")

asyncio.run(main())
```

## What Happens

1. `Harness` assembles the Agent with the provider, tools, sandbox, and system prompt
2. Turn 1: Agent receives the message → LLM decides to use `write_file` → tool executes → LLM confirms
3. Turn 2: Agent receives the follow-up → LLM uses `exec` to run `python hello.py` → LLM reports the output
4. Session accumulates all messages across turns
