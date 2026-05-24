# 教程：编写自定义工具

学会了基本用法后，你可能会觉得内置的 28 个工具不够用 —— 这很正常。llm-harness 的设计目标之一就是**让扩展工具变得极其简单**。

本教程将带你从零编写两个自定义工具，并注册到 Harness 中。

---

## BaseTool ABC

所有工具都继承自 `BaseTool` 抽象基类，只需要实现三个类变量和一个方法：

```python
from pydantic import BaseModel, Field
from agent_harness import BaseTool, ToolExecutionContext, ToolResult

class MyTool(BaseTool):
    name: ClassVar[str] = "my_tool"              # 工具名称（LLM 通过这个名字调用）
    description: ClassVar[str] = "我的自定义工具"  # 工具描述（LLM 理解用途）
    input_model: ClassVar[type[BaseModel]] = ...  # Pydantic 输入模型

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """执行工具逻辑，返回 ToolResult"""
        ...
```

| 成员 | 类型 | 说明 |
|------|------|------|
| `name` | `ClassVar[str]` | 工具的唯一标识符。LLM 通过这个名字来调用它。 |
| `description` | `ClassVar[str]` | 描述工具的用途。**写好描述很重要** — LLM 靠它决定何时调用。 |
| `input_model` | `ClassVar[type[BaseModel]]` | Pydantic 模型，定义工具的参数结构。LLM 据此生成参数。 |
| `execute()` | `async def` | 工具的核心逻辑。接收校验后的参数和执行上下文，返回 `ToolResult`。 |
| `is_read_only()` | `def`（可选） | 标记本次调用是否只读。权限系统据此决定是否需要审批。 |

!!! tip "为什么用 ClassVar？"
    `name`、`description`、`input_model` 是**类变量**（`ClassVar`），因为它们在所有实例中是一样的。`execute()` 是实例方法，可以有状态。

---

## 示例 1：天气查询工具

我们从最简单的开始 —— 一个调用公共 API 查询天气的工具。

### 1. 定义输入模型

```python
from pydantic import BaseModel, Field

class WeatherInput(BaseModel):
    city: str = Field(description="城市名称，如 北京、上海、Tokyo")
    days: int = Field(default=1, ge=1, le=7, description="预报天数（1-7）")
```

!!! note "Field 的 description 很重要"
    `Field(description=...)` 中的描述会出现在给 LLM 的 Schema 中。描述越清晰，LLM 生成正确参数的概率越高。

### 2. 实现工具类

```python title="weather_tool.py"
from typing import Any, ClassVar
import httpx
from pydantic import BaseModel, Field
from agent_harness import BaseTool, ToolExecutionContext, ToolResult


class WeatherInput(BaseModel):
    city: str = Field(description="城市名称，如 北京、上海、Tokyo")
    days: int = Field(default=1, ge=1, le=7, description="预报天数（1-7）")


class WeatherTool(BaseTool):
    name: ClassVar[str] = "weather"
    description: ClassVar[str] = "查询指定城市的天气预报"
    input_model: ClassVar[type[BaseModel]] = WeatherInput

    async def execute(self, arguments: WeatherInput, context: ToolExecutionContext) -> ToolResult:
        try:
            # 使用 wttr.in 的公共天气 API
            url = f"https://wttr.in/{arguments.city}?format=%C+%t+%w+%h&lang=zh"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
                return ToolResult(
                    output=f"{arguments.city} 天气：{resp.text.strip()}",
                )
        except Exception as e:
            return ToolResult(
                output=f"查询天气失败：{e}",
                is_error=True,
            )

    def is_read_only(self, arguments: WeatherInput) -> bool:
        return True  # 天气查询是只读操作，不需要审批
```

### 3. 注册工具到 Harness

```python title="main.py"
import asyncio
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage
from agent_harness.prompts.sections import IdentitySection
from agent_harness.tools.base import ToolRegistry
from weather_tool import WeatherTool

async def main():
    # 创建工具注册表，注册自定义工具
    registry = ToolRegistry()
    registry.register(WeatherTool())

    # 在 Harness 中传入已注册的工具
    harness = Harness(
        provider=OpenAICompatProvider(api_key="sk-...", api_base="https://api.openai.com/v1"),
        tools=registry,  # 传入 ToolRegistry 而非 list[str]
        context=[IdentitySection("你是一个助理，可以用 weather 工具查询天气。")],
    )

    agent = Agent(harness, model="gpt-4o")

    result = await agent.process(
        InboundMessage("cli", "user", "c1", "北京今天天气怎么样？")
    )
    print(result.content)

asyncio.run(main())
```

