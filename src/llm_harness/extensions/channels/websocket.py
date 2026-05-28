"""WebSocket channel stub."""

from __future__ import annotations

from typing import Any

from llm_harness.core.bus.events import OutboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.extensions.channels.base import BaseChannel


class WebSocketChannel(BaseChannel):
    """WebSocket-based channel stub."""

    name = "websocket"
    display_name = "WebSocket"

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        pass
