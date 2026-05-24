# Tools -- The Tool System

## Overview

The tool system is the bridge between an LLM's intent and real-world actions.
Every tool call follows a strict lifecycle: schema generation, argument
validation, permission check, execution, and result emission.

## BaseTool ABC

Every tool extends `BaseTool`, an abstract base class with three required class
variables and one abstract method:

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from agent_harness.tools.base import ToolExecutionContext, ToolResult

class MyTool(BaseTool):
    name = "my_tool"              # ClassVar[str] -- unique tool name
    description = "Does something useful"  # ClassVar[str] -- LLM-facing description
    input_model: type[BaseModel] = MyInput  # ClassVar -- Pydantic model for args

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        # ... implementation
        return ToolResult(output="done")
```

### Class Variables

| Field | Type | Purpose |
|-------|------|---------|
| `name` | `ClassVar[str]` | Unique identifier used in API schemas and tool routing |
| `description` | `ClassVar[str]` | Human/LLM-readable description of what the tool does |
| `input_model` | `ClassVar[type[BaseModel]]` | Pydantic model class that validates arguments |

### Abstract Method: `execute()`

```python
async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
```

- `arguments` is a validated instance of `self.input_model`
- `context` provides execution metadata (`cwd`, `metadata` dict)
- Returns a `ToolResult` with `output` (str), `is_error` (bool), and optional `metadata`

### Optional Method: `is_read_only()`

```python
def is_read_only(self, arguments: BaseModel) -> bool:
    return False
```

Override to declare that a particular invocation is read-only. Read-only tools
bypass confirmation prompts in DEFAULT permission mode.

### Schema Methods

Tools can produce schemas in both Anthropic and OpenAI formats:

```python
tool.to_api_schema("anthropic")  # -> {"name": ..., "description": ..., "input_schema": ...}
tool.to_api_schema("openai")     # -> {"type": "function", "function": {...}}
tool.to_openai_schema()          # same as to_api_schema("openai")
```

## ToolExecutionContext

```python
@dataclass
class ToolExecutionContext:
    cwd: Path                    # Working directory for execution
    metadata: dict[str, Any]     # Additional context (caller info, etc.)
```

## ToolResult

```python
@dataclass(frozen=True)
class ToolResult:
    output: str                  # Text output (shown to LLM)
    is_error: bool = False       # Whether execution failed
    metadata: dict[str, Any]     # Structured metadata (not shown to LLM)
```

## ToolRegistry

`ToolRegistry` maps tool names to `BaseTool` instances and provides batch
schema conversion.

```python
registry = ToolRegistry()

# Registration
registry.register(ReadFileTool())
registry.register(WriteFileTool())
registry.register(ExecTool())

# Lookup
tool = registry.get("read_file")   # -> BaseTool | None
has = registry.has("read_file")    # -> bool

# Enumeration
all_tools = registry.list_tools()  # -> list[BaseTool]
names = registry.tool_names        # -> ["edit_file", "exec", "glob", ...]

# Schema conversion (for LLM API calls)
anthropic_schemas = registry.to_api_schema("anthropic")
openai_schemas = registry.to_api_schema("openai")

# Removal
registry.unregister("old_tool")
```

### API Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `register(tool)` | `None` | Register a tool instance by its `name` |
| `unregister(name)` | `None` | Remove a tool by name |
| `has(name)` | `bool` | Check if a tool is registered |
| `get(name)` | `BaseTool | None` | Look up a tool by name |
| `list_tools()` | `list[BaseTool]` | Return all registered tool instances |
| `tool_names` | `list[str]` | Sorted list of registered tool names |
| `to_api_schema(api_format)` | `list[dict]` | Convert all tools to API schema format |

## Dual Schema Format: Anthropic and OpenAI

The system supports both major function-calling formats. Tools store their
canonical schema in Pydantic and convert on demand:

```python
# Anthropic format (default)
{
    "name": "read_file",
    "description": "Read the contents of a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"}
        },
        "required": ["file_path"]
    }
}

# OpenAI format
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "parameters": {
            "type": "object",
            "properties": {...},
            "required": ["file_path"]
        }
    }
}
```

## Observability Events

The `AgentLoop` automatically emits structured events around tool execution:

- `ToolExecutionStarted(tool_name, tool_input)` -- emitted before execution
- `ToolExecutionCompleted(tool_name, output, is_error, duration_ms)` -- emitted after execution

These events flow to both the `LoopCallbacks.on_event` callback and the global
`EventBus`. See [Observability](observability.md) for details.

## Config-Driven Tools

The `build_tools_from_config()` function builds a `ToolRegistry` from a
`ToolsConfig` object, which is typically loaded from a JSON config file.

```python
from agent_harness import build_tools_from_config, ToolsConfig

config = ToolsConfig(
    enabled=["*"],           # Enable all tools
    exec_enable=True,
    exec_timeout=120,
    restrict_to_workspace=True,
)

