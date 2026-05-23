"""Message tool for sending messages to users.

Ported from nanobot.agent.tools.message with interface adapted to agent-harness BaseTool.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from agent_harness.bus.events import OutboundMessage
from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class MessageInput(BaseModel):
    """Input model for the message tool."""

    content: str = Field(description="The message content to send")
    channel: str | None = Field(default=None, description="Optional: target channel")
    chat_id: str | None = Field(default=None, description="Optional: target chat/user ID")
    media: list[str] = Field(default_factory=list, description="Optional: file paths to attach")


class MessageTool(BaseTool):
    """Tool to send messages to users on chat channels."""

    name = "message"
    description = (
        "Send a message to the user, optionally with file attachments. "
        "This is the ONLY way to deliver files (images, documents, audio, video) to the user. "
        "Use the 'media' parameter with file paths to attach files. "
        "Do NOT use read_file to send files -- that only reads content for your own analysis."
    )
    input_model = MessageInput

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id
        self._sent_in_turn: bool = False

    def set_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Set the current message context."""
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    def start_turn(self) -> None:
        """Reset per-turn send tracking."""
        self._sent_in_turn = False

    async def execute(self, arguments: MessageInput, context: ToolExecutionContext) -> ToolResult:
        """Execute the message tool."""
        channel = arguments.channel or self._default_channel
        chat_id = arguments.chat_id or self._default_chat_id

        if not channel or not chat_id:
            return ToolResult(output="Error: No target channel/chat specified", is_error=True)

        if not self._send_callback:
            return ToolResult(output="Error: Message sending not configured", is_error=True)

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=arguments.content,
            media=arguments.media,
            metadata={
                "message_id": self._default_message_id,
            },
        )

        try:
            await self._send_callback(msg)
            if channel == self._default_channel and chat_id == self._default_chat_id:
                self._sent_in_turn = True
            media_info = f" with {len(arguments.media)} attachments" if arguments.media else ""
            return ToolResult(output=f"Message sent to {channel}:{chat_id}{media_info}")
        except Exception as e:
            return ToolResult(output=f"Error sending message: {e}", is_error=True)