!!! tip "三种传入 tools 的方式"
    - `tools=["read_file", "exec"]` — 字符串列表，只使用内置工具
    - `tools=ToolRegistry` — 完全控制，可混合内置 + 自定义工具
    - `tools=ToolsConfig` — 配置文件驱动（详见[配置文件驱动](config-driven.md)）

---

## 示例 2：数据库查询工具

实际业务场景中，让 Agent 直接查询数据库非常有用。我们来实现一个只读的 SQL 查询工具。

```python title="db_tool.py"
from typing import Any, ClassVar
import sqlite3
from pathlib import Path
from pydantic import BaseModel, Field
from agent_harness import BaseTool, ToolExecutionContext, ToolResult


class DBQueryInput(BaseModel):
    sql: str = Field(description="要执行的 SQL SELECT 查询语句")
    max_rows: int = Field(default=20, ge=1, le=100, description="最大返回行数")


class DBQueryTool(BaseTool):
    name: ClassVar[str] = "db_query"
    description: ClassVar[str] = "对 SQLite 数据库执行 SELECT 查询，返回结果集"
    input_model: ClassVar[type[BaseModel]] = DBQueryInput

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()

    async def execute(self, arguments: DBQueryInput, context: ToolExecutionContext) -> ToolResult:
        # 安全检查：只允许 SELECT
        sql_stripped = arguments.sql.strip().lower()
        if not sql_stripped.startswith("select"):
            return ToolResult(
                output="错误：只允许执行 SELECT 查询",
                is_error=True,
            )

        try:
            # SQLite 查询是 IO 操作，用 asyncio 的线程池执行器避免阻塞
            import asyncio
            loop = asyncio.get_running_loop()

            def _query():
                conn = sqlite3.connect(str(self.db_path))
                try:
                    cursor = conn.execute(arguments.sql)
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchmany(arguments.max_rows)
                    return columns, rows
                finally:
                    conn.close()

            columns, rows = await loop.run_in_executor(None, _query)

            # 格式化成表格文本
            output_lines = [", ".join(columns)]
            output_lines.extend(", ".join(str(cell) for cell in row) for row in rows)
            output_lines.append(f"（共返回 {len(rows)} 行）")

            return ToolResult(output="\n".join(output_lines))

        except Exception as e:
            return ToolResult(output=f"查询失败：{e}", is_error=True)

    def is_read_only(self, arguments: DBQueryInput) -> bool:
        # SQL 已经只允许 SELECT，但显式标记只读让权限系统跳过审批
        return True
```

```python title="main_db.py"
import asyncio
from agent_harness import Agent, Harness, OpenAICompatProvider
from agent_harness.bus.events import InboundMessage
from agent_harness.prompts.sections import IdentitySection
from agent_harness.tools.base import ToolRegistry
from weather_tool import WeatherTool
from db_tool import DBQueryTool

async def main():
    registry = ToolRegistry()
    registry.register(WeatherTool())
    registry.register(DBQueryTool(db_path="./my_data.db"))

    harness = Harness(
        provider=OpenAICompatProvider(api_key="sk-...", api_base="https://api.openai.com/v1"),
        tools=registry,
        context=[IdentitySection("你是一个助理，可以查询天气和数据库。")],
    )

    agent = Agent(harness, model="gpt-4o")

    result = await agent.process(
        InboundMessage("cli", "user", "c1", "查询 users 表中前 5 条记录")
    )
    print(result.content)

asyncio.run(main())
```

!!! warning "生产环境中注意 SQL 注入"
    本例仅为演示工具编写方法。生产环境中应对 SQL 做更严格的校验，或使用参数化查询接口。

---

## 测试工具（使用 MockProvider）

不想浪费 API 调用？可以用 `MockProvider` 来测试工具的逻辑：

