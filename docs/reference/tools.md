# Tools

工具系统提供了 LLM 工具调用请求与实际执行之间的接口。

源码位置：`llm_harness.core.tools`

## 核心类

### BaseTool (ABC)

```python
class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult: ...
    def is_read_only(self, arguments: BaseModel) -> bool: ...
    def to_api_schema(self, api_format: str = "anthropic") -> dict[str, Any]: ...
    def to_openai_schema(self) -> dict[str, Any]: ...
```

### ToolRegistry

```python
class ToolRegistry:
    def register(self, tool: BaseTool) -> None: ...
    def unregister(self, name: str) -> None: ...
    def has(self, name: str) -> bool: ...
    def get(self, name: str) -> BaseTool | None: ...
    def list_tools(self) -> list[BaseTool]: ...
    def to_api_schema(self, api_format: str = "anthropic") -> list[dict[str, Any]]: ...
```

### ToolExecutionContext

```python
@dataclass
class ToolExecutionContext:
    cwd: Path                              # 工作目录
    metadata: dict[str, Any]               # session_key、account 等
```

### ToolResult

```python
@dataclass(frozen=True)
class ToolResult:
    output: str                            # 工具输出文本
    is_error: bool = False                 # 执行是否失败
    metadata: dict[str, Any]               # 任意元数据
```

### ToolFactory

```python
class ToolFactory:
    def __init__(self, *, sandbox=None, memory=None, swarm=None, bus=None, skills=None, harness_tool_names=None): ...
    def register(self, name: str, builder: Callable[[], BaseTool | None]) -> None: ...
    def build(self, name: str) -> BaseTool | None: ...
```

## 内置工具

| 工具 | 名称 | 依赖 | 只读 |
|------|------|-------------|-----------|
| ReadFileTool | `read_file` | sandbox | 是 |
| WriteFileTool | `write_file` | sandbox | 否 |
| EditFileTool | `edit_file` | sandbox | 否 |
| ExecTool | `exec` | sandbox | 否 |
| GlobTool | `glob` | sandbox | 是 |
| GrepTool | `grep` | sandbox | 是 |
| WebSearchTool | `web_search` | 无 | 是 |
| WebFetchTool | `web_fetch` | 无 | 是 |
| MemoryReadTool | `memory_read` | memory | 是 |
| MemoryWriteTool | `memory_write` | memory | 否 |
| AgentTool | `agent` | swarm, bus | 否 |
| SendMessageTool | `send_message` | swarm | 否 |
| TaskStopTool | `task_stop` | swarm | 否 |
| SkillTool | `skill` | skills | 是 |
| AskUserQuestionTool | `ask_user_question` | 无 | 否 |

## 实现自定义工具

```python
from pydantic import BaseModel, Field
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult

class GreetInput(BaseModel):
    name: str = Field(description="要问候的名称")

class GreetTool(BaseTool):
    name: ClassVar[str] = "greet"
    description: ClassVar[str] = "按名称问候某人。"
    input_model: ClassVar[type[BaseModel]] = GreetInput

    async def execute(self, args: GreetInput, ctx: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"Hello, {args.name}!")

    @staticmethod
    def is_read_only(args: GreetInput) -> bool:
        return True
```
