"""Tool: WriteFileTool — write file contents via sandbox."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class WriteFileInput(BaseModel):
    path: str = Field(description="The file path to write to")
    content: str = Field(description="The content to write")


class WriteFileTool(BaseTool):
    """Write content to a file via the sandbox backend."""

    name: ClassVar[str] = "write_file"
    description: ClassVar[str] = "Write content to a file at the given path."
    input_model: ClassVar[type[BaseModel]] = WriteFileInput

    def __init__(self, sandbox: SandboxBackend) -> None:
        self._sandbox = sandbox

    async def execute(self, arguments: WriteFileInput, context: ToolExecutionContext) -> ToolResult:
        session_key = context.metadata.get("session_key", "")
        await self._sandbox.write_file(session_key, arguments.path, arguments.content)
        return ToolResult(output=f"Successfully wrote {len(arguments.content)} bytes to {arguments.path}")
