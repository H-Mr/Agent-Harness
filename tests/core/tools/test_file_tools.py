"""Tests for file tools — ReadFileTool, WriteFileTool, EditFileTool."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from llm_harness.core.tools.base import ToolExecutionContext, ToolResult
from llm_harness.core.tools.read_file import ReadFileTool, ReadFileInput
from llm_harness.core.tools.write_file import WriteFileTool, WriteFileInput
from llm_harness.core.tools.edit_file import EditFileTool, EditFileInput


ctx = ToolExecutionContext(cwd=Path("/workspace"), metadata={"session_key": "test:session"})


# ---------------------------------------------------------------------------
# ReadFileTool
# ---------------------------------------------------------------------------

class TestReadFileTool:
    @pytest.mark.asyncio
    async def test_execute_reads_via_sandbox(self):
        """ReadFileTool.execute delegates to sandbox.read_file and returns content."""
        sb = AsyncMock()
        sb.read_file = AsyncMock(return_value="line1\nline2\nline3")
        tool = ReadFileTool(sandbox=sb)
        result = await tool.execute(ReadFileInput(path="/test/file.txt"), ctx)
        assert isinstance(result, ToolResult)
        assert "1| line1" in result.output
        sb.read_file.assert_called_once_with("test:session", "/test/file.txt")

    @pytest.mark.asyncio
    async def test_passes_session_key(self):
        """session_key from context metadata is passed to sandbox."""
        sb = AsyncMock()
        sb.read_file = AsyncMock(return_value="test content")
        tool = ReadFileTool(sandbox=sb)
        await tool.execute(ReadFileInput(path="/f.txt"), ctx)
        sb.read_file.assert_called_once_with("test:session", "/f.txt")

    @pytest.mark.asyncio
    async def test_propagates_sandbox_error(self):
        """Sandbox exceptions propagate up from execute (caught by AgentLoop)."""
        sb = AsyncMock()
        sb.read_file = AsyncMock(side_effect=Exception("File not found"))
        tool = ReadFileTool(sandbox=sb)
        with pytest.raises(Exception, match="File not found"):
            await tool.execute(ReadFileInput(path="/missing.txt"), ctx)

    def test_is_read_only_true(self):
        """ReadFileTool is read-only."""
        tool = ReadFileTool(sandbox=AsyncMock())
        assert tool.is_read_only(ReadFileInput(path="x")) is True


# ---------------------------------------------------------------------------
# WriteFileTool
# ---------------------------------------------------------------------------

class TestWriteFileTool:
    @pytest.mark.asyncio
    async def test_execute_writes_via_sandbox(self):
        """WriteFileTool.execute delegates to sandbox.write_file with path and content."""
        sb = AsyncMock()
        tool = WriteFileTool(sandbox=sb)
        result = await tool.execute(
            WriteFileInput(path="/test/out.txt", content="hello world"), ctx,
        )
        assert isinstance(result, ToolResult)
        assert "Successfully wrote" in result.output
        sb.write_file.assert_called_once_with("test:session", "/test/out.txt", "hello world")

    @pytest.mark.asyncio
    async def test_passes_session_key(self):
        """session_key from context metadata is passed to sandbox."""
        sb = AsyncMock()
        tool = WriteFileTool(sandbox=sb)
        await tool.execute(WriteFileInput(path="/f.txt", content="data"), ctx)
        sb.write_file.assert_called_once_with("test:session", "/f.txt", "data")

    def test_is_read_only_false(self):
        """WriteFileTool is not read-only."""
        tool = WriteFileTool(sandbox=AsyncMock())
        assert tool.is_read_only(WriteFileInput(path="x", content="y")) is False


# ---------------------------------------------------------------------------
# EditFileTool
# ---------------------------------------------------------------------------

class TestEditFileTool:
    @pytest.mark.asyncio
    async def test_execute_edits_via_sandbox(self):
        """EditFileTool reads, replaces, then writes back via sandbox."""
        sb = AsyncMock()
        sb.read_file = AsyncMock(return_value="old content here")
        tool = EditFileTool(sandbox=sb)
        result = await tool.execute(
            EditFileInput(path="/test/f.py", old_text="old", new_text="new"), ctx,
        )
        assert isinstance(result, ToolResult)
        assert "Successfully edited" in result.output
        sb.write_file.assert_called_once()
        written_content = sb.write_file.call_args[0][2]
        assert "new" in written_content

    @pytest.mark.asyncio
    async def test_passes_session_key(self):
        """session_key from context metadata is passed to sandbox for both read and write."""
        sb = AsyncMock()
        sb.read_file = AsyncMock(return_value="old text")
        tool = EditFileTool(sandbox=sb)
        await tool.execute(EditFileInput(path="/f.py", old_text="old", new_text="new"), ctx)
        sb.read_file.assert_called_once_with("test:session", "/f.py")
        sb.write_file.assert_called_once()
        assert sb.write_file.call_args[0][0] == "test:session"

    @pytest.mark.asyncio
    async def test_old_text_not_found_returns_error(self):
        """When old_text is not found, an error ToolResult is returned."""
        sb = AsyncMock()
        sb.read_file = AsyncMock(return_value="irrelevant content")
        tool = EditFileTool(sandbox=sb)
        result = await tool.execute(
            EditFileInput(path="/f.py", old_text="nonexistent", new_text="new"), ctx,
        )
        assert result.is_error is True
        assert "not found" in result.output

    @pytest.mark.asyncio
    async def test_propagates_sandbox_read_error(self):
        """If sandbox.read_file raises, an error ToolResult is returned."""
        sb = AsyncMock()
        sb.read_file = AsyncMock(side_effect=Exception("read failed"))
        tool = EditFileTool(sandbox=sb)
        result = await tool.execute(
            EditFileInput(path="/f.py", old_text="old", new_text="new"), ctx,
        )
        assert result.is_error is True
        assert "Error reading" in result.output

    def test_is_read_only_false(self):
        """EditFileTool is not read-only."""
        tool = EditFileTool(sandbox=AsyncMock())
        assert tool.is_read_only(EditFileInput(path="x", old_text="a", new_text="b")) is False
