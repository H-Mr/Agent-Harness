"""Bus event types -- the two fundamental data structures of the system.

InboundMessage:  user/channel -> Agent (input)
OutboundMessage: Agent -> user/channel (output)

session_key is a channel:chat_id composite (e.g. "telegram:123456"),
used to distinguish sessions so same-session messages are serialized
while different sessions can run in parallel.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundMessage:
    """Inbound message -- a message received from a chat channel.

    Sources can be CLI input, Telegram messages, Discord messages, etc.
    Regardless of source, the message is normalized into this structure
    before being published to the bus.
    """

    channel: str           # Source channel: "cli", "telegram", "discord", "slack", etc.
    sender_id: str         # Sender identifier (username or ID)
    chat_id: str           # Session identifier (group chat ID / private chat ID)
    content: str           # Message text content
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)         # Attachment URL list
    metadata: dict[str, Any] = field(default_factory=dict) # Channel-specific data (e.g. _wants_stream)
    session_key_override: str | None = None                # Optional session key override (for threaded sessions)

    @property
    def session_key(self) -> str:
        """Unique session identifier, default format: channel:chat_id.

        Messages with the same session_key are processed sequentially (serial per session);
        messages with different session_keys can be processed concurrently.
        """
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Outbound message -- a message from the Agent to be sent to the user.

    metadata may contain special markers:
    - _stream_delta: streaming content delta
    - _stream_end: streaming end signal
    - _progress: tool call progress hint
    - _tool_hint: whether the progress hint is a tool call info
    """

    channel: str                              # Target channel
    chat_id: str                              # Target session
    content: str                              # Message text
    reply_to: str | None = None               # Optional: reply to a specific message
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)  # Carries streaming/progress markers
