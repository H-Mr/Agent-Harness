"""Test message tool suppress logic for final replies.

Adapted for agent-harness: tests MessageTool suppress logic at unit level
rather than through the full AgentLoop (which has a different architecture
based on LoopCallbacks).
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_harness.bus.events import OutboundMessage
from agent_harness.tools.base import ToolExecutionContext
from agent_harness.tools.message import MessageInput, MessageTool


class TestMessageToolSuppressLogic:
    """Final reply suppressed only when message tool sends to the same target."""

    @pytest.mark.asyncio
    async def test_suppress_when_sent_to_same_target(self, tmp_path: Path) -> None:
        """MessageTool tracks whether it sent to the current context this turn."""
        tool = MessageTool(default_channel="feishu", default_chat_id="chat123")
        tool.set_context("feishu", "chat123")

        sent: list[OutboundMessage] = []
        tool.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        result = await tool.execute(
            MessageInput(content="Hello", channel="feishu", chat_id="chat123"),
            ToolExecutionContext(cwd=Path.cwd()),
        )

        assert len(sent) == 1
        assert tool._sent_in_turn is True

    @pytest.mark.asyncio
    async def test_not_suppress_when_sent_to_different_target(self, tmp_path: Path) -> None:
        """Sending to different target should not set _sent_in_turn for current context."""
        tool = MessageTool(default_channel="feishu", default_chat_id="chat123")
        tool.set_context("feishu", "chat123")

        sent: list[OutboundMessage] = []
        tool.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        result = await tool.execute(
            MessageInput(content="Email content", channel="email", chat_id="user@example.com"),
            ToolExecutionContext(cwd=Path.cwd()),
        )

        assert len(sent) == 1
        # Different channel, so not same target
        assert tool._sent_in_turn is False


class TestMessageToolTurnTracking:

    def test_sent_in_turn_tracks_same_target(self) -> None:
        tool = MessageTool()
        tool.set_context("feishu", "chat1")
        assert tool._sent_in_turn is False
        tool._sent_in_turn = True
        assert tool._sent_in_turn is True

    def test_start_turn_resets(self) -> None:
        tool = MessageTool()
        tool._sent_in_turn = True
        tool.start_turn()
        assert tool._sent_in_turn is False
