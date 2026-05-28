"""Tool: GrepTool — search file contents via sandbox."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class GrepInput(BaseModel):
    pattern: str = Field(description="Regular expression to search for")
    path: str = Field(default=".", description="Search root path")
    limit: int = Field(default=200, ge=1, le=5000, description="Maximum results to return")


class GrepTool(BaseTool):
    """Search file contents with a regular expression via the sandbox backend."""

    name: ClassVar[str] = "grep"
    description: ClassVar[str] = "Search file contents with a regular expression."
    input_model: ClassVar[type[BaseModel]] = GrepInput

    def __init__(self, sandbox: SandboxBackend) -> None:
        self._sandbox = sandbox

    async def execute(self, arguments: GrepInput, context: ToolExecutionContext) -> ToolResult:
        session_key = context.metadata.get("session_key", "")
        matches = await self._sandbox.grep(session_key, arguments.pattern, arguments.path)
        if not matches:
            return ToolResult(output="(no matches)")
        return ToolResult(output="\n".join(matches[: arguments.limit]))

    def is_read_only(self, arguments: GrepInput) -> bool:
        del arguments
        return True
