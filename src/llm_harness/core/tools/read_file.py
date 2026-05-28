"""Tool: ReadFileTool — read file contents via sandbox."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class ReadFileInput(BaseModel):
    path: str = Field(description="The file path to read")
    offset: int = Field(default=1, ge=1, description="Line number to start reading from (1-indexed)")
    limit: int = Field(default=2000, ge=1, description="Maximum number of lines to read")


class ReadFileTool(BaseTool):
    """Read file contents via the sandbox backend."""

    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = "Read the contents of a file."
    input_model: ClassVar[type[BaseModel]] = ReadFileInput

    def __init__(self, sandbox: SandboxBackend) -> None:
        self._sandbox = sandbox

    async def execute(self, arguments: ReadFileInput, context: ToolExecutionContext) -> ToolResult:
        session_key = context.metadata.get("session_key", "")
        result = await self._sandbox.read_file(session_key, arguments.path)

        all_lines = result.splitlines()
        total = len(all_lines)
        offset = max(arguments.offset, 1)
        limit = arguments.limit

        if offset > total:
            return ToolResult(
                output=f"Error: offset {offset} is beyond end of file ({total} lines)",
                is_error=True,
            )

        start = offset - 1
        end = min(start + limit, total)
        numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
        output = "\n".join(numbered)

        truncated = end < total
        if truncated:
            output += f"\n\n(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)"
        else:
            output += f"\n\n(End of file -- {total} lines total)"

        return ToolResult(output=output)

    def is_read_only(self, arguments: ReadFileInput) -> bool:
        del arguments
        return True
