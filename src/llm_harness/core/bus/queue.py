"""Async message queue for decoupled channel-agent communication."""

import asyncio
import logging

from llm_harness.core.bus.events import InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)
_MAX_QUEUE_SIZE = 10_000


class MessageBus:
    """In-process async message queue for decoupled channel-agent communication."""

    def __init__(self, maxsize: int = _MAX_QUEUE_SIZE):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Enqueue a message from a channel for the agent to process."""
        try:
            await self.inbound.put(msg)
        except asyncio.QueueFull:
            logger.error("Inbound queue full, dropping message from %s", msg.sender_id)

    async def consume_inbound(self) -> InboundMessage:
        """Dequeue the next inbound message (blocks until one is available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Enqueue a message from the agent for a channel to deliver."""
        try:
            await self.outbound.put(msg)
        except asyncio.QueueFull:
            logger.error("Outbound queue full, dropping message to %s/%s", msg.channel, msg.chat_id)

    async def consume_outbound(self) -> OutboundMessage:
        """Dequeue the next outbound message (blocks until one is available)."""
        return await self.outbound.get()
