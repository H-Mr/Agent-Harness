"""Tool: MemoryWriteTool — write entry to memory section via MemoryBackend."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class MemoryWriteInput(BaseModel):
    entry: str = Field(description="Memory entry to persist (markdown)")


class MemoryWriteTool(BaseTool):
    """Write an entry to persistent long-term memory."""

    name: ClassVar[str] = "memory_write"
    description: ClassVar[str] = "Write an entry to persistent long-term memory."
    input_model: ClassVar[type[BaseModel]] = MemoryWriteInput

    def __init__(self, memory: MemoryBackend) -> None:
        self._memory = memory

    async def execute(self, arguments: MemoryWriteInput, context: ToolExecutionContext) -> ToolResult:
        session_key = context.metadata.get("session_key", "")
        await self._memory.append_section(session_key, "memory", arguments.entry)
        return ToolResult(output="Memory updated.")
