"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from llm_harness.core.bus.events import OutboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.extensions.channels.base import BaseChannel

logger = logging.getLogger(__name__)

# Retry delays for message sending (exponential backoff: 1s, 2s, 4s)
_SEND_RETRY_DELAYS = (1, 2, 4)


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages
    """

    def __init__(
        self,
        channel_types: dict[str, type[BaseChannel]],
        channels_config: dict[str, Any],
        bus: MessageBus,
        *,
        send_tool_hints: bool = False,
        send_progress: bool = True,
        send_max_retries: int = 3,
    ):
        """
        Args:
            channel_types: Mapping of channel name -> BaseChannel subclass.
            channels_config: Dict with per-channel config keys and top-level settings.
            bus: The message bus for inbound/outbound routing.
            send_tool_hints: Whether to forward tool call progress hints.
            send_progress: Whether to forward generic progress messages.
            send_max_retries: Max send attempts per outbound message.
        """
        self.channel_types = channel_types
        self.channels_config = channels_config
        self.bus = bus
        self.send_tool_hints = send_tool_hints
        self.send_progress = send_progress
        self.send_max_retries = send_max_retries
        self.channels: dict[str, BaseChannel] = {}
        self._channel_tasks: dict[str, asyncio.Task] = {}
        self._dispatch_task: asyncio.Task | None = None

        self._init_channels()

    def _init_channels(self) -> None:
        """Initialize channels from the provided channel_types dict."""
        for name, cls in self.channel_types.items():
            section = self.channels_config.get(name, None)
            if section is None:
                continue
            enabled = (
                section.get("enabled", False)
                if isinstance(section, dict)
                else getattr(section, "enabled", False)
            )
            if not enabled:
                continue
            try:
                channel = cls(section, self.bus)
                self.channels[name] = channel
                logger.info("%s channel enabled", cls.display_name)
            except Exception as e:
                logger.warning("%s channel not available: %s", name, e)

        self._validate_allow_from()

    def _validate_allow_from(self) -> None:
        for name, ch in self.channels.items():
            allow_list = (
                ch.config.get("allow_from", [])
                if isinstance(ch.config, dict)
                else getattr(ch.config, "allow_from", [])
            )
            if not allow_list:
                raise ValueError(
                    f'Error: "{name}" has empty allowFrom (denies all). '
                    f'Set ["*"] to allow everyone, or add specific user IDs.'
                )

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error("Failed to start channel %s: %s", name, e)

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return

        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # Start channels
        for name, channel in self.channels.items():
            logger.info("Starting %s channel...", name)
            task = asyncio.create_task(self._start_channel(name, channel))
            self._channel_tasks[name] = task

        # Wait for all to complete (they should run forever)
        await asyncio.gather(*self._channel_tasks.values(), return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")

        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        # Cancel all channel tasks
        for name, task in self._channel_tasks.items():
            if not task.done():
                task.cancel()

        # Stop all channels (graceful cleanup after cancellation)
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Stopped %s channel", name)
            except Exception as e:
                logger.error("Error stopping %s: %s", name, e)

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0,
                )

                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not self.send_tool_hints:
                        continue
                    if not msg.metadata.get("_tool_hint") and not self.send_progress:
                        continue

                channel = self.channels.get(msg.channel)
                if channel:
                    await self._send_with_retry(channel, msg)
                else:
                    logger.warning("Unknown channel: %s", msg.channel)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    @staticmethod
    async def _send_once(channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send one outbound message without retry policy."""
        if msg.metadata.get("_stream_delta") or msg.metadata.get("_stream_end"):
            await channel.send_delta(msg.chat_id, msg.content, msg.metadata)
        elif not msg.metadata.get("_streamed"):
            await channel.send(msg)

    async def _send_with_retry(self, channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send a message with retry on failure using exponential backoff.

        Note: CancelledError is re-raised to allow graceful shutdown.
        """
        max_attempts = max(self.send_max_retries, 1)

        for attempt in range(max_attempts):
            try:
                await self._send_once(channel, msg)
                return  # Send succeeded
            except asyncio.CancelledError:
                raise  # Propagate cancellation for graceful shutdown
            except Exception as e:
                if attempt == max_attempts - 1:
                    logger.error(
                        "Failed to send to %s after %d attempts: %s - %s",
                        msg.channel, max_attempts, type(e).__name__, e,
                    )
                    return
                delay = _SEND_RETRY_DELAYS[min(attempt, len(_SEND_RETRY_DELAYS) - 1)]
                logger.warning(
                    "Send to %s failed (attempt %d/%d): %s, retrying in %ds",
                    msg.channel, attempt + 1, max_attempts, type(e).__name__, delay,
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    raise  # Propagate cancellation during sleep

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {
                "enabled": True,
                "running": channel.is_running,
            }
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
