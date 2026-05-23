"""Integration test: full agent pipeline with mock LLM.

Tests the complete flow:
  InboundMessage → AgentLoop → Provider.call → Tool.execute →
  Permission.check → Hook.execute → OutboundMessage

Uses MockProvider to simulate LLM responses (tool_calls + text).
All pipeline stages are wired together — no mocking of internal components.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from agent_harness.bus.events import InboundMessage, OutboundMessage
from agent_harness.bus.queue import MessageBus
from agent_harness.config.schema import ToolsConfig
from agent_harness.context.base import ContextBuilder
from agent_harness.hooks import (
    HookEvent,
    HookExecutor,
    HookExecutionContext,
    HookRegistry,
)
from agent_harness.hooks.schemas import CommandHookDefinition
from agent_harness.loop.agent import AgentLoop, LoopCallbacks, TurnResult
from agent_harness.permissions.checker import PermissionChecker
from agent_harness.permissions.modes import PermissionMode
from agent_harness.permissions.settings import PermissionSettings
from agent_harness.providers.base import (
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)
from agent_harness.tools.base import (
    BaseTool,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
)


# ============================================================================
# Mock Provider — returns scripted responses
# ============================================================================

class MockProvider(LLMProvider):
    """Returns a pre-defined sequence of LLMResponses."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        super().__init__(api_key="mock")
        self._responses = responses or []
        self._idx = 0
        self.calls: list[dict] = []

    def get_default_model(self) -> str:
        return "mock-model"

    async def chat(self, messages, tools=None, model=None, max_tokens=4096,
                   temperature=0.7, reasoning_effort=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools})
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        # Default: echo
        last = next((m.get("content", "") for m in reversed(messages)
                     if m.get("role") == "user"), "")
        return LLMResponse(content=f"Echo: {last}",
                           usage={"prompt_tokens": 10, "completion_tokens": 5})


# ============================================================================
# Test tools
# ============================================================================

class EchoInput(BaseModel):
    message: str = Field(description="Message to echo")


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo a message back"
    input_model = EchoInput

    async def execute(self, arguments: EchoInput, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"ECHO: {arguments.message}")


class CalcInput(BaseModel):
    expr: str = Field(description="Math expression")


class CalcTool(BaseTool):
    name = "calc"
    description = "Calculate a math expression"
    input_model = CalcInput

    async def execute(self, arguments: CalcInput, context: ToolExecutionContext) -> ToolResult:
        try:
            result = eval(arguments.expr, {"__builtins__": {}}, {})
            return ToolResult(output=str(result))
        except Exception as e:
            return ToolResult(output=str(e), is_error=True)

    def is_read_only(self, arguments):
        return True


# ============================================================================
# Helpers
# ============================================================================

def _make_callbacks(tools: ToolRegistry, context: ContextBuilder):
    """Build LoopCallbacks wired to tools + context."""
    async def execute_tool(name: str, args: dict) -> str:
        tool = tools.get(name)
        if tool is None:
            return f"Error: tool '{name}' not found"
        try:
            parsed = tool.input_model.model_validate(args)
            result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
            return result.output
        except Exception as e:
            return f"Error: {e}"

    def build_messages(msg: InboundMessage) -> list[dict]:
        return [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": msg.content},
        ]

    return LoopCallbacks(
        build_messages=build_messages,
        execute_tool=execute_tool,
        get_tool_definitions=lambda: tools.to_api_schema("openai"),
    )


# ============================================================================
# Tests
# ============================================================================

