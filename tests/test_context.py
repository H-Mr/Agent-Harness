"""Tests for agent_harness.context.base."""

from __future__ import annotations

import pytest

from agent_harness.context.base import ContextBuilder, SectionProvider


class TestSectionProvider:
    """SectionProvider ABC tests."""

    def test_default_priority(self):
        """Default priority should be 100."""
        provider = _make_provider("test", "hello")
        assert provider.priority == 100

    def test_section_name_required(self):
        """section_name must be implemented."""
        provider = _make_provider("my-section", "content")
        assert provider.section_name == "my-section"


class TestContextBuilder:
    """ContextBuilder tests."""

    @pytest.mark.asyncio
    async def test_empty_build(self):
        """Building with no providers should return empty string."""
        builder = ContextBuilder()
        result = await builder.build_system_prompt()
        assert result == ""

    @pytest.mark.asyncio
    async def test_single_provider(self):
        """A single provider should produce its section."""
        builder = ContextBuilder()
        builder.add_provider(_make_provider("instructions", "Do the thing."))
        result = await builder.build_system_prompt()
        assert "Do the thing." in result

    @pytest.mark.asyncio
    async def test_multiple_providers(self):
        """Multiple providers should be joined by separators."""
        builder = ContextBuilder()
        builder.add_provider(_make_provider("a", "Section A"))
        builder.add_provider(_make_provider("b", "Section B"))
        result = await builder.build_system_prompt()
        assert "Section A" in result
        assert "Section B" in result
        assert "---" in result

    @pytest.mark.asyncio
    async def test_priority_order(self):
        """Providers should be ordered by priority (lower = earlier)."""
        builder = ContextBuilder()
        high = _make_provider("high", "HIGH", priority=50)
        low = _make_provider("low", "LOW", priority=200)
        builder.add_provider(high)
        builder.add_provider(low)
        result = await builder.build_system_prompt()
        high_idx = result.index("HIGH")
        low_idx = result.index("LOW")
        assert high_idx < low_idx

    @pytest.mark.asyncio
    async def test_remove_provider(self):
        """Removing a provider should exclude its section."""
        builder = ContextBuilder()
        builder.add_provider(_make_provider("keep", "KEEP"))
        builder.add_provider(_make_provider("remove", "REMOVE"))
        builder.remove_provider("remove")
        result = await builder.build_system_prompt()
        assert "KEEP" in result
        assert "REMOVE" not in result

    @pytest.mark.asyncio
    async def test_empty_sections_skipped(self):
        """Providers returning empty strings should be skipped."""
        builder = ContextBuilder()
        builder.add_provider(_make_provider("empty", ""))
        builder.add_provider(_make_provider("nonempty", "CONTENT"))
        result = await builder.build_system_prompt()
        assert result == "CONTENT"

    @pytest.mark.asyncio
    async def test_build_messages_basic(self):
        """build_messages should produce a standard message list."""
        builder = ContextBuilder()
        msgs = builder.build_messages(
            system_prompt="You are a bot.",
            history=[],
            current_message="Hello!",
        )
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "You are a bot."}
        assert msgs[1]["role"] == "user"
        assert "Hello!" in msgs[1]["content"]

    @pytest.mark.asyncio
    async def test_build_messages_with_history(self):
        """History messages should appear between system and user."""
        builder = ContextBuilder()
        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        msgs = builder.build_messages(
            system_prompt="sys",
            history=history,
            current_message="Next question",
        )
        assert len(msgs) == 4
        assert msgs[0]["role"] == "system"
        assert msgs[1] == history[0]
        assert msgs[2] == history[1]
        assert msgs[3]["role"] == "user"

    @pytest.mark.asyncio
    async def test_build_messages_with_channel_context(self):
        """Channel/chat_id should be prepended to the user message."""
        builder = ContextBuilder()
        msgs = builder.build_messages(
            system_prompt="sys",
            history=[],
            current_message="Hello!",
            channel="test-channel",
            chat_id="chat-123",
        )
        user_content: str = msgs[1]["content"]
        assert "Current time:" in user_content
        assert "test-channel" in user_content
        assert "chat-123" in user_content
        assert "Hello!" in user_content

    def test_add_tool_result(self):
        """add_tool_result should append a tool message."""
        msgs = [{"role": "user", "content": "hi"}]
        result = ContextBuilder.add_tool_result(msgs, "call-1", "read_file", "file content")
        assert len(result) == 2
        assert result[1] == {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "read_file",
            "content": "file content",
        }

    def test_add_assistant_message_content_only(self):
        """add_assistant_message with just content."""
        msgs = []
        result = ContextBuilder.add_assistant_message(msgs, "Hello!")
        assert len(result) == 1
        assert result[0] == {"role": "assistant", "content": "Hello!"}

    def test_add_assistant_message_with_tool_calls(self):
        """add_assistant_message with tool calls."""
        msgs = []
        tool_calls = [{"id": "call-1", "function": {"name": "read_file"}}]
        result = ContextBuilder.add_assistant_message(msgs, None, tool_calls=tool_calls)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["tool_calls"] == tool_calls
        assert "content" not in result[0]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_provider(name: str, content: str, *, priority: int = 100) -> SectionProvider:
    """Create a simple SectionProvider for testing."""

    class _TestProvider(SectionProvider):
        @property
        def section_name(self) -> str:
            return name

        @property
        def priority(self) -> int:
            return priority

        async def get_section(self) -> str:
            return content

    return _TestProvider()
