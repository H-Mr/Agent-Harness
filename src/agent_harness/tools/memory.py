"""Memory tools for reading/writing persistent long-term memory.

Provides write_memory and read_memory tools following the BaseTool pattern.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class MemoryWriteInput(BaseModel):
    """Input model for write_memory tool."""

    entry: str = Field(description="Memory entry to persist (markdown)")


class MemoryWriteTool(BaseTool):
    """Tool to write to persistent long-term memory (MEMORY.md)."""

    name = "write_memory"
    description = "Write to persistent long-term memory (MEMORY.md)."
    input_model = MemoryWriteInput

    def __init__(self, memory_store: Any) -> None:
        self._store = memory_store

    async def execute(self, arguments: MemoryWriteInput, context: ToolExecutionContext) -> ToolResult:
        """Write an entry to long-term memory."""
        self._store.write_long_term(arguments.entry)
        return ToolResult(output="Memory updated.")


class MemoryReadInput(BaseModel):
    """Input model for read_memory tool (no parameters needed)."""


class MemoryReadTool(BaseTool):
    """Tool to read current long-term memory (MEMORY.md)."""

    name = "read_memory"
    description = "Read current long-term memory (MEMORY.md)."
    input_model = MemoryReadInput

    def __init__(self, memory_store: Any) -> None:
        self._store = memory_store

    async def execute(self, arguments: MemoryReadInput, context: ToolExecutionContext) -> ToolResult:
        """Read and return the current long-term memory."""
        content = self._store.read_long_term()
        return ToolResult(output=content or "(no memory stored)")
