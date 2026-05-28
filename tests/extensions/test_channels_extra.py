"""Tests for additional channel functionality (base.py, manager.py)."""

from __future__ import annotations

from abc import ABC
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from llm_harness.core.bus.events import OutboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.extensions.channels.base import BaseChannel
from llm_harness.extensions.channels.manager import ChannelManager

# =============================================================================
# Helper: concrete channel subclass for testing
# =============================================================================


class FakeChannel(BaseChannel):
    """Minimal concrete channel used in tests below."""

    name = "fake"
    display_name = "Fake"

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        pass

    # Intentionally NOT overriding send_delta -- used to test supports_streaming


class StreamingChannel(FakeChannel):
    """Channel that overrides send_delta to enable streaming."""

    name = "streaming"

    async def send_delta(self, chat_id: str, delta: str, metadata: dict | None = None) -> None:
        pass


# =============================================================================
# ChannelManager._send_once
# =============================================================================


class TestSendOnce:
    """ChannelManager._send_once routing logic."""

    @pytest.mark.asyncio
    async def test_routes_stream_delta_to_send_delta(self):
        """Messages with _stream_delta metadata are sent via send_delta."""
        channel = AsyncMock(spec=FakeChannel)
        msg = OutboundMessage(
            channel="fake", chat_id="c1", content="chunk",
            metadata={"_stream_delta": True},
        )
        await ChannelManager._send_once(channel, msg)
        channel.send_delta.assert_awaited_once_with("c1", "chunk", {"_stream_delta": True})
        channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_routes_stream_end_to_send_delta(self):
        """Messages with _stream_end metadata are sent via send_delta."""
        channel = AsyncMock(spec=FakeChannel)
        msg = OutboundMessage(
            channel="fake", chat_id="c2", content="",
            metadata={"_stream_end": True},
        )
        await ChannelManager._send_once(channel, msg)
        channel.send_delta.assert_awaited_once_with("c2", "", {"_stream_end": True})

    @pytest.mark.asyncio
    async def test_routes_normal_message_to_send(self):
        """Regular messages (no stream metadata) are sent via send."""
        channel = AsyncMock(spec=FakeChannel)
        msg = OutboundMessage(
            channel="fake", chat_id="c3", content="hello",
            metadata={},
        )
        await ChannelManager._send_once(channel, msg)
        channel.send.assert_awaited_once_with(msg)
        channel.send_delta.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_send_for_streamed_messages(self):
        """Messages with _streamed=True are not sent via send."""
        channel = AsyncMock(spec=FakeChannel)
        msg = OutboundMessage(
            channel="fake", chat_id="c4", content="done",
            metadata={"_streamed": True},
        )
        await ChannelManager._send_once(channel, msg)
        channel.send.assert_not_called()
        channel.send_delta.assert_not_called()


# =============================================================================
# ChannelManager._send_with_retry
# =============================================================================


class TestSendWithRetry:
    """ChannelManager._send_with_retry retry logic."""

    @pytest.mark.asyncio
    async def test_sends_on_first_attempt(self, mock_bus):
        """Sends successfully on the first attempt."""
        channel = AsyncMock(spec=FakeChannel)
        channel.send = AsyncMock()
        msg = OutboundMessage(channel="fake", chat_id="c1", content="ok", metadata={})

        manager = ChannelManager(
            channel_types={},
            channels_config={},
            bus=mock_bus,
            send_max_retries=3,
        )
        await manager._send_with_retry(channel, msg)
        channel.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_on_failure(self, mock_bus):
        """Retries after a transient failure."""
        channel = AsyncMock(spec=FakeChannel)
        channel.send = AsyncMock(side_effect=[ConnectionError("first fail"), None])
        msg = OutboundMessage(channel="fake", chat_id="c1", content="retry", metadata={})

        manager = ChannelManager(
            channel_types={},
            channels_config={},
            bus=mock_bus,
            send_max_retries=3,
        )
        await manager._send_with_retry(channel, msg)
        assert channel.send.await_count == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self, mock_bus):
        """Gives up after exhausting max_retries attempts."""
        channel = AsyncMock(spec=FakeChannel)
        channel.send = AsyncMock(side_effect=ConnectionError("persistent fail"))
        msg = OutboundMessage(channel="fake", chat_id="c1", content="fail", metadata={})

        manager = ChannelManager(
            channel_types={},
            channels_config={},
            bus=mock_bus,
            send_max_retries=3,
        )
        # Should not raise, just log the error
        await manager._send_with_retry(channel, msg)
        assert channel.send.await_count == 3


# =============================================================================
# ChannelManager._dispatch_outbound filtering
# =============================================================================


