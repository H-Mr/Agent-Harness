"""Tests for structured observability events emitted during the agent loop."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from agent_harness.loop.agent import AgentLoop, LoopCallbacks, TurnResult
from agent_harness.observability.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from agent_harness.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult


# ============================================================================
# Test tools
# ============================================================================


class EchoInput(BaseModel):
    msg: str = ""


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo a message"
    input_model = EchoInput

    async def execute(self, arguments: EchoInput, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"ECHO: {arguments.msg}")


class FailingInput(BaseModel):
    reason: str = ""


class FailingTool(BaseTool):
    name = "failing"
    description = "Always fails"
    input_model = FailingInput

    async def execute(self, arguments: FailingInput, context: ToolExecutionContext) -> ToolResult:
        raise RuntimeError(arguments.reason)


# ============================================================================
# Helpers
# ============================================================================


def _make_tools() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(EchoTool())
    tools.register(FailingTool())
    return tools


async def _execute_tool(tools: ToolRegistry, name: str, args: dict, *, catch_errors: bool = True) -> str:
    tool = tools.get(name)
    if tool is None:
        return f"Error: tool '{name}' not found"
    try:
        parsed = tool.input_model.model_validate(args)
        result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
        return result.output
    except Exception as e:
        if catch_errors:
            return f"Error: {e}"
        raise


def _make_callbacks(tools, *, on_event=None):
    return LoopCallbacks(
        build_messages=lambda msg: [
            {"role": "system", "content": "test"},
            {"role": "user", "content": msg.content},
        ],
        execute_tool=lambda name, args: _execute_tool(tools, name, args),
        get_tool_definitions=lambda: tools.to_api_schema("openai"),
        on_event=on_event,
    )


# ============================================================================
# Tests
# ============================================================================


class TestToolExecutionEvents:
    """ToolExecutionStarted and ToolExecutionCompleted are emitted."""

    async def test_started_and_completed_emitted(self):
        events: list[StreamEvent] = []

        async def collect(e): events.append(e)

        provider = _make_mock([
            # turn 1: call echo
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="echo", arguments={"msg": "hello"})],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
            # turn 2: final text
            LLMResponse(content="Done", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])

        tools = _make_tools()
        loop = AgentLoop(provider, _make_callbacks(tools, on_event=collect))

        await loop.process_direct("echo hello")

        started = [e for e in events if isinstance(e, ToolExecutionStarted)]
        completed = [e for e in events if isinstance(e, ToolExecutionCompleted)]

        assert len(started) == 1
        assert started[0].tool_name == "echo"
        assert started[0].tool_input == {"msg": "hello"}

        assert len(completed) == 1
        assert completed[0].tool_name == "echo"
        assert "ECHO: hello" in completed[0].output
        assert completed[0].is_error is False
        assert completed[0].duration_ms is not None
        assert completed[0].duration_ms >= 0

    async def test_concurrent_tool_events(self):
        events: list[StreamEvent] = []

        async def collect(e): events.append(e)

        provider = _make_mock([
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="echo", arguments={"msg": "a"}),
                    ToolCallRequest(id="c2", name="echo", arguments={"msg": "b"}),
                ],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 5},
            ),
            LLMResponse(content="ok", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])

        tools = _make_tools()
        loop = AgentLoop(provider, _make_callbacks(tools, on_event=collect))

        await loop.process_direct("echo a and b")

        started = [e for e in events if isinstance(e, ToolExecutionStarted)]
        completed = [e for e in events if isinstance(e, ToolExecutionCompleted)]

        assert len(started) == 2
        assert len(completed) == 2

    async def test_tool_error_event(self):
        events: list[StreamEvent] = []

        async def collect(e): events.append(e)

        provider = _make_mock([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="failing", arguments={"reason": "boom"})],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
            LLMResponse(content="Handled error", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])

        tools = _make_tools()
        # catch_errors=False: let exceptions propagate to the loop so it sets is_error=True
        cbs = LoopCallbacks(
            build_messages=lambda msg: [
                {"role": "system", "content": "test"},
                {"role": "user", "content": msg.content},
            ],
            execute_tool=lambda name, args: _execute_tool(tools, name, args, catch_errors=False),
            get_tool_definitions=lambda: tools.to_api_schema("openai"),
            on_event=collect,
        )
        loop = AgentLoop(provider, cbs)

        await loop.process_direct("fail")

        completed = [e for e in events if isinstance(e, ToolExecutionCompleted)]
        assert len(completed) == 1
        assert completed[0].tool_name == "failing"
        assert completed[0].is_error is True


class TestTurnCompleteEvent:
    """AssistantTurnComplete is emitted on final text response."""

    async def test_turn_complete_emitted(self):
        events: list[StreamEvent] = []

        async def collect(e): events.append(e)

        provider = _make_mock([
            LLMResponse(content="Hello!", usage={"prompt_tokens": 10, "completion_tokens": 5}),
        ])

        tools = _make_tools()
        loop = AgentLoop(provider, _make_callbacks(tools, on_event=collect))

        await loop.process_direct("hi")

        complete = [e for e in events if isinstance(e, AssistantTurnComplete)]
        assert len(complete) == 1
        assert complete[0].content == "Hello!"
        assert complete[0].usage["prompt_tokens"] == 10

    async def test_error_event_emitted(self):
        events: list[StreamEvent] = []

        async def collect(e): events.append(e)

        provider = _make_mock([
            LLMResponse(
                content="API error occurred",
                finish_reason="error",
                usage={"prompt_tokens": 5, "completion_tokens": 0},
            ),
        ])

        tools = _make_tools()
        loop = AgentLoop(provider, _make_callbacks(tools, on_event=collect))

        await loop.process_direct("hi")

        errors = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(errors) == 1
        assert "API error" in errors[0].message
        assert errors[0].recoverable is True


class TestNoCallback:
    """When on_event is None, no errors occur."""

    async def test_no_on_event_does_not_crash(self):
        provider = _make_mock([
            LLMResponse(content="ok", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = _make_tools()
        loop = AgentLoop(provider, _make_callbacks(tools, on_event=None))

        result = await loop.process_direct("hi")
        assert result.final_content == "ok"


class TestEventBusAndTracker:
    """Events pushed to bus → consumed by tracker → written to JSONL file."""

    async def test_emit_to_bus_and_consume(self):
        from agent_harness.observability.bus import EventBus
        from agent_harness.observability.events import ToolExecutionStarted

        bus = EventBus()
        events_received: list[object] = []

        async def drain():
            while len(events_received) < 3:
                events_received.append(await bus.consume())

        task = asyncio.create_task(drain())
        await bus.emit(ToolExecutionStarted("tool_a", {"x": 1}))
        await bus.emit(ToolExecutionStarted("tool_b", {"y": 2}))
        await bus.emit(ToolExecutionStarted("tool_c", {"z": 3}))
        await task

        assert len(events_received) == 3
        names = [e.tool_name for e in events_received]
        assert names == ["tool_a", "tool_b", "tool_c"]

    async def test_tracker_writes_jsonl(self, tmp_path):
        from agent_harness.observability.bus import EventBus
        from agent_harness.observability.events import (
            SessionOpened,
            ToolExecutionCompleted,
            AssistantTurnComplete,
        )
        from agent_harness.observability.tracker import Tracker

        # Isolated bus — not the global singleton
        bus = EventBus()
        track_path = tmp_path / "track.jsonl"
        tracker = Tracker(track_path, bus=bus)
        await tracker.start()
        await bus.emit(SessionOpened("cli:test"))
        await bus.emit(ToolExecutionStarted("echo", {"msg": "hi"}))
        await bus.emit(ToolExecutionCompleted("echo", "ECHO: hi", duration_ms=1.5))
        await bus.emit(AssistantTurnComplete("Done", {"prompt_tokens": 10, "completion_tokens": 5}))

        # Small delay to let the tracker drain
        await asyncio.sleep(0.1)
        await tracker.stop()

        lines = track_path.read_text().strip().split("\n")
        assert len(lines) == 4

        import json
        records = [json.loads(line) for line in lines]
        types = [r["type"] for r in records]
        assert types == [
            "SessionOpened",
            "ToolExecutionStarted",
            "ToolExecutionCompleted",
            "AssistantTurnComplete",
        ]
        # Verify ToolExecutionCompleted has duration
        assert records[2]["data"]["duration_ms"] == 1.5
        # Verify AssistantTurnComplete has usage
        assert records[3]["data"]["usage"]["prompt_tokens"] == 10

    async def test_tracker_no_events_does_not_crash(self, tmp_path):
        from agent_harness.observability.bus import EventBus
        from agent_harness.observability.tracker import Tracker

        bus = EventBus()
        tracker = Tracker(tmp_path / "empty.jsonl", bus=bus)
        await tracker.start()
        await asyncio.sleep(0.1)
        await tracker.stop()

        assert (tmp_path / "empty.jsonl").exists()


# ============================================================================
# Helpers
# ============================================================================


def _make_mock(responses: list[LLMResponse]) -> LLMProvider:
    class Mock(LLMProvider):
        def __init__(self):
            super().__init__(api_key="mock")
            self._responses = responses
            self._i = 0

        def get_default_model(self):
            return "mock"

        async def chat(self, messages, tools=None, model=None, max_tokens=4096,
                       temperature=0.7, reasoning_effort=None, tool_choice=None):
            r = self._responses[self._i]
            self._i += 1
            return r

    return Mock()
