"""Chat channel abstractions and management."""

from llm_harness.extensions.channels.base import BaseChannel
from llm_harness.extensions.channels.cli import CLIChannel
from llm_harness.extensions.channels.websocket import WebSocketChannel
from llm_harness.extensions.channels.manager import ChannelManager

__all__ = [
    "BaseChannel",
    "CLIChannel",
    "WebSocketChannel",
    "ChannelManager",
]
