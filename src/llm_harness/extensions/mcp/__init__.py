"""MCP client — connects to MCP servers and wraps their tools as native tools."""

from llm_harness.extensions.mcp.client import MCPToolWrapper, connect_mcp_servers

# Alias for backward compatibility
MCPClient = MCPToolWrapper

__all__ = [
    "MCPToolWrapper",
    "MCPClient",
    "connect_mcp_servers",
]
