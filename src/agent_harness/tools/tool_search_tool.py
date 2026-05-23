"""Tool for searching available tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult, ToolRegistry


class ToolSearchToolInput(BaseModel):
    """Arguments for tool search."""

    query: str = Field(description="Substring to search in tool names and descriptions")


class ToolSearchTool(BaseTool):
    """Search tool registry contents by name or description."""

    name = "tool_search"
    description = "Search the available tool list by name or description."
    input_model = ToolSearchToolInput

    def __init__(self, registry: ToolRegistry | None = None):
        self._registry = registry

    def is_read_only(self, arguments: ToolSearchToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: ToolSearchToolInput, context: ToolExecutionContext) -> ToolResult:
        registry = self._registry or context.metadata.get("tool_registry")
        if registry is None:
            return ToolResult(output="Tool registry not available", is_error=True)
        query = arguments.query.lower()
        matches = [
            tool for tool in registry.list_tools()
            if query in tool.name.lower() or query in tool.description.lower()
        ]
        if not matches:
            return ToolResult(output="(no matches)")
        return ToolResult(output="\n".join(f"{tool.name}: {tool.description}" for tool in matches))
