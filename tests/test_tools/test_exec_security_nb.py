"""Tests for exec tool internal URL blocking.

Adapted for agent-harness: the exec tool uses regex-based private IP detection
instead of DNS resolution. URLs with private IP literals are blocked directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.tools.base import ToolExecutionContext
from agent_harness.tools.shell import ExecTool, ExecInput


@pytest.mark.asyncio
async def test_exec_blocks_curl_metadata():
    """Private IP in URL is blocked directly by regex (no DNS needed)."""
    tool = ExecTool()
    result = await tool.execute(
        ExecInput(command='curl -s -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/'),
        ToolExecutionContext(cwd=Path.cwd()),
    )
    assert "Error" in result.output
    assert "internal" in result.output.lower() or "private" in result.output.lower()


@pytest.mark.asyncio
async def test_exec_blocks_wget_localhost():
    """Localhost URL is blocked directly."""
    tool = ExecTool()
    result = await tool.execute(
        ExecInput(command="wget http://localhost:8080/secret -O /tmp/out"),
        ToolExecutionContext(cwd=Path.cwd()),
    )
    assert "Error" in result.output


@pytest.mark.asyncio
async def test_exec_allows_normal_commands():
    """Simple commands should pass through."""
    tool = ExecTool(timeout=5)
    result = await tool.execute(
        ExecInput(command="echo hello"),
        ToolExecutionContext(cwd=Path.cwd()),
    )
    assert "hello" in result.output
    assert "Error" not in result.output.split("\n")[0]


@pytest.mark.asyncio
async def test_exec_allows_curl_to_public_url():
    """Commands with public URLs should not be blocked."""
    tool = ExecTool()
    guard_result = tool._guard_command("curl https://example.com/api", str(Path.cwd()))
    assert guard_result is None


@pytest.mark.asyncio
async def test_exec_blocks_chained_internal_url():
    """Internal URLs buried in chained commands should still be caught."""
    tool = ExecTool()
    result = await tool.execute(
        ExecInput(command="echo start && curl http://169.254.169.254/latest/meta-data/ && echo done"),
        ToolExecutionContext(cwd=Path.cwd()),
    )
    assert "Error" in result.output
