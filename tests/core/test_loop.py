"""Tests for AgentLoop — pure ReAct skeleton driven by callbacks."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from llm_harness.core.loop import AgentLoop, TurnResult
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult
from llm_harness.adapters.providers.base import LLMResponse, ToolCallRequest


# ---------------------------------------------------------------------------
# Mock tool classes for testing
# ---------------------------------------------------------------------------

class MockEchoInput(BaseModel):
    text: str


class MockEchoTool(BaseTool):
    name = "echo"
    description = "Echo the input text"
    input_model = MockEchoInput

    async def execute(self, arguments, context):
        return ToolResult(output=f"echo: {arguments.text}")


class MockAddInput(BaseModel):
    x: int
    y: int


class MockAddTool(BaseTool):
    name = "add"
    description = "Add two numbers"
    input_model = MockAddInput

    async def execute(self, arguments, context):
        return ToolResult(output=str(arguments.x + arguments.y))


# ---------------------------------------------------------------------------
# Helper to create a minimal loop
# ---------------------------------------------------------------------------

def _make_loop(provider, tools=None, **kw):
    from llm_harness.core.tools.base import ToolRegistry
    registry = ToolRegistry()
    if tools:
        for t in tools:
            registry.register(t)
    kw.setdefault("on_tool_check", lambda name, tool, args: MagicMock(allowed=True))
    return AgentLoop(
        provider=provider,
        tools=registry,
        model="test-model",
        on_build_context=lambda msg, history: [{"role": "user", "content": msg.content}],
        on_error=lambda exc, ctx: None,
        **kw,
    )


@pytest.mark.asyncio
async def test_basic_text_response():
    """A response with no tool calls returns TurnResult with content."""
    provider = AsyncMock()
    provider.api_format = "openai"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Hello world", tool_calls=[], finish_reason="stop",
    ))

    loop = _make_loop(provider)
    msg = MagicMock(content="hi", session_key="test:session")
    result = await loop.run(msg, [])
    assert isinstance(result, TurnResult)
    assert result.final_content == "Hello world"
    assert result.tools_used == []


@pytest.mark.asyncio
async def test_tool_call_triggers_execution():
    """Tool calls are executed and results appended to messages."""
    provider = AsyncMock()
    provider.api_format = "openai"

    # First call: returns a tool call, second call: returns text
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[
            ToolCallRequest(id="call_1", name="echo", arguments={"text": "hello"}),
        ], finish_reason="tool_calls"),
        LLMResponse(content="Done", tool_calls=[], finish_reason="stop"),
    ])

    loop = _make_loop(provider, tools=[MockEchoTool()])
    msg = MagicMock(content="do it", session_key="test:session")
    result = await loop.run(msg, [])
    assert result.final_content == "Done"
    assert "echo" in result.tools_used
    # Tool result should appear in messages
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert any("echo: hello" in m.get("content", "") for m in tool_msgs)


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    """An unknown tool name produces an error message instead of executing."""
    provider = AsyncMock()
    provider.api_format = "openai"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="", tool_calls=[
            ToolCallRequest(id="call_1", name="nonexistent", arguments={}),
        ], finish_reason="tool_calls",
    ))

    loop = _make_loop(provider, tools=[])
    msg = MagicMock(content="run", session_key="test:session")
    result = await loop.run(msg, [])
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert any("unknown tool" in m.get("content", "").lower() for m in tool_msgs)


@pytest.mark.asyncio
async def test_invalid_tool_args_returns_error():
    """Invalid arguments for a registered tool return an error."""
    provider = AsyncMock()
    provider.api_format = "openai"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="", tool_calls=[
            ToolCallRequest(id="call_1", name="add", arguments={"x": "not_a_number", "y": 2}),
        ], finish_reason="tool_calls",
    ))

    loop = _make_loop(provider, tools=[MockAddTool()])
    msg = MagicMock(content="add", session_key="test:session")
    result = await loop.run(msg, [])
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert any("invalid args" in m.get("content", "").lower() for m in tool_msgs)


@pytest.mark.asyncio
async def test_permission_denied_blocks_tool():
    """When permission check returns not allowed, tool execution is blocked."""
    def deny_check(name, tool, args):
        return MagicMock(allowed=False, reason="blocked")

    provider = AsyncMock()
    provider.api_format = "openai"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="", tool_calls=[
            ToolCallRequest(id="call_1", name="echo", arguments={"text": "hi"}),
        ], finish_reason="tool_calls",
    ))

    loop = _make_loop(provider, tools=[MockEchoTool()],
                      on_tool_check=deny_check)
    msg = MagicMock(content="run", session_key="test:session")
    result = await loop.run(msg, [])
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert any("permission denied" in m.get("content", "").lower() for m in tool_msgs)


@pytest.mark.asyncio
async def test_max_iterations_reached():
    """When tool calls keep coming, loop exits after max_iterations."""
    provider = AsyncMock()
    provider.api_format = "openai"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="", tool_calls=[
            ToolCallRequest(id="call_1", name="echo", arguments={"text": "x"}),
        ], finish_reason="tool_calls",
    ))

    loop = _make_loop(provider, tools=[MockEchoTool()], max_iterations=2)
    msg = MagicMock(content="loop", session_key="test:session")
    result = await loop.run(msg, [])
    assert result.final_content == "Max iterations reached."


@pytest.mark.asyncio
async def test_new_messages_start_set_correctly():
    """new_messages_start points to where new conversation messages begin."""
    provider = AsyncMock()
    provider.api_format = "openai"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Hello", tool_calls=[], finish_reason="stop",
    ))

    loop = _make_loop(provider)
    history = [{"role": "user", "content": "prev msg"}]
    msg = MagicMock(content="current", session_key="test:session")
    result = await loop.run(msg, history)
    assert result.new_messages_start >= 1  # the current user msg + history


@pytest.mark.asyncio
async def test_tool_result_truncation():
    """Tool results longer than TOOL_RESULT_MAX_CHARS are truncated."""
    provider = AsyncMock()
    provider.api_format = "openai"
    long_text = "x" * 20_000

    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="", tool_calls=[
            ToolCallRequest(id="call_1", name="echo", arguments={"text": long_text}),
        ], finish_reason="tool_calls",
    ))

    loop = _make_loop(provider, tools=[MockEchoTool()])
    loop.TOOL_RESULT_MAX_CHARS = 100
    msg = MagicMock(content="run", session_key="test:session")
    result = await loop.run(msg, [])
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert all(len(m.get("content", "")) <= 100 + len("\n... truncated") for m in tool_msgs)
    assert any("truncated" in m.get("content", "") for m in tool_msgs)


@pytest.mark.asyncio
async def test_on_event_callback():
    """on_event callback fires for tool:executing and loop:iteration events."""
    events = []

    async def collector(event, data):
        events.append((event, data))

    provider = AsyncMock()
    provider.api_format = "openai"
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[
            ToolCallRequest(id="call_1", name="echo", arguments={"text": "hi"}),
        ], finish_reason="tool_calls"),
        LLMResponse(content="Done", tool_calls=[], finish_reason="stop"),
    ])

    loop = _make_loop(provider, tools=[MockEchoTool()], on_event=collector)
    msg = MagicMock(content="go", session_key="test:session")
    await loop.run(msg, [])
    event_types = [e[0] for e in events]
    assert "tool:executing" in event_types
    assert "loop:iteration" in event_types
