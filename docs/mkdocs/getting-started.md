# Getting Started

## Installation

```bash
pip install llm-harness               # base, 6 core dependencies
pip install llm-harness[anthropic]    # + Claude (Anthropic SDK)
pip install llm-harness[openai]       # + OpenAI SDK
pip install llm-harness[all]          # everything
pip install llm-harness[dev]          # + pytest, ruff
```

Requirements: Python >= 3.10

## Your First Agent

```python
import asyncio
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage
from agent_harness.prompts.sections import IdentitySection

async def main():
    agent = Agent(
        Harness(
            provider=OpenAICompatProvider(
                api_key="sk-...",
                api_base="https://api.openai.com/v1",
            ),
            tools=["read_file", "write_file", "exec"],
            context=[IdentitySection("You are a friendly assistant.")],
        ),
        model="gpt-4",
    )

    result = await agent.process(
        InboundMessage(channel="cli", sender_id="user", chat_id="c1", content="Hello!")
    )
    print(result.content)

asyncio.run(main())
```

## With Sessions and Memory

```python
agent = Agent(
    Harness(
        provider=OpenAICompatProvider(api_key="...", api_base="..."),
        tools=["read_file", "write_file", "exec"],
        memory=MemoryStore("./agent-data/memory"),       # persistent memory
        sessions=SessionManager("./agent-data/sessions"), # conversation history
        context=[IdentitySection("You are a helpful assistant.")],
    ),
    model="gpt-4",
)

# First turn
await agent.process(InboundMessage("cli", "user", "c1", "My name is Alice"))

# Second turn — agent remembers Alice from session history
result = await agent.process(InboundMessage("cli", "user", "c1", "What's my name?"))
print(result.content)  # "Your name is Alice."
```

## Config-Driven Setup

```json title="config.json"
{
  "agent": {
    "model": "deepseek-v4-pro",
    "api_base": "https://api.deepseek.com/v1",
    "api_key": "sk-...",
    "workspace": "~/.my-agent"
  },
  "tools": {
    "enabled": ["web_search", "read_file", "write_file", "exec", "message"]
  },
  "permission": {
    "mode": "default"
  },
  "observability": {
    "track_file": "~/.my-agent/track.jsonl"
  }
}
```

```python
from agent_harness import Agent, Harness, load_config

config = load_config("config.json")
agent = Agent(Harness.from_config(config))
result = await agent.process(InboundMessage("cli", "user", "c1", "Search for AI news"))
```

## Using Different Providers

### Anthropic Claude

```python
from agent_harness.providers.anthropic_provider import AnthropicProvider

agent = Agent(
    Harness(provider=AnthropicProvider(api_key="sk-ant-...")),
    model="claude-sonnet-4-6",
)
```

### Any OpenAI-Compatible API (DeepSeek, Groq, Ollama, vLLM...)

```python
agent = Agent(
    Harness(
        provider=OpenAICompatProvider(
            api_key="...",
            api_base="https://your-api-endpoint.com/v1",
        ),
    ),
    model="your-model-name",
)
```

25 provider backends are auto-detected from model name and API base URL.

## Custom Tools

```python
from agent_harness import BaseTool, ToolResult
from pydantic import BaseModel, Field

class WeatherInput(BaseModel):
    city: str = Field(description="City name to get weather for")

class WeatherTool(BaseTool):
    name = "get_weather"
    description = "Get current weather for a city"
    input_model = WeatherInput

    async def execute(self, arguments, context):
        # Your weather API call here
        return ToolResult(output=f"Weather in {arguments.city}: Sunny, 22°C")

agent = Agent(Harness(provider=..., tools=[WeatherTool()]), model="gpt-4")
agent.harness.tools.register(WeatherTool())
```

## Low-Level API

If you need full control over every callback:

```python
from agent_harness import AgentLoop, LoopCallbacks, ToolRegistry, AnthropicProvider

tools = ToolRegistry()
tools.register(MyTool())

callbacks = LoopCallbacks(
    build_messages=lambda msg: [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": msg.content},
    ],
    execute_tool=lambda name, args: _exec(tools, name, args),
    get_tool_definitions=lambda: tools.to_api_schema("anthropic"),
)

loop = AgentLoop(AnthropicProvider(api_key="..."), callbacks)
result = await loop.process_direct("Hello!")
```

## Next Steps

- [Core Concepts](core-concepts/overview.md) — Deep dive into Harness, Agent, and the pipeline
- [Architecture](architecture.md) — Full system design
- [API Reference](api/harness.md) — Auto-generated module documentation
- [Examples](examples/index.md) — Real-world use cases