registry = build_tools_from_config(config, workspace=Path("./project"))
```

### Sentinel Values

The `enabled` list supports two special sentinel values:

| Sentinel | Meaning |
|----------|---------|
| `"*"` | Enable all tools (default) |
| `"none"` | Disable all tools |

When neither sentinel is used, only the explicitly named tools are enabled:

```python
ToolsConfig(enabled=["read_file", "write_file", "exec", "web_search"])
```

The `disabled` list always overrides `enabled`:

```python
ToolsConfig(enabled=["*"], disabled=["exec"])  # All tools except exec
```

### Tool-Specific Options

The `ToolsConfig` schema includes per-tool settings:

```python
class ToolsConfig(BaseModel):
    exec_timeout: int = 60
    exec_enable: bool = True
    web_search_provider: str = "duckduckgo"
    web_search_max_results: int = 5
    enabled: list[str] = ["*"]
    disabled: list[str] = []
    restrict_to_workspace: bool = False
```

## Built-In Tools (28 Tools)

| Tool Name | Description |
|-----------|-------------|
| `read_file` | Read file contents with optional offset/limit |
| `write_file` | Write content to a file |
| `edit_file` | Apply a surgical edit to a file (find/replace) |
| `list_dir` | List directory contents |
| `exec` | Execute shell commands (with timeout and workspace restrictions) |
| `web_search` | Search the web via DuckDuckGo or other providers |
| `web_fetch` | Fetch and extract content from a URL |
| `glob` | Find files matching a glob pattern |
| `grep` | Search file contents with regex |
| `notebook_edit` | Edit Jupyter notebook cells |
| `message` | Send a message to a channel (app-specific routing) |
| `memory_read` | Read long-term memory |
| `memory_write` | Write to long-term memory |
| `spawn` | Spawn a sub-agent task (requires SubagentManager) |
| `ask_user_question` | Pause and ask the user a question (requires callback) |
| `cron_create` | Create a cron-style scheduled job |
| `cron_delete` | Delete a scheduled job |
| `cron_list` | List scheduled jobs |
| `cron_toggle` | Enable or disable a scheduled job |
| `todo_write` | Write an item to the todo list |
| `tool_search` | Search available tools by keyword |
| `skill` | Load and invoke an on-demand skill |
| `task_create` | Create a background task |
| `task_get` | Get a background task's status |
| `task_list` | List all background tasks |
| `task_update` | Update a background task |
| `task_stop` | Stop a background task |
| `task_output` | Get a background task's output |

!!! note "Some tools require runtime injection"
    Tools like `spawn`, `ask_user_question`, and `cron_create` return `None` from
    their factory function in `build_tools_from_config()` because they need
    runtime dependencies (SubagentManager, callback, CronService). Applications
    that need these tools should register them manually after build.

## Writing Custom Tools

### Step 1: Define the Input Model

```python
from pydantic import BaseModel, Field

class WeatherInput(BaseModel):
    location: str = Field(description="City name or coordinates")
    units: str = Field(default="celsius", description="Temperature units")
```

### Step 2: Implement the Tool

```python
from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

class WeatherTool(BaseTool):
    name = "get_weather"
    description = "Get current weather for a location"
    input_model = WeatherInput

    async def execute(self, arguments: WeatherInput, context: ToolExecutionContext) -> ToolResult:
        api_key = os.environ.get("WEATHER_API_KEY")
        # ... call weather API
        return ToolResult(output=f"Temperature in {arguments.location}: 22°{arguments.units[0].upper()}")
```

### Step 3: Register and Use

```python
registry = ToolRegistry()
registry.register(WeatherTool())

harness = Harness(provider=provider, tools=registry)
agent = Agent(harness)
```

## Tool Lifecycle

Every tool invocation follows this lifecycle:

```
LLM returns tool_call(name="read_file", args={"file_path": "..."})
  │
  ├─ 1. Lookup ──────── registry.get("read_file") → ReadFileTool instance
  │
  ├─ 2. Validate ────── tool.input_model.model_validate({"file_path": "..."})
  │                      → validated Pydantic model
  │
  ├─ 3. Permission ──── harness.on_tool_check("read_file", tool, parsed_args)
  │                      → PermissionDecision (allowed/denied/confirm)
  │
  ├─ 4. Execute ─────── tool.execute(parsed_args, context)
  │                      → ToolResult
  │
  └─ 5. Return ─────── result.output → LLM as tool result message
```

The `AgentLoop._build_loop()` method in the Agent class wires this lifecycle:

```python
async def execute_tool(tool_name, args_dict):
    tool = harness.tools.get(tool_name)
    parsed = tool.input_model.model_validate(args_dict)
    permission = await harness.on_tool_check(tool_name, tool, parsed)
    if not permission.allowed:
        return f"Error: Permission denied: {permission.reason}"
    context = ToolExecutionContext(cwd=harness.workspace)
    result = await tool.execute(parsed, context)
    return result.output
```

---

**Prev:** [Agent Deep Dive](agent.md) | **Next:** [Providers](providers.md)
