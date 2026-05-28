"""Chat channel abstractions and management."""

from llm_harness.extensions.channels.base import BaseChannel
from llm_harness.extensions.channels.cli import CLIChannel
from llm_harness.extensions.channels.http import HTTPChannel
from llm_harness.extensions.channels.websocket import WebSocketChannel
from llm_harness.extensions.channels.wechat import WeChatChannel
from llm_harness.extensions.channels.feishu import FeishuChannel
from llm_harness.extensions.channels.manager import ChannelManager

__all__ = [
    "BaseChannel",
    "CLIChannel",
    "HTTPChannel",
    "WebSocketChannel",
    "WeChatChannel",
    "FeishuChannel",
    "ChannelManager",
]
