"""Tests for memory tools — MemoryReadTool and MemoryWriteTool."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from llm_harness.core.tools.base import ToolExecutionContext, ToolResult
from llm_harness.core.tools.memory_read import MemoryReadTool, MemoryReadInput
from llm_harness.core.tools.memory_write import MemoryWriteTool, MemoryWriteInput


ctx = ToolExecutionContext(cwd=Path("/workspace"), metadata={"session_key": "test:session"})


# ---------------------------------------------------------------------------
# MemoryReadTool
# ---------------------------------------------------------------------------

class TestMemoryReadTool:
    @pytest.mark.asyncio
    async def test_reads_from_memory_backend(self):
        """MemoryReadTool reads the 'memory' section via backend.read_section."""
        mem = AsyncMock()
        mem.read_section = AsyncMock(return_value="stored memory content")
        tool = MemoryReadTool(memory=mem)
        result = await tool.execute(MemoryReadInput(), ctx)
        assert isinstance(result, ToolResult)
        assert result.output == "stored memory content"
        mem.read_section.assert_called_once_with("test:session", "memory")

    @pytest.mark.asyncio
    async def test_uses_session_key_from_metadata(self):
        """The session_key in context metadata determines namespace."""
        mem = AsyncMock()
        mem.read_section = AsyncMock(return_value="data")
        tool = MemoryReadTool(memory=mem)
        custom_ctx = ToolExecutionContext(cwd=Path("/ws"), metadata={"session_key": "custom:key"})
        await tool.execute(MemoryReadInput(), custom_ctx)
        mem.read_section.assert_called_once_with("custom:key", "memory")

    @pytest.mark.asyncio
    async def test_handles_empty_response(self):
        """When backend returns empty/None, a fallback message is returned."""
        mem = AsyncMock()
        mem.read_section = AsyncMock(return_value="")
        tool = MemoryReadTool(memory=mem)
        result = await tool.execute(MemoryReadInput(), ctx)
        assert result.output == "(no memory stored)"

    def test_is_read_only_true(self):
        """MemoryReadTool is read-only."""
        tool = MemoryReadTool(memory=AsyncMock())
        assert tool.is_read_only(MemoryReadInput()) is True


# ---------------------------------------------------------------------------
# MemoryWriteTool
# ---------------------------------------------------------------------------

class TestMemoryWriteTool:
    @pytest.mark.asyncio
    async def test_writes_to_memory_backend(self):
        """MemoryWriteTool appends to the 'memory' section via backend.append_section."""
        mem = AsyncMock()
        tool = MemoryWriteTool(memory=mem)
        result = await tool.execute(MemoryWriteInput(entry="important note"), ctx)
        assert isinstance(result, ToolResult)
        assert result.output == "Memory updated."
        mem.append_section.assert_called_once_with("test:session", "memory", "important note")

    @pytest.mark.asyncio
    async def test_uses_session_key_from_metadata(self):
        """The session_key in context metadata determines namespace."""
        mem = AsyncMock()
        tool = MemoryWriteTool(memory=mem)
        custom_ctx = ToolExecutionContext(cwd=Path("/ws"), metadata={"session_key": "other:key"})
        await tool.execute(MemoryWriteInput(entry="note"), custom_ctx)
        mem.append_section.assert_called_once_with("other:key", "memory", "note")
