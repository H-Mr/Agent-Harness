# llm-harness

Pure async, dependency-injected Agent development framework.

## What is llm-harness?

llm-harness is an **Agent engine kernel** — it gives you `Harness` (the assembler),
`Agent` (the stateless engine), and `AgentLoop` (the ReAct skeleton). You bring
your own LLM provider, tools, sandbox, memory backend, and session storage.

**Not** a LangChain wrapper. **Not** a Dify competitor. A focused, ~7,000-line
library that does one thing: run ReAct agent loops with pluggable everything.

## Quick Look

```python
from llm_harness import Harness, Agent, Session, ToolRegistry, Config, load_config

config = load_config("harness.yaml")
harness = Harness(provider=..., model="claude-sonnet-4-6", tools=..., sandbox=...)
agent = harness.create_agent()

session = Session(key="user:chat-1")
result = await agent.process(msg, session=session, cwd=Path("/workspace"))
print(result.final_content)
```

## Where to Start

- **New here?** → [7-Day Mastery Path](tutorials/7-day-mastery.md)
- **Just want to run?** → [Quickstart](tutorials/quickstart.md)
- **Solving a specific problem?** → [How-To Guides](how-to/custom-tool.md)
- **Need API details?** → [Reference](reference/harness.md)
- **Curious about the design?** → [Explanation](explanation/architecture.md)
