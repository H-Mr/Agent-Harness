"""Tool: GlobTool — glob for files via sandbox."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class GlobInput(BaseModel):
    pattern: str = Field(description="Glob pattern to match")
    limit: int = Field(default=200, ge=1, le=5000, description="Maximum results to return")


class GlobTool(BaseTool):
    """List files matching a glob pattern via the sandbox backend."""

    name: ClassVar[str] = "glob"
    description: ClassVar[str] = "List files matching a glob pattern."
    input_model: ClassVar[type[BaseModel]] = GlobInput

    def __init__(self, sandbox: SandboxBackend) -> None:
        self._sandbox = sandbox

    async def execute(self, arguments: GlobInput, context: ToolExecutionContext) -> ToolResult:
        session_key = context.metadata.get("session_key", "")
        matches = await self._sandbox.glob(session_key, arguments.pattern)
        if not matches:
            return ToolResult(output="(no matches)")
        return ToolResult(output="\n".join(matches[: arguments.limit]))

    def is_read_only(self, arguments: GlobInput) -> bool:
        del arguments
        return True