```python title="test_weather_tool.py"
import pytest
from agent_harness import ToolRegistry, ToolExecutionContext
from agent_harness.providers.base import LLMProvider, LLMResponse, GenerationSettings
from agent_harness.loop.agent import AgentLoop, LoopCallbacks
from agent_harness.tools.base import ToolRegistry
from pathlib import Path
from weather_tool import WeatherTool, WeatherInput

@pytest.mark.asyncio
async def test_weather_tool_direct():
    """直接测试工具执行"""
    tool = WeatherTool()
    args = WeatherInput(city="Beijing", days=1)
    context = ToolExecutionContext(cwd=Path("/tmp"))

    result = await tool.execute(args, context)
    assert not result.is_error
    assert "Beijing" in result.output
    assert "天气" in result.output


@pytest.mark.asyncio
async def test_weather_tool_via_loop():
    """通过 AgentLoop 测试工具调用流程"""
    registry = ToolRegistry()
    registry.register(WeatherTool())

    # 模拟 LLM 返回 tool_use
    class MockProvider(LLMProvider):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        async def chat(self, messages, tools, settings=None):
            self.call_count += 1
            if self.call_count == 1:
                # 第一次调用：返回工具调用请求
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(
                        id="call_1",
                        name="weather",
                        arguments={"city": "Beijing", "days": 1},
                    )]
                )
            else:
                # 第二次调用：返回最终回复
                return LLMResponse(content="北京的天气是晴天，20°C。")

        def get_default_model(self) -> str:
            return "mock-model"

    from agent_harness.providers.base import ToolCallRequest
    from agent_harness.tools.base import ToolExecutionContext

    async def execute_tool(name, args):
        tool = registry.get(name)
        assert tool is not None
        parsed = tool.input_model.model_validate(args)
        ctx = ToolExecutionContext(cwd=Path("/tmp"))
        result = await tool.execute(parsed, ctx)
        return result.output

    loop = AgentLoop(
        provider=MockProvider(),
        callbacks=LoopCallbacks(
            build_messages=lambda *a, **kw: [{"role": "user", "content": "天气"}],
            execute_tool=execute_tool,
            get_tool_definitions=lambda: registry.to_api_schema("openai"),
        ),
        model="mock-model",
    )

    result = await loop.run_react_loop([{"role": "user", "content": "北京天气如何？"}])
    assert result.final_content is not None
    assert "北京" in result.final_content
```

!!! tip "MockProvider 的价值"
    用 MockProvider 测试工具可以在**不调用真实 LLM** 的情况下验证：
    - 工具的参数校验是否正确
    - 工具的逻辑是否正确
    - 工具调用 → 结果返回 → LLM 总结 的完整流程

---

## 最佳实践

### 1. 正确设置 `is_read_only()`

```python
def is_read_only(self, arguments: WeatherInput) -> bool:
    return True   # 只读操作无需用户审批
```

在 `"default"` 权限模式下，写操作会触发用户确认。正确标记只读可以让用户体验更流畅。

### 2. 错误处理

总是捕获异常，返回有意义的错误信息：

```python
async def execute(self, arguments, context) -> ToolResult:
    try:
        # 安全的操作
        ...
    except FileNotFoundError:
        return ToolResult(output="文件不存在", is_error=True)
    except PermissionError:
        return ToolResult(output="没有权限访问该文件", is_error=True)
    except Exception as e:
        return ToolResult(output=f"操作失败：{e}", is_error=True)
```

### 3. 日志

使用内置的 logger 记录工具执行情况：

```python
import logging
logger = logging.getLogger(__name__)

async def execute(self, arguments, context) -> ToolResult:
    logger.info("Executing my_tool with city=%s", arguments.city)
    ...
```

### 4. 保持 execute 异步

`execute()` 是异步方法。对于同步操作（如 SQLite 查询），用 `run_in_executor` 避免阻塞事件循环：

```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, sync_function)
```

### 5. 输入校验

利用 Pydantic 的校验能力：

```python
class MyInput(BaseModel):
    email: str = Field(description="邮箱地址")
    count: int = Field(default=10, ge=1, le=1000, description="数量")
    mode: Literal["fast", "slow"] = Field(default="fast", description="模式")
```

Pydantic 会自动校验类型、范围、枚举值，无效参数不会进入 `execute()`。

---

## 总结

编写一个 llm-harness 工具的流程：

1. 定义 Pydantic `input_model`（参数结构）
2. 继承 `BaseTool`，设置 `name`/`description`/`input_model`
3. 实现 `execute()` 方法
4. 创建实例并通过 `ToolRegistry` 注入到 `Harness`
5. （可选）覆盖 `is_read_only()` 优化权限体验
6. （推荐）用 `MockProvider` 编写测试

## 下一步

- [配置文件驱动](config-driven.md) — 用 JSON 管理工具和权限
- [工具执行管线](../explanation/pipeline.md) — 理解工具的完整调用链
- [权限系统](../api/permissions.md) — 深入权限配置
