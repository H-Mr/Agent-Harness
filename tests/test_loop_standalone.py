"""Tests for the AgentLoop -- pure ReAct skeleton with concurrency control."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_harness.bus.events import InboundMessage, OutboundMessage
from agent_harness.loop.agent import AgentLoop, LoopCallbacks, TurnResult
from agent_harness.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)


# ============================================================================
# Mock Provider
# ============================================================================


@dataclass
class _MockProvider(LLMProvider):
    """A provider that returns canned responses in sequence.

    Each call to chat/chat_stream pops the next response from `responses`.
    """

    responses: list[LLMResponse] = field(default_factory=list)
    default_model: str = "mock-model"
    generation: GenerationSettings = field(default_factory=GenerationSettings)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="mock reply", finish_reason="stop")

    def get_default_model(self) -> str:
        return self.default_model


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_callbacks():
    """Create LoopCallbacks with AsyncMock functions."""
    build_messages = AsyncMock(
        side_effect=lambda msg: [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": msg.content},
        ]
    )
    execute_tool = AsyncMock(
        side_effect=lambda name, args: f"executed {name} with {args}"
    )
    get_tool_definitions = MagicMock(return_value=[])
    return LoopCallbacks(
        build_messages=build_messages,
        execute_tool=execute_tool,
        get_tool_definitions=get_tool_definitions,
    )


@pytest.fixture
def mock_provider():
    """Create an empty mock provider -- tests add their own responses."""
    return _MockProvider()


@pytest.fixture
def loop(mock_provider, mock_callbacks):
    """Create an AgentLoop with mock dependencies."""
    return AgentLoop(
        provider=mock_provider,
        callbacks=mock_callbacks,
        max_iterations=10,
        max_concurrent=3,
    )


# ============================================================================
# Tests: run_react_loop
# ============================================================================


class TestRunReactLoop:
    """Tests for the core ReAct loop."""

    async def test_text_only_response(self, loop, mock_provider):
        """LLM returns text directly -- loop should complete in one iteration."""
        mock_provider.responses = [
            LLMResponse(content="Hello, world!", finish_reason="stop"),
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "Say hello"}]
        )
        assert result.final_content == "Hello, world!"
        assert result.tools_used == []
        assert len(result.messages) == 2  # user + assistant
        # Assistant message should be appended
        assert result.messages[-1]["role"] == "assistant"
        assert result.messages[-1]["content"] == "Hello, world!"

    async def test_single_tool_then_text(self, loop, mock_provider, mock_callbacks):
        """LLM calls one tool, then returns text."""
        mock_callbacks.get_tool_definitions.return_value = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                },
            }
        ]
        mock_provider.responses = [
            # Response 1: tool call
            LLMResponse(
                content="Let me search for that.",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="web_search",
                        arguments={"query": "current weather"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            # Response 2: final text
            LLMResponse(
                content="The weather is sunny.",
                finish_reason="stop",
            ),
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "What is the weather?"}]
        )
        assert result.final_content == "The weather is sunny."
        assert result.tools_used == ["web_search"]
        # Tool should have been called with correct args
        mock_callbacks.execute_tool.assert_awaited_once_with(
            "web_search", {"query": "current weather"}
        )
        # Messages should include: user, assistant(tool_calls), tool, assistant(final)
        assert len(result.messages) == 4
        assert result.messages[1]["role"] == "assistant"
        assert "tool_calls" in result.messages[1]
        assert result.messages[2]["role"] == "tool"
        assert result.messages[3]["role"] == "assistant"
        assert result.messages[3]["content"] == "The weather is sunny."

    async def test_multiple_concurrent_tools(self, loop, mock_provider, mock_callbacks):
        """LLM calls multiple tools in one response -- they execute concurrently."""
        mock_callbacks.get_tool_definitions.return_value = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                },
            }
        ]
        mock_provider.responses = [
            LLMResponse(
                content="Using multiple tools.",
                tool_calls=[
                    ToolCallRequest(id="c1", name="search", arguments={"q": "a"}),
                    ToolCallRequest(id="c2", name="search", arguments={"q": "b"}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="Done.", finish_reason="stop"),
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "test"}]
        )
        assert result.final_content == "Done."
        assert result.tools_used == ["search", "search"]
        assert mock_callbacks.execute_tool.await_count == 2

    async def test_max_iterations_reached(self, loop, mock_provider):
        """LLM keeps calling tools and never returns text."""
        mock_provider.responses = [
            LLMResponse(
                content="Calling tool...",
                tool_calls=[
                    ToolCallRequest(
                        id="call_x",
                        name="search",
                        arguments={"q": "keep going"},
                    )
                ],
                finish_reason="tool_calls",
            )
            for _ in range(loop.max_iterations + 1)
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "loop forever"}]
        )
        assert result.final_content is not None
        assert "maximum iterations" in result.final_content.lower()
        assert result.final_content != "Sorry, I encountered an error."

    async def test_finish_reason_error(self, loop, mock_provider):
        """LLM returns an error -- loop should return error message."""
        mock_provider.responses = [
            LLMResponse(
                content="API error occurred",
                finish_reason="error",
            ),
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "trigger error"}]
        )
        assert result.final_content is not None
        assert "error" in result.final_content.lower()

    async def test_token_usage_tracked(self, loop, mock_provider):
        """Token usage is captured in TurnResult."""
        mock_provider.responses = [
            LLMResponse(
                content="Hello!",
                finish_reason="stop",
                usage={"prompt_tokens": 50, "completion_tokens": 10},
            ),
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "hi"}]
        )
        assert result.usage["prompt_tokens"] == 50
        assert result.usage["completion_tokens"] == 10

    async def test_tool_execution_error(self, loop, mock_provider, mock_callbacks):
        """A tool that raises an exception is handled gracefully."""
        mock_callbacks.get_tool_definitions.return_value = [
            {
                "type": "function",
                "function": {
                    "name": "failing_tool",
                    "description": "Always fails",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            }
        ]
        mock_callbacks.execute_tool = AsyncMock(
            side_effect=ValueError("Something went wrong")
        )
        mock_provider.responses = [
            LLMResponse(
                content="Let me try...",
                tool_calls=[
                    ToolCallRequest(
                        id="call_fail",
                        name="failing_tool",
                        arguments={},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="I see the error, let me fix it.",
                finish_reason="stop",
            ),
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "use tool"}]
        )
        assert result.final_content == "I see the error, let me fix it."
        assert "failing_tool" in result.tools_used
        # The tool result message should contain the error
        tool_msg = result.messages[2]
        assert tool_msg["role"] == "tool"
        assert "Error" in tool_msg["content"]
        assert "ValueError" in tool_msg["content"]

    async def test_empty_response_content(
        self, loop, mock_provider
    ):
        """LLM returns content=None but no tool_calls -- should handle gracefully."""
        mock_provider.responses = [
            LLMResponse(content=None, finish_reason="stop"),
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "say nothing"}]
        )
        # Content is None, but loop should still complete
        assert result.final_content is None
        assert len(result.messages) == 2

    async def test_streaming_callbacks(
        self, loop, mock_provider, mock_callbacks
    ):
        """When streaming callbacks are provided, chat_stream_with_retry is used."""
        on_stream = AsyncMock()
        on_stream_end = AsyncMock()
        mock_callbacks.on_stream = on_stream
        mock_callbacks.on_stream_end = on_stream_end
        mock_callbacks.get_tool_definitions.return_value = []
        mock_provider.responses = [
            LLMResponse(content="Streamed reply", finish_reason="stop"),
        ]
        result = await loop.run_react_loop(
            [{"role": "user", "content": "stream this"}]
        )
        assert result.final_content == "Streamed reply"
        # on_stream_end should be called with resuming=False
        on_stream_end.assert_awaited_once_with(resuming=False)


# ============================================================================
# Tests: process_message (concurrency)
# ============================================================================


class TestProcessMessage:
    """Tests for message processing with concurrency control."""

    async def test_basic_message_flow(self, loop, mock_provider):
        """InboundMessage -> process_message -> OutboundMessage."""
        mock_provider.responses = [
            LLMResponse(content="Reply from agent", finish_reason="stop"),
        ]
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="Hello!",
        )
        result = await loop.process_message(msg)
        assert result is not None
        assert result.content == "Reply from agent"
        assert result.channel == "cli"
        assert result.chat_id == "direct"

    async def test_concurrent_sessions_do_not_block_each_other(
        self, loop, mock_provider
    ):
        """Messages from different sessions process concurrently."""
        mock_provider.responses = [
            LLMResponse(content="Reply A", finish_reason="stop"),
            LLMResponse(content="Reply B", finish_reason="stop"),
        ]
        msg_a = InboundMessage(
            channel="cli", sender_id="alice", chat_id="session_a", content="Hi"
        )
        msg_b = InboundMessage(
            channel="cli", sender_id="bob", chat_id="session_b", content="Hi"
        )
        results = await asyncio.gather(
            loop.process_message(msg_a),
            loop.process_message(msg_b),
        )
        contents = {r.content for r in results if r is not None}
        assert "Reply A" in contents
        assert "Reply B" in contents

    async def test_same_session_serial(self, loop, mock_provider):
        """Messages from the same session run serially due to per-session Lock."""
        # Both responses are the same because they'll come in order
        mock_provider.responses = [
            LLMResponse(content="First", finish_reason="stop"),
            LLMResponse(content="Second", finish_reason="stop"),
        ]
        msg1 = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="First message",
        )
        msg2 = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="Second message",
        )
        # Run both concurrently but they share session_key -> serial
        results = await asyncio.gather(
            loop.process_message(msg1),
            loop.process_message(msg2),
        )
        # Same session, so they complete in order
        assert results[0] is not None and results[0].content == "First"
        assert results[1] is not None and results[1].content == "Second"

    async def test_cancelled_error_bubbles(self, loop, mock_provider):
        """CancelledError should propagate (not be caught by the generic handler)."""
        # Use an event to make build_messages hang so we can cancel deterministically
        hang_event = asyncio.Event()

        async def hanging_build_messages(msg):
            await hang_event.wait()  # hangs until we set it
            return [
                {"role": "system", "content": "test"},
                {"role": "user", "content": msg.content},
            ]

        loop.callbacks.build_messages = hanging_build_messages
        mock_provider.responses = [
            LLMResponse(content="ok", finish_reason="stop"),
        ]

        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="cancel me",
        )

        async def _cancel_after_start():
            task = asyncio.create_task(loop.process_message(msg))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        await _cancel_after_start()
        # Unblock the hanging coroutine so it can be garbage collected cleanly
        hang_event.set()
        await asyncio.sleep(0.01)

    async def test_exception_returns_error_message(self, loop, mock_provider):
        """Unexpected exceptions produce a friendly error OutboundMessage."""
        mock_provider.responses = [
            LLMResponse(content="ok", finish_reason="stop"),
        ]
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="trigger error",
        )
        # Make build_messages raise
        loop.callbacks.build_messages = AsyncMock(
            side_effect=RuntimeError("Unexpected failure")
        )
        result = await loop.process_message(msg)
        assert result is not None
        assert "error" in result.content.lower()


# ============================================================================
# Tests: process_direct
# ============================================================================


class TestProcessDirect:
    """Tests for the one-shot direct processing."""

    async def test_direct_processing(self, loop, mock_provider):
        """process_direct runs the ReAct loop without a bus."""
        mock_provider.responses = [
            LLMResponse(content="Direct reply", finish_reason="stop"),
        ]
        result = await loop.process_direct("Hello, agent!")
        assert isinstance(result, TurnResult)
        assert result.final_content == "Direct reply"

    async def test_direct_with_tool_call(self, loop, mock_provider, mock_callbacks):
        """process_direct with tool call then text."""
        mock_callbacks.get_tool_definitions.return_value = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                },
            }
        ]
        mock_provider.responses = [
            LLMResponse(
                content="Searching...",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1", name="search", arguments={"q": "test"}
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="Found results.", finish_reason="stop"),
        ]
        result = await loop.process_direct("Search something")
        assert result.final_content == "Found results."
        assert result.tools_used == ["search"]


# ============================================================================
# Tests: Helpers
# ============================================================================


class TestHelpers:
    """Tests for static helper methods."""

    def test_tool_hint_simple(self):
        tc = ToolCallRequest(
            id="1", name="web_search", arguments={"query": "hello"}
        )
        hint = AgentLoop._tool_hint([tc])
        assert 'web_search("hello")' in hint

    def test_tool_hint_long_arg(self):
        tc = ToolCallRequest(
            id="1",
            name="web_search",
            arguments={"query": "a" * 50},
        )
        hint = AgentLoop._tool_hint([tc])
        assert "..." in hint

    def test_tool_hint_no_string_arg(self):
        tc = ToolCallRequest(
            id="1", name="calculator", arguments={"x": 42, "y": 7}
        )
        hint = AgentLoop._tool_hint([tc])
        assert hint == "calculator"

    def test_tool_hint_multiple_tools(self):
        tcs = [
            ToolCallRequest(
                id="1", name="search", arguments={"q": "weather"}
            ),
            ToolCallRequest(
                id="2", name="read_file", arguments={"path": "/tmp/x"}
            ),
        ]
        hint = AgentLoop._tool_hint(tcs)
        assert 'search("weather")' in hint
        assert 'read_file("/tmp/x")' in hint

    def test_build_assistant_msg_no_tool_calls(self):
        response = LLMResponse(content="Hello")
        msg = AgentLoop._build_assistant_msg(response)
        assert msg["role"] == "assistant"
        assert msg["content"] == "Hello"
        assert "tool_calls" not in msg

    def test_build_assistant_msg_with_tool_calls(self):
        response = LLMResponse(content="Thinking...")
        tcs = [{"id": "1", "type": "function", "function": {"name": "test", "arguments": "{}"}}]
        msg = AgentLoop._build_assistant_msg(response, tcs)
        assert msg["role"] == "assistant"
        assert msg["content"] == "Thinking..."
        assert msg["tool_calls"] == tcs

    def test_build_assistant_msg_no_content(self):
        response = LLMResponse(content=None)
        msg = AgentLoop._build_assistant_msg(response)
        assert msg["role"] == "assistant"
        assert "content" not in msg
