# How to Connect MCP Servers

## Goal

Register tools from one or more MCP servers so the agent can invoke them alongside native built-in tools.

## Prerequisites

- Working llm-harness installation
- An MCP server binary or URL to connect to (stdio, SSE, or streamable HTTP transports)
- The `mcp` PyPI package installed (`pip install mcp`)

## Step by Step

### 1. Understand the Connection API

The framework exposes two entry points in `llm_harness.extensions.mcp.client`:

- **`connect_mcp_servers(mcp_servers, registry, stack)`** -- connects multiple servers from a config dict and registers their tools into a `ToolRegistry`. Each tool is wrapped as an `MCPToolWrapper` prefixed with `mcp_<server>_<tool_name>`.
- **`MCPServerConnection`** -- a single-server async context manager for programmatic one-off use.

### 2. Connect via Config Dict (Recommended)

The `mcp_servers` dict maps server names to connection parameters. The transport type is inferred or set explicitly:

```python
import asyncio
from contextlib import AsyncExitStack
from llm_harness.extensions.mcp.client import connect_mcp_servers
from llm_harness.core.tools.base import ToolRegistry

async def register_mcp_tools() -> ToolRegistry:
    registry = ToolRegistry()
    stack = AsyncExitStack()

    servers = {
        "filesystem": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
            "enabled_tools": ["read", "write", "list_directory"],
            "tool_timeout": 30,
        },
        "github": {
            "type": "sse",
            "url": "https://mcp.example.com/sse",
            "headers": {"Authorization": "Bearer <token>"},
        },
    }

    await connect_mcp_servers(servers, registry, stack)

    # Tools are now registered as mcp_filesystem_read, mcp_github_*, etc.
    for tool in registry.list_tools():
        print(f"  {tool.name}: {tool.description}")

    return registry
```

The supported `mcp_servers` dict keys per entry:

| Key | Description |
|---|---|
| `type` | `"stdio"`, `"sse"`, or `"streamableHttp"` (inferred from `command`/`url` if omitted) |
| `command` | Executable path for stdio transport |
| `args` | List of CLI arguments |
| `env` | Dict of extra environment variables |
| `url` | Server URL for SSE or streamable HTTP |
| `headers` | Dict of HTTP headers (SSE only) |
| `enabled_tools` | List of tool names to expose, or `["*"]` for all |
| `tool_timeout` | Seconds per tool call (default 30) |

### 3. Filter Which Tools Are Exposed

Use `enabled_tools` to limit the tool surface. You can reference raw names (`"read"`) or wrapped names (`"mcp_filesystem_read"`):

```python
servers = {
    "fs": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
        "enabled_tools": [
            "read",              # raw name
            "mcp_fs_write",      # wrapped name
        ],
    },
}
```

Pass `"*"` to enable all tools from the server.

### 4. Use MCPServerConnection for a Single Server

For quick scripts or tests:

```python
from llm_harness.extensions.mcp.client import MCPServerConnection
from llm_harness.core.tools.base import ToolRegistry

async def connect_one():
    registry = ToolRegistry()
    async with MCPServerConnection(
        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    ) as server:
        for tool in server.tools:
            registry.register(tool)
    # Tools are usable while the context manager is active
```

### 5. Pass the Registry to a Harness Agent

Once registered, MCP tools behave identically to native tools:

```python
from llm_harness.core.harness import Harness

harness = Harness(
    provider=provider,
    model="deepseek-chat",
    tools=registry,
    sandbox=sandbox,
)
agent = harness.create_agent()
# The agent can now invoke mcp_filesystem_read, mcp_filesystem_write, etc.
```

## Complete Example

```python
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from llm_harness.extensions.mcp.client import connect_mcp_servers
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage

async def main():
    # 1. Connect MCP servers
    registry = ToolRegistry()
    stack = AsyncExitStack()

    servers = {
        "filesystem": {
            "command": "npx",
            "args": [
                "-y",
                "@modelcontextprotocol/server-filesystem",
                str(Path.cwd() / "workspace"),
            ],
            "enabled_tools": ["*"],
        },
    }
    await connect_mcp_servers(servers, registry, stack)

    # 2. Create agent with MCP tools included
    provider = OpenAICompatProvider(
        api_key=..., api_base="https://api.deepseek.com"
    )
    sandbox = SRTSandboxBackend(Path("./workspace"))
    harness = Harness(
        provider=provider,
        model="deepseek-chat",
        tools=registry,
        sandbox=sandbox,
    )
    agent = harness.create_agent()

    # 3. Send a message
    msg = InboundMessage("cli", "user", "c1", "List files in /workspace")
    session = Session(key="demo:mcp")
    result = await agent.process(msg, session=session, cwd=Path("./workspace"))
    print(result.final_content)

asyncio.run(main())
```

## Transport Reference

### stdio

Spawns a subprocess and communicates over stdin/stdout. Suitable for local MCP servers.

```python
{"command": "npx", "args": ["-y", "my-mcp-server"], "env": {"DEBUG": "1"}}
```

### SSE (Server-Sent Events)

Connects over HTTP SSE. The URL typically ends in `/sse`.

```python
{"url": "http://localhost:3000/sse", "headers": {"Authorization": "Bearer xxx"}}
```

Custom HTTP headers are injected into the underlying `httpx.AsyncClient` via the `httpx_client_factory` callback.

### streamable HTTP

Uses HTTP POST for requests and responses without a persistent SSE connection.

```python
{"type": "streamableHttp", "url": "http://localhost:8080/mcp"}
```

## Testing

```python
import pytest
from contextlib import AsyncExitStack
from llm_harness.extensions.mcp.client import connect_mcp_servers
from llm_harness.core.tools.base import ToolRegistry

@pytest.mark.asyncio
async def test_mcp_connection():
    registry = ToolRegistry()
    stack = AsyncExitStack()

    # Use a local echo or mock server for testing
    servers = {
        "test": {
            "command": "echo",
            "args": [],
            "enabled_tools": ["*"],
        },
    }
    # Connection will log a warning but not crash if the server is unavailable
    await connect_mcp_servers(servers, registry, stack)
    # Assert no tools were registered (echo isn't an MCP server)
    assert len(registry.list_tools()) == 0
```
