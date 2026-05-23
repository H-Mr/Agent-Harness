"""Tests for MessageTool adapted for agent-harness BaseTool interface."""

from pathlib import Path

import pytest

from agent_harness.tools.base import ToolExecutionContext
from agent_harness.tools.message import MessageInput, MessageTool


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(
        MessageInput(content="test"),
        ToolExecutionContext(cwd=Path.cwd()),
    )
    assert result.output == "Error: No target channel/chat specified"
