# 如何连接 MCP 服务器

## 目标

注册一个或多个 MCP 服务器的工具，使 agent 能够像调用内置原生工具一样调用它们。

## 前置条件

- 可用的 llm-harness 安装
- 可供连接的 MCP 服务器二进制文件或 URL（支持 stdio、SSE 或 streamable HTTP 传输）
- 已安装 `mcp` PyPI 包（`pip install mcp`）

## 分步指南

### 1. 理解连接 API

框架在 `llm_harness.extensions.mcp.client` 中暴露了两个入口点：

- **`connect_mcp_servers(mcp_servers, registry, stack)`** —— 从配置 dict 连接多个服务器，并将其工具注册到 `ToolRegistry`。每个工具被包装为 `MCPToolWrapper`，名称前缀为 `mcp_<server>_<tool_name>`。
- **`MCPServerConnection`** —— 用于编程式单次使用的单服务器异步上下文管理器。

### 2. 通过配置 Dict 连接（推荐）

`mcp_servers` dict 将服务器名称映射到连接参数。传输类型自动推断或显式指定：

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

    # 现在工具已注册为 mcp_filesystem_read、mcp_github_* 等
    for tool in registry.list_tools():
        print(f"  {tool.name}: {tool.description}")

    return registry
```

每条记录的 `mcp_servers` dict 支持的键：

| 键 | 说明 |
|---|---|
| `type` | `"stdio"`、`"sse"` 或 `"streamableHttp"`（省略时根据 `command`/`url` 推断） |
| `command` | stdio 传输的可执行文件路径 |
| `args` | CLI 参数列表 |
| `env` | 额外的环境变量 dict |
| `url` | SSE 或 streamable HTTP 的服务器 URL |
| `headers` | HTTP 头 dict（仅 SSE） |
| `enabled_tools` | 要暴露的工具名称列表，或 `["*"]` 表示全部 |
| `tool_timeout` | 每次工具调用的超时秒数（默认 30） |

### 3. 过滤暴露的工具

使用 `enabled_tools` 限制工具范围。可以引用原始名称（`"read"`）或包装后的名称（`"mcp_filesystem_read"`）：

```python
servers = {
    "fs": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
        "enabled_tools": [
            "read",              # 原始名称
            "mcp_fs_write",      # 包装后的名称
        ],
    },
}
```

传入 `"*"` 以启用服务器的所有工具。

### 4. 对单个服务器使用 MCPServerConnection

适用于快速脚本或测试：

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
    # 在上下文管理器活跃期间，工具可用
```

### 5. 将 Registry 传递给 Harness Agent

注册后，MCP 工具的行为与原生工具完全一致：

```python
from llm_harness.core.harness import Harness

harness = Harness(
    provider=provider,
    model="deepseek-chat",
    tools=registry,
    sandbox=sandbox,
)
agent = harness.create_agent()
# 现在 agent 可以调用 mcp_filesystem_read、mcp_filesystem_write 等
```

## 完整示例

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
    # 1. 连接 MCP 服务器
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

    # 2. 创建包含 MCP 工具的 agent
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

    # 3. 发送消息
    msg = InboundMessage("cli", "user", "c1", "List files in /workspace")
    session = Session(key="demo:mcp")
    result = await agent.process(msg, session=session, cwd=Path("./workspace"))
    print(result.final_content)

asyncio.run(main())
```

## 传输方式参考

### stdio

启动一个子进程并通过 stdin/stdout 通信。适用于本地 MCP 服务器。

```python
{"command": "npx", "args": ["-y", "my-mcp-server"], "env": {"DEBUG": "1"}}
```

### SSE（Server-Sent Events）

通过 HTTP SSE 连接。URL 通常以 `/sse` 结尾。

```python
{"url": "http://localhost:3000/sse", "headers": {"Authorization": "Bearer xxx"}}
```

自定义 HTTP 头通过 `httpx_client_factory` 回调注入到底层的 `httpx.AsyncClient`。

### streamable HTTP

使用 HTTP POST 进行请求和响应，无需持久化的 SSE 连接。

```python
{"type": "streamableHttp", "url": "http://localhost:8080/mcp"}
```

## 测试

```python
import pytest
from contextlib import AsyncExitStack
from llm_harness.extensions.mcp.client import connect_mcp_servers
from llm_harness.core.tools.base import ToolRegistry

@pytest.mark.asyncio
async def test_mcp_connection():
    registry = ToolRegistry()
    stack = AsyncExitStack()

    # 使用本地 echo 或 mock 服务器进行测试
    servers = {
        "test": {
            "command": "echo",
            "args": [],
            "enabled_tools": ["*"],
        },
    }
    # 如果服务器不可用，连接会记录警告但不会崩溃
    await connect_mcp_servers(servers, registry, stack)
    # 断言没有注册任何工具（echo 不是 MCP 服务器）
    assert len(registry.list_tools()) == 0
```
