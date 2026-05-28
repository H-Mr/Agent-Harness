"""Tests for ExecTool — shell command execution via sandbox."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from llm_harness.adapters.sandbox.backend import ExecResult
from llm_harness.core.tools.base import ToolExecutionContext, ToolResult
from llm_harness.core.tools.exec import ExecTool, ExecInput


ctx = ToolExecutionContext(cwd=Path("/workspace"), metadata={"session_key": "test:session"})


class TestExecTool:
    @pytest.mark.asyncio
    async def test_execute_with_default_cwd_and_timeout(self):
        """ExecTool passes command with default cwd=/workspace and timeout=60."""
        sb = AsyncMock()
        sb.execute = AsyncMock(return_value=ExecResult(output="ok", exit_code=0))
        tool = ExecTool(sandbox=sb)
        result = await tool.execute(ExecInput(command="ls -la"), ctx)
        assert isinstance(result, ToolResult)
        assert result.output == "ok"
        sb.execute.assert_called_once_with("test:session", "ls -la", cwd="/workspace", timeout=60)

    @pytest.mark.asyncio
    async def test_execute_with_custom_working_dir(self):
        """ExecTool uses custom working_dir when provided."""
        sb = AsyncMock()
        sb.execute = AsyncMock(return_value=ExecResult(output="ok", exit_code=0))
        tool = ExecTool(sandbox=sb)
        await tool.execute(ExecInput(command="pwd", working_dir="/custom/path"), ctx)
        sb.execute.assert_called_once_with("test:session", "pwd", cwd="/custom/path", timeout=60)

    @pytest.mark.asyncio
    async def test_passes_session_key(self):
        """session_key from context metadata is passed to sandbox.execute."""
        sb = AsyncMock()
        sb.execute = AsyncMock(return_value=ExecResult(output="ok", exit_code=0))
        tool = ExecTool(sandbox=sb)
        custom_ctx = ToolExecutionContext(cwd=Path("/ws"), metadata={"session_key": "custom:key"})
        await tool.execute(ExecInput(command="whoami"), custom_ctx)
        assert sb.execute.call_args[0][0] == "custom:key"

    @pytest.mark.asyncio
    async def test_non_zero_exit_code_shown_in_output(self):
        """A non-zero exit code is appended to the output."""
        sb = AsyncMock()
        sb.execute = AsyncMock(return_value=ExecResult(output="error msg", exit_code=1, is_error=True))
        tool = ExecTool(sandbox=sb)
        result = await tool.execute(ExecInput(command="bad-command"), ctx)
        assert "Exit code: 1" in result.output
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_propagates_sandbox_errors(self):
        """Sandbox exceptions propagate up from execute (caught by AgentLoop)."""
        sb = AsyncMock()
        sb.execute = AsyncMock(side_effect=Exception("sandbox timeout"))
        tool = ExecTool(sandbox=sb)
        with pytest.raises(Exception, match="sandbox timeout"):
            await tool.execute(ExecInput(command="sleep 100"), ctx)
