"""CLI channel — standard input/output based channel with lifecycle hooks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from llm_harness.core.bus.events import OutboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.extensions.channels.base import BaseChannel

logger = logging.getLogger(__name__)


class CLIChannel(BaseChannel):
    """Channel that reads from stdin and writes to stdout.

    on_connect fires on start, on_disconnect fires on exit.
    """

    name = "cli"
    display_name = "CLI"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)

    async def start(self) -> None:
        """Start the CLI channel (fires on_connect lifecycle hook)."""
        self._running = True
        await self.on_connect("cli:stdin")
        logger.info("CLI channel started")

        # Read lines from stdin
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, input)
                if not self._running:
                    break
                await self._handle_message(
                    sender_id="user",
                    chat_id="cli",
                    content=line,
                )
            except EOFError:
                break
            except KeyboardInterrupt:
                break

    async def stop(self) -> None:
        """Stop the CLI channel (fires on_disconnect lifecycle hook)."""
        self._running = False
        await self.on_disconnect("cli:stdin")
        logger.info("CLI channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Write an outbound message to stdout."""
        print(msg.content)
        await self.on_message(msg)
