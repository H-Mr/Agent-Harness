# 如何创建自定义工具

## 目标

创建一个自定义工具，扩展 agent 在内置 15 个工具之外的能力。

## 前置条件

- 可用的 llm-harness 安装
- 了解 Pydantic BaseModel 用于输入 schema

## 分步指南

### 1. 定义输入模型

为你的工具参数创建一个 Pydantic 模型。使用 `Field(description=...)` 描述每个字段——LLM 会根据这些描述来决定如何调用你的工具。

```python
from pydantic import BaseModel, Field

class TimezoneInput(BaseModel):
    city: str = Field(description="City name, e.g. 'Beijing' or 'New York'")
```

### 2. 继承 BaseTool

将 `name`、`description` 和 `input_model` 设为 ClassVar。实现 `execute()` 和 `is_read_only()`。

```python
from typing import ClassVar
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult

class TimezoneTool(BaseTool):
    name: ClassVar[str] = "timezone"
    description: ClassVar[str] = "Get the current time in a given city."
    input_model: ClassVar[type[BaseModel]] = TimezoneInput

    async def execute(self, args: TimezoneInput, ctx: ToolExecutionContext) -> ToolResult:
        # 在这里编写你的逻辑
        return ToolResult(output=f"The time in {args.city} is 14:30 UTC")

    @staticmethod
    def is_read_only(args: TimezoneInput) -> bool:
        return True
```

### 3. 注册工具

```python
from llm_harness.core.tools.base import ToolRegistry

tools = ToolRegistry()
tools.register(TimezoneTool())
```

或者通过 ToolFactory 注册：

```python
from llm_harness.core.tools.factory import ToolFactory

factory = ToolFactory(sandbox=sandbox)
factory.register("timezone", lambda: TimezoneTool())
```

### 4. 与 Agent 一起使用

```python
harness = Harness(provider=provider, model="deepseek-chat", tools=tools, sandbox=sandbox)
agent = harness.create_agent()
result = await agent.process(msg, session=session, cwd=cwd)
```

## 完整示例

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

## 测试

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
