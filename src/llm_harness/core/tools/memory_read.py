"""Tool: MemoryReadTool — read memory section via MemoryBackend."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class MemoryReadInput(BaseModel):
    """No parameters needed for reading memory."""


class MemoryReadTool(BaseTool):
    """Read the current long-term memory section."""

    name: ClassVar[str] = "memory_read"
    description: ClassVar[str] = "Read current long-term memory."
    input_model: ClassVar[type[BaseModel]] = MemoryReadInput

    def __init__(self, memory: MemoryBackend) -> None:
        self._memory = memory

    async def execute(self, arguments: MemoryReadInput, context: ToolExecutionContext) -> ToolResult:
        del arguments
        session_key = context.metadata.get("session_key", "")
        content = await self._memory.read_section(session_key, "memory")
        return ToolResult(output=content or "(no memory stored)")

    def is_read_only(self, arguments: MemoryReadInput) -> bool:
        del arguments
        return True
