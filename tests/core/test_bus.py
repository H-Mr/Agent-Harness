"""Tests for MessageBus — async message queue for channel-agent communication."""

import pytest
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.bus.events import InboundMessage, OutboundMessage


@pytest.mark.asyncio
async def test_publish_inbound_round_trip():
    """Publish an InboundMessage then consume it and verify fields."""
    bus = MessageBus()
    msg = InboundMessage(
        channel="test",
        sender_id="user1",
        chat_id="chat1",
        content="hello",
        metadata={"key": "val"},
    )
    await bus.publish_inbound(msg)
    consumed = await bus.consume_inbound()
    assert consumed.channel == "test"
    assert consumed.sender_id == "user1"
    assert consumed.chat_id == "chat1"
    assert consumed.content == "hello"
    assert consumed.metadata == {"key": "val"}


@pytest.mark.asyncio
async def test_publish_outbound_round_trip():
    """Publish an OutboundMessage then consume it and verify fields."""
    bus = MessageBus()
    msg = OutboundMessage(
        channel="test",
        chat_id="chat1",
        content="response",
        reply_to="msg_1",
    )
    await bus.publish_outbound(msg)
    consumed = await bus.consume_outbound()
    assert consumed.channel == "test"
    assert consumed.chat_id == "chat1"
    assert consumed.content == "response"
    assert consumed.reply_to == "msg_1"


@pytest.mark.asyncio
async def test_multiple_messages_in_order():
    """Multiple inbound messages are consumed in FIFO order."""
    bus = MessageBus()
    for i in range(5):
        msg = InboundMessage(
            channel="ch", sender_id="s", chat_id="c",
            content=f"msg_{i}",
        )
        await bus.publish_inbound(msg)

    for i in range(5):
        consumed = await bus.consume_inbound()
        assert consumed.content == f"msg_{i}"


@pytest.mark.asyncio
async def test_publish_is_non_blocking():
    """Publishing to an empty queue should not block."""
    bus = MessageBus()
    msg = InboundMessage(
        channel="ch", sender_id="s", chat_id="c", content="hello",
    )
    # This should return immediately (no await needed for put on unbounded queue)
    await bus.publish_inbound(msg)
    # If we got here without hanging, the test passes
    assert True