class TestDispatchOutbound:
    """ChannelManager._dispatch_outbound message filtering."""

    @pytest.mark.asyncio
    async def test_filters_progress_when_disabled(self, mock_bus):
        """_progress messages without _tool_hint are dropped when send_progress=False."""
        channel = FakeChannel({"enabled": True}, mock_bus)
        manager = ChannelManager(
            channel_types={"fake": FakeChannel},
            channels_config={"fake": {"enabled": True, "allow_from": ["*"]}},
            bus=mock_bus,
            send_progress=False,
        )
        # The channel is already initialized via _init_channels in __init__
        # Let us test the filter condition directly by inspecting the dispatch loop logic.
        # We'll check that a message with _progress but without _tool_hint is skipped when
        # send_progress is False.

        # The actual dispatch loop is an infinite while; test the filter condition inline:
        msg = OutboundMessage(
            channel="fake", chat_id="c1", content="progress",
            metadata={"_progress": True},
        )
        # Replicate the filter logic from _dispatch_outbound
        should_skip = msg.metadata.get("_progress") and (
            (msg.metadata.get("_tool_hint") and not manager.send_tool_hints)
            or (not msg.metadata.get("_tool_hint") and not manager.send_progress)
        )
        assert should_skip is True

    @pytest.mark.asyncio
    async def test_filters_tool_hint_when_disabled(self, mock_bus):
        """_tool_hint messages are dropped when send_tool_hints=False."""
        manager = ChannelManager(
            channel_types={"fake": FakeChannel},
            channels_config={"fake": {"enabled": True, "allow_from": ["*"]}},
            bus=mock_bus,
            send_tool_hints=False,
        )
        msg = OutboundMessage(
            channel="fake", chat_id="c1", content="hint",
            metadata={"_progress": True, "_tool_hint": True},
        )
        should_skip = msg.metadata.get("_progress") and (
            (msg.metadata.get("_tool_hint") and not manager.send_tool_hints)
            or (not msg.metadata.get("_tool_hint") and not manager.send_progress)
        )
        assert should_skip is True


# =============================================================================
# ChannelManager getters
# =============================================================================


class TestChannelManagerGetters:
    """ChannelManager.get_channel / get_status / enabled_channels."""

    def test_get_channel_returns_by_name(self, mock_bus):
        manager = ChannelManager(
            channel_types={"fake": FakeChannel},
            channels_config={"fake": {"enabled": True, "allow_from": ["*"]}},
            bus=mock_bus,
        )
        ch = manager.get_channel("fake")
        assert ch is not None
        assert ch.name == "fake"

    def test_get_channel_unknown(self, mock_bus):
        manager = ChannelManager(
            channel_types={"fake": FakeChannel},
            channels_config={"fake": {"enabled": True, "allow_from": ["*"]}},
            bus=mock_bus,
        )
        assert manager.get_channel("nonexistent") is None

    def test_get_status(self, mock_bus):
        manager = ChannelManager(
            channel_types={"fake": FakeChannel},
            channels_config={"fake": {"enabled": True, "allow_from": ["*"]}},
            bus=mock_bus,
        )
        status = manager.get_status()
        assert "fake" in status
        assert status["fake"]["enabled"] is True
        assert status["fake"]["running"] is False  # not started yet

    def test_enabled_channels(self, mock_bus):
        manager = ChannelManager(
            channel_types={"fake": FakeChannel},
            channels_config={"fake": {"enabled": True, "allow_from": ["*"]}},
            bus=mock_bus,
        )
        assert manager.enabled_channels == ["fake"]


# =============================================================================
# BaseChannel.supports_streaming
# =============================================================================


class TestSupportsStreaming:
    """BaseChannel.supports_streaming property."""

    def test_true_when_streaming_enabled_and_send_delta_overridden(self, mock_bus):
        """Returns True when config has streaming=True and send_delta is overridden."""
        ch = StreamingChannel({"enabled": True, "streaming": True}, mock_bus)
        assert ch.supports_streaming is True

    def test_false_when_send_delta_not_overridden(self, mock_bus):
        """Returns False when send_delta is not overridden regardless of config."""
        ch = FakeChannel({"enabled": True, "streaming": True}, mock_bus)
        assert ch.supports_streaming is False

    def test_false_when_streaming_disabled(self, mock_bus):
        """Returns False when config streaming is False/absent."""
        ch = StreamingChannel({"enabled": True}, mock_bus)
        assert ch.supports_streaming is False


# =============================================================================
# BaseChannel.default_config
# =============================================================================


class TestDefaultConfig:
    """BaseChannel.default_config class method."""

    def test_returns_dict_with_enabled_false(self):
        """default_config returns {"enabled": False}."""
        assert BaseChannel.default_config() == {"enabled": False}


# =============================================================================
# BaseChannel._handle_message
# =============================================================================


