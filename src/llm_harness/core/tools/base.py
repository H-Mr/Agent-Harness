"""Tool abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel


@dataclass
class ToolExecutionContext:
    """Shared execution context for tool invocations."""

    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Normalized tool execution result."""

    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all llm-harness tools."""

    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """Execute the tool."""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """Return whether the invocation is read-only."""
        del arguments
        return False

    def to_api_schema(self, api_format: str = "anthropic") -> dict[str, Any]:
        """Return the tool schema in the requested API format.

        Supported formats: ``"anthropic"``, ``"openai"``.
        """
        if api_format == "openai":
            return self.to_openai_schema()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }

    def to_openai_schema(self) -> dict[str, Any]:
        """Return the tool schema in OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }


class ToolRegistry:
    """Map tool names to implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Remove a registered tool by name."""
        self._tools.pop(name, None)

    def has(self, name: str) -> bool:
        """Return whether a tool with *name* is registered."""
        return name in self._tools

    def get(self, name: str) -> BaseTool | None:
        """Return a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    @property
    def tool_names(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return sorted(self._tools)

    def to_api_schema(self, api_format: str = "anthropic") -> list[dict[str, Any]]:
        """Return all tool schemas in the requested API format."""
        return [tool.to_api_schema(api_format=api_format) for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
