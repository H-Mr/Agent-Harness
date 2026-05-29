# How to Create a Custom Tool

## Goal

Create a custom tool that extends the agent's capabilities beyond the 15 built-in tools.

## Prerequisites

- Working llm-harness installation
- Understanding of Pydantic BaseModel for input schemas

## Step by Step

### 1. Define the Input Model

Create a Pydantic model for your tool's arguments. Use `Field(description=...)` for each field -- the LLM uses these descriptions to decide how to call your tool.

```python
from pydantic import BaseModel, Field

class TimezoneInput(BaseModel):
    city: str = Field(description="City name, e.g. 'Beijing' or 'New York'")
```

### 2. Subclass BaseTool

Override `name`, `description`, and `input_model` as ClassVar. Implement `execute()` and `is_read_only()`.

```python
from typing import ClassVar
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult

class TimezoneTool(BaseTool):
    name: ClassVar[str] = "timezone"
    description: ClassVar[str] = "Get the current time in a given city."
    input_model: ClassVar[type[BaseModel]] = TimezoneInput

    async def execute(self, args: TimezoneInput, ctx: ToolExecutionContext) -> ToolResult:
        # Your logic here
        return ToolResult(output=f"The time in {args.city} is 14:30 UTC")

    @staticmethod
    def is_read_only(args: TimezoneInput) -> bool:
        return True
```

### 3. Register the Tool

```python
from llm_harness.core.tools.base import ToolRegistry

tools = ToolRegistry()
tools.register(TimezoneTool())
```

Or register via ToolFactory:

```python
from llm_harness.core.tools.factory import ToolFactory

factory = ToolFactory(sandbox=sandbox)
factory.register("timezone", lambda: TimezoneTool())
```

### 4. Use with an Agent

```python
harness = Harness(provider=provider, model="deepseek-chat", tools=tools, sandbox=sandbox)
agent = harness.create_agent()
result = await agent.process(msg, session=session, cwd=cwd)
```

## Complete Example

```python
import os, asyncio
from pathlib import Path
from typing import ClassVar
from pydantic import BaseModel, Field
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult, ToolRegistry
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage

class WeatherInput(BaseModel):
    city: str = Field(description="City name in English")

class WeatherTool(BaseTool):
    name: ClassVar[str] = "weather"
    description: ClassVar[str] = "Get current weather for a city (mock)."
    input_model: ClassVar[type[BaseModel]] = WeatherInput

    async def execute(self, args: WeatherInput, ctx: ToolExecutionContext) -> ToolResult:
        weather = {"Beijing": "Sunny 25C", "New York": "Cloudy 18C", "London": "Rainy 15C"}
        result = weather.get(args.city, f"No data for {args.city}")
        return ToolResult(output=result)

    @staticmethod
    def is_read_only(args: WeatherInput) -> bool:
        return True

async def main():
    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"], api_base="https://api.deepseek.com")
    sandbox = SRTSandboxBackend(Path("./workspace"))
    tools = ToolRegistry()
    tools.register(WeatherTool())

    harness = Harness(provider=provider, model="deepseek-chat", tools=tools, sandbox=sandbox)
    agent = harness.create_agent()

    msg = InboundMessage("cli", "user", "c1", "What's the weather in Beijing?")
    result = await agent.process(msg, session=Session(key="demo:test"), cwd=Path("./workspace"))
    print(result.final_content)

asyncio.run(main())
```

## Testing

```python
import pytest
from pathlib import Path
from llm_harness.core.tools.base import ToolExecutionContext

@pytest.mark.asyncio
async def test_weather_tool():
    tool = WeatherTool()
    ctx = ToolExecutionContext(cwd=Path("/workspace"))
    result = await tool.execute(WeatherInput(city="Beijing"), ctx)
    assert "Sunny 25C" in result.output
    assert not result.is_error
```