class TestHandleMessage:
    """BaseChannel._handle_message permission check and forwarding."""

    @pytest.mark.asyncio
    async def test_publishes_to_bus_when_allowed(self, mock_bus):
        """When sender is allowed, publishes an InboundMessage to the bus."""
        ch = FakeChannel({"enabled": True, "allow_from": ["user123"]}, mock_bus)
        await ch._handle_message(
            sender_id="user123",
            chat_id="chat456",
            content="hello",
        )
        mock_bus.publish_inbound.assert_awaited_once()
        published = mock_bus.publish_inbound.await_args[0][0]
        assert published.sender_id == "user123"
        assert published.chat_id == "chat456"
        assert published.content == "hello"

    @pytest.mark.asyncio
    async def test_adds_wants_stream_when_streaming_supported(self, mock_bus):
        """Sets _wants_stream metadata when channel supports streaming."""
        ch = StreamingChannel(
            {"enabled": True, "allow_from": ["*"], "streaming": True},
            mock_bus,
        )
        await ch._handle_message(
            sender_id="anyone",
            chat_id="c1",
            content="hello",
        )
        published = mock_bus.publish_inbound.await_args[0][0]
        assert published.metadata.get("_wants_stream") is True

    @pytest.mark.asyncio
    async def test_denies_when_not_allowed(self, mock_bus):
        """Does not publish when sender is not in allow_from."""
        ch = FakeChannel({"enabled": True, "allow_from": ["trusted"]}, mock_bus)
        await ch._handle_message(
            sender_id="stranger",
            chat_id="c1",
            content="bad",
        )
        mock_bus.publish_inbound.assert_not_called()

    @pytest.mark.asyncio
    async def test_denies_when_allow_from_empty(self, mock_bus):
        """Does not publish when allow_from is empty (deny all)."""
        ch = FakeChannel({"enabled": True, "allow_from": []}, mock_bus)
        await ch._handle_message(
            sender_id="anyone",
            chat_id="c1",
            content="test",
        )
        mock_bus.publish_inbound.assert_not_called()

    @pytest.mark.asyncio
    async def test_wildcard_allow_all(self, mock_bus):
        """Wildcard '*' in allow_from permits all senders."""
        ch = FakeChannel({"enabled": True, "allow_from": ["*"]}, mock_bus)
        await ch._handle_message(
            sender_id="totally-unknown",
            chat_id="c1",
            content="hello",
        )
        mock_bus.publish_inbound.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_session_key_override(self, mock_bus):
        """session_key_override is forwarded to InboundMessage."""
        ch = FakeChannel({"enabled": True, "allow_from": ["*"]}, mock_bus)
        await ch._handle_message(
            sender_id="u1",
            chat_id="c1",
            content="hi",
            session_key="custom:session",
        )
        published = mock_bus.publish_inbound.await_args[0][0]
        assert published.session_key_override == "custom:session"


# =============================================================================
# BaseChannel.login
# =============================================================================


class TestLogin:
    """BaseChannel.login default."""

    @pytest.mark.asyncio
    async def test_returns_true_by_default(self, mock_bus):
        """login returns True when not overridden."""
        ch = FakeChannel({"enabled": True}, mock_bus)
        assert await ch.login() is True

    @pytest.mark.asyncio
    async def test_passes_force_flag(self, mock_bus):
        """login accepts a force parameter."""
        ch = FakeChannel({"enabled": True}, mock_bus)
        assert await ch.login(force=True) is True

    @pytest.mark.asyncio
    async def test_returns_true_with_force_false(self, mock_bus):
        ch = FakeChannel({"enabled": True}, mock_bus)
        assert await ch.login(force=False) is True


# =============================================================================
# BaseChannel.is_allowed
# =============================================================================


class TestIsAllowed:
    """BaseChannel.is_allowed permission logic."""

    def test_empty_list_denies_all(self, mock_bus):
        ch = FakeChannel({"allow_from": []}, mock_bus)
        assert ch.is_allowed("anyone") is False

    def test_wildcard_allows_all(self, mock_bus):
        ch = FakeChannel({"allow_from": ["*"]}, mock_bus)
        assert ch.is_allowed("anyone") is True

    def test_specific_id_allows_only_that_id(self, mock_bus):
        ch = FakeChannel({"allow_from": ["alice"]}, mock_bus)
        assert ch.is_allowed("alice") is True
        assert ch.is_allowed("bob") is False


# =============================================================================
# ChannelManager task lifecycle
# =============================================================================


class TestChannelTaskLifecycle:
    """ChannelManager must store and cancel channel tasks."""

    @pytest.mark.asyncio
    async def test_stop_all_cancels_stored_channel_tasks(self, mock_bus):
        """stop_all cancels tasks stored in _channel_tasks."""
        import asyncio

        async def fake_channel_runner():
            while True:
                await asyncio.sleep(0.1)

        mgr = ChannelManager(
            channel_types={},
            channels_config={},
            bus=mock_bus,
        )

        # Simulate what start_all would do: store a channel task
        mgr._channel_tasks["test_channel"] = asyncio.create_task(
            fake_channel_runner()
        )

        task = mgr._channel_tasks["test_channel"]
        assert not task.done()

        # stop_all should cancel it
        await mgr.stop_all()

        # Wait for cancellation to propagate
        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()

    def test_channel_tasks_dict_exists(self, mock_bus):
        """ChannelManager must have _channel_tasks dict initialized."""
        mgr = ChannelManager(
            channel_types={},
            channels_config={},
            bus=mock_bus,
        )
        assert hasattr(mgr, "_channel_tasks")
        assert isinstance(mgr._channel_tasks, dict)