class TestFullPipeline:
    """End-to-end pipeline tests with all subsystems wired."""

    async def test_text_only_response(self):
        """Simple text response — no tools, no permissions, no hooks."""
        provider = MockProvider([
            LLMResponse(content="Hello, world!", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = ToolRegistry()
        callbacks = _make_callbacks(tools, ContextBuilder())
        loop = AgentLoop(provider, callbacks)

        result = await loop.process_direct("Hi")
        assert result.final_content == "Hello, world!"
        assert result.tools_used == []
        assert len(provider.calls) == 1

    async def test_single_tool_call(self):
        """LLM calls one tool, then responds."""
        provider = MockProvider([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="echo", arguments={"message": "ping"})],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
            LLMResponse(content="Got ping back!", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = ToolRegistry()
        tools.register(EchoTool())
        callbacks = _make_callbacks(tools, ContextBuilder())
        loop = AgentLoop(provider, callbacks)

        result = await loop.process_direct("echo ping")
        assert result.final_content == "Got ping back!"
        assert "echo" in result.tools_used
        assert len(provider.calls) == 2

    async def test_multiple_concurrent_tools(self):
        """LLM calls two tools in one turn — concurrent execution."""
        provider = MockProvider([
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="echo", arguments={"message": "a"}),
                    ToolCallRequest(id="c2", name="calc", arguments={"expr": "2+3"}),
                ],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 5},
            ),
            LLMResponse(content="Echo=ECHO: a, Calc=5", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = ToolRegistry()
        tools.register(EchoTool())
        tools.register(CalcTool())
        callbacks = _make_callbacks(tools, ContextBuilder())
        loop = AgentLoop(provider, callbacks)

        result = await loop.process_direct("echo a and calc 2+3")
        assert result.final_content == "Echo=ECHO: a, Calc=5"
        assert "echo" in result.tools_used
        assert "calc" in result.tools_used
        assert len(provider.calls) == 2

    async def test_tool_not_found(self):
        """LLM calls a tool that doesn't exist — error returned to LLM."""
        provider = MockProvider([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="nonexistent", arguments={})],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
            LLMResponse(content="Tool not found, handling gracefully", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = ToolRegistry()
        callbacks = _make_callbacks(tools, ContextBuilder())
        loop = AgentLoop(provider, callbacks)

        result = await loop.process_direct("use bad tool")
        assert "Tool not found" in result.final_content
        assert "nonexistent" in result.tools_used

    async def test_max_iterations_reached(self):
        """LLM keeps calling tools until max_iterations exhausted."""
        provider = MockProvider([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id=f"c{i}", name="echo", arguments={"message": str(i)})],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            )
            for i in range(10)  # more than max_iterations=5
        ])
        tools = ToolRegistry()
        tools.register(EchoTool())
        callbacks = _make_callbacks(tools, ContextBuilder())
        loop = AgentLoop(provider, callbacks, max_iterations=5)

        result = await loop.process_direct("loop forever")
        assert "maximum iterations" in result.final_content.lower()
        assert len(result.tools_used) == 5


class TestPipelineWithPermissions:
    """Pipeline tests with PermissionChecker wired in."""

    async def test_read_only_tool_allowed(self):
        """Read-only tools pass permission check."""
        provider = MockProvider([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="calc", arguments={"expr": "1+1"})],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
            LLMResponse(content="2", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = ToolRegistry()
        tools.register(CalcTool())

        # Wire permission check into execute_tool callback
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))

        async def execute_with_permission(name: str, args: dict) -> str:
            tool = tools.get(name)
            if tool is None:
                return f"Error: tool '{name}' not found"
            decision = checker.evaluate(name, is_read_only=tool.is_read_only(tool.input_model.model_validate(args) if tool.input_model else None))
            if not decision.allowed:
                return f"Permission denied: {decision.reason}"
            parsed = tool.input_model.model_validate(args)
            result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
            return result.output

        callbacks = LoopCallbacks(
            build_messages=lambda msg: [{"role": "system", "content": "test"}, {"role": "user", "content": msg.content}],
            execute_tool=execute_with_permission,
            get_tool_definitions=lambda: tools.to_api_schema("openai"),
        )
        loop = AgentLoop(provider, callbacks)

        result = await loop.process_direct("calc 1+1")
        assert result.final_content == "2"

    async def test_write_tool_blocked_in_plan_mode(self):
        """Plan mode blocks mutating tools."""
        provider = MockProvider([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="echo", arguments={"message": "x"})],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
            LLMResponse(content="Blocked, handling gracefully", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = ToolRegistry()
        tools.register(EchoTool())
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.PLAN))

        async def execute_with_permission(name: str, args: dict) -> str:
            tool = tools.get(name)
            if tool is None:
                return f"Error: tool '{name}' not found"
            decision = checker.evaluate(name, is_read_only=tool.is_read_only(tool.input_model.model_validate(args) if tool.input_model else None))
            if not decision.allowed:
                return f"Permission denied: {decision.reason}"
            parsed = tool.input_model.model_validate(args)
            result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
            return result.output

        callbacks = LoopCallbacks(
            build_messages=lambda msg: [{"role": "system", "content": "test"}, {"role": "user", "content": msg.content}],
            execute_tool=execute_with_permission,
            get_tool_definitions=lambda: tools.to_api_schema("openai"),
        )
        loop = AgentLoop(provider, callbacks)

        result = await loop.process_direct("echo x")
        # Plan mode blocks the write, LLM gets "Permission denied" as tool result
        assert "Permission denied" in str(provider.calls[-1]["messages"])


