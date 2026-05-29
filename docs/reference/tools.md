# Tools

The tool system provides the interface between LLM tool-call requests and
actual execution.

Source: `llm_harness.core.tools`

## Core Classes

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
    cwd: Path                              # working directory
    metadata: dict[str, Any]               # session_key, account, etc.
```

### ToolResult

```python
@dataclass(frozen=True)
class ToolResult:
    output: str                            # tool output text
    is_error: bool = False                 # whether execution failed
    metadata: dict[str, Any]               # arbitrary metadata
```

### ToolFactory

```python
class ToolFactory:
    def __init__(self, *, sandbox=None, memory=None, swarm=None, bus=None, skills=None, harness_tool_names=None): ...
    def register(self, name: str, builder: Callable[[], BaseTool | None]) -> None: ...
    def build(self, name: str) -> BaseTool | None: ...
```

## Built-in Tools

| Tool | Name | Dependencies | Read-Only |
|------|------|-------------|-----------|
| ReadFileTool | `read_file` | sandbox | Yes |
| WriteFileTool | `write_file` | sandbox | No |
| EditFileTool | `edit_file` | sandbox | No |
| ExecTool | `exec` | sandbox | No |
| GlobTool | `glob` | sandbox | Yes |
| GrepTool | `grep` | sandbox | Yes |
| WebSearchTool | `web_search` | none | Yes |
| WebFetchTool | `web_fetch` | none | Yes |
| MemoryReadTool | `memory_read` | memory | Yes |
| MemoryWriteTool | `memory_write` | memory | No |
| AgentTool | `agent` | swarm, bus | No |
| SendMessageTool | `send_message` | swarm | No |
| TaskStopTool | `task_stop` | swarm | No |
| SkillTool | `skill` | skills | Yes |
| AskUserQuestionTool | `ask_user_question` | none | No |

## Implementing a Custom Tool

```python
from pydantic import BaseModel, Field
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult

class GreetInput(BaseModel):
    name: str = Field(description="Name to greet")

class GreetTool(BaseTool):
    name: ClassVar[str] = "greet"
    description: ClassVar[str] = "Greet someone by name."
    input_model: ClassVar[type[BaseModel]] = GreetInput

    async def execute(self, args: GreetInput, ctx: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"Hello, {args.name}!")

    @staticmethod
    def is_read_only(args: GreetInput) -> bool:
        return True
```