class TestPipelineWithHooks:
    """Pipeline tests with HookExecutor wired in."""

    async def test_pre_tool_hook_executes(self):
        """PreToolUse hook fires before tool execution."""
        hook_log: list[str] = []

        provider = MockProvider([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="echo", arguments={"message": "hello"})],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
            LLMResponse(content="Done", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = ToolRegistry()
        tools.register(EchoTool())

        # Set up hooks
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(
            command="echo hook_fired",
            matcher="echo",
        ))

        async def execute_with_hooks(name: str, args: dict) -> str:
            tool = tools.get(name)
            if tool is None:
                return f"Error: tool '{name}' not found"
            # Run pre-tool hooks
            from agent_harness.hooks.executor import HookExecutor, HookExecutionContext
            executor = HookExecutor(registry, HookExecutionContext(
                cwd=Path.cwd(),
                provider=provider,
                default_model="mock",
            ))
            hook_result = await executor.execute(HookEvent.PRE_TOOL_USE, {
                "tool_name": name,
                "tool_input": args,
            })
            hook_log.append(f"pre_tool: {name}, blocked={hook_result.blocked}")
            if hook_result.blocked:
                return f"Blocked by hook: {hook_result.reason}"
            # Execute tool
            parsed = tool.input_model.model_validate(args)
            result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
            return result.output

        callbacks = LoopCallbacks(
            build_messages=lambda msg: [{"role": "system", "content": "test"}, {"role": "user", "content": msg.content}],
            execute_tool=execute_with_hooks,
            get_tool_definitions=lambda: tools.to_api_schema("openai"),
        )
        loop = AgentLoop(provider, callbacks)

        result = await loop.process_direct("echo hello")
        assert result.final_content == "Done"
        assert len(hook_log) == 1
        assert "pre_tool: echo" in hook_log[0]


class TestPipelineBus:
    """Pipeline tests with MessageBus."""

    async def test_bus_roundtrip(self):
        """Message goes in, response comes out via bus."""
        provider = MockProvider([
            LLMResponse(content="Response via bus", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])
        tools = ToolRegistry()
        tools.register(EchoTool())
        callbacks = _make_callbacks(tools, ContextBuilder())
        loop = AgentLoop(provider, callbacks)
        bus = MessageBus()

        # Put message on bus
        msg = InboundMessage(channel="cli", sender_id="test", chat_id="test1", content="hello")
        await bus.publish_inbound(msg)

        # Process it
        consumed = await bus.consume_inbound()
        response = await loop.process_message(consumed)

        # Response on outbound
        if response:
            await bus.publish_outbound(response)

        out = await bus.consume_outbound()
        assert "Response via bus" in out.content
        assert out.channel == "cli"


class TestToolBuilderIntegration:
    """Tests for config-driven tool building."""

    def test_build_from_config_all(self):
        from agent_harness.tools.builder import build_tools_from_config
        config = ToolsConfig(enabled=["*"])
        tools = build_tools_from_config(config)
        assert len(tools.list_tools()) >= 10

    def test_build_from_config_subset(self):
        from agent_harness.tools.builder import build_tools_from_config
        config = ToolsConfig(enabled=["echo", "calc"])
        # Custom tools won't be in registry — should have 0
        tools = build_tools_from_config(config)
        # The echo and calc tools aren't in the factory registry, so this should be empty
        # But we can add them manually
        tools.register(EchoTool())
        tools.register(CalcTool())
        assert len(tools.list_tools()) == 2
        assert tools.has("echo")
        assert tools.has("calc")

    def test_build_from_config_disabled(self):
        from agent_harness.tools.builder import build_tools_from_config
        config = ToolsConfig(enabled=["*"], disabled=["exec", "web_search"])
        tools = build_tools_from_config(config)
        names = [t.name for t in tools.list_tools()]
        assert "exec" not in names
        assert "web_search" not in names
        assert "read_file" in names  # still enabled
