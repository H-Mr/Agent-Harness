"""Tests for agent orchestration tools — AgentTool, SendMessageTool, TaskStopTool, AskUserQuestionTool."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_harness.core.tools.base import ToolExecutionContext, ToolResult
from llm_harness.core.tools.agent import AgentTool, AgentInput
from llm_harness.core.tools.send_message import SendMessageTool, SendMessageInput
from llm_harness.core.tools.task_stop import TaskStopTool, TaskStopInput
from llm_harness.core.tools.ask_user import AskUserQuestionTool, AskUserQuestionToolInput
from llm_harness.core.swarm.backend import SpawnResult
from llm_harness.core.swarm.definitions import (
    AgentDefinition,
    list_definitions,
    register_definition,
)


ctx = ToolExecutionContext(cwd=Path("/workspace"), metadata={"session_key": "test:session"})


# ---------------------------------------------------------------------------
# AgentTool
# ---------------------------------------------------------------------------

class TestAgentTool:
    @pytest.mark.asyncio
    async def test_spawns_sub_agent_via_backend(self):
        """AgentTool.execute calls swarm.spawn with a SpawnConfig."""
        swarm = AsyncMock()
        swarm.spawn = AsyncMock(return_value=SpawnResult(agent_id="agent-abc", success=True))
        bus = MagicMock()
        tool = AgentTool(swarm=swarm, bus=bus, harness_tool_names=["read_file", "exec"])
        result = await tool.execute(
            AgentInput(name="general-purpose", prompt="do something"), ctx,
        )
        assert isinstance(result, ToolResult)
        assert "Agent spawned" in result.output
        assert "agent-abc" in result.output
        swarm.spawn.assert_called_once()
        config = swarm.spawn.call_args[0][0]
        assert config.agent_name == "general-purpose"
        assert config.prompt == "do something"

    @pytest.mark.asyncio
    async def test_unknown_agent_definition_returns_error(self):
        """An unknown agent name returns an error ToolResult."""
        swarm = AsyncMock()
        tool = AgentTool(swarm=swarm, bus=MagicMock())
        result = await tool.execute(
            AgentInput(name="nonexistent", prompt="hi"), ctx,
        )
        assert result.is_error is True
        assert "Unknown" in result.output

    @pytest.mark.asyncio
    async def test_spawn_failure_returns_error(self):
        """When swarm.spawn returns success=False, an error is returned."""
        swarm = AsyncMock()
        swarm.spawn = AsyncMock(return_value=SpawnResult(
            agent_id="", success=False, error="backend down",
        ))
        tool = AgentTool(swarm=swarm, bus=MagicMock())
        result = await tool.execute(
            AgentInput(name="general-purpose", prompt="x"), ctx,
        )
        assert result.is_error is True
        assert "backend down" in result.output

    @pytest.mark.asyncio
    async def test_passes_session_key_as_origin(self):
        """The session_key from context metadata is passed as origin_session_key."""
        swarm = AsyncMock()
        swarm.spawn = AsyncMock(return_value=SpawnResult(agent_id="a1", success=True))
        tool = AgentTool(swarm=swarm, bus=MagicMock())
        await tool.execute(AgentInput(name="general-purpose", prompt="x"), ctx)
        swarm.spawn.assert_called_once()
        _, kwargs = swarm.spawn.call_args
        assert kwargs.get("origin_session_key") == "test:session"

    @pytest.mark.asyncio
    async def test_error_message_includes_custom_agent_names(self):
        """Error message for unknown agent must show dynamically registered names."""
        # Register a custom agent definition
        register_definition(AgentDefinition(
            name="my-custom-agent",
            description="A custom agent for testing",
            system_prompt="You are custom.",
        ))

        swarm = AsyncMock()
        tool = AgentTool(swarm=swarm, bus=MagicMock())
        result = await tool.execute(
            AgentInput(name="nonexistent", prompt="hi"), ctx,
        )

        assert result.is_error is True
        # Error message should include the dynamically registered agent
        assert "my-custom-agent" in result.output

        # Cleanup: list_definitions() is a live view so we need to remove it
        from llm_harness.core.swarm.definitions import _BUILTIN
        _BUILTIN.pop("my-custom-agent", None)


# ---------------------------------------------------------------------------
# SendMessageTool
# ---------------------------------------------------------------------------

class TestSendMessageTool:
    @pytest.mark.asyncio
    async def test_sends_message_to_running_agent(self):
        """SendMessageTool delegates to swarm.send_message."""
        swarm = AsyncMock()
        swarm.send_message = AsyncMock(return_value=True)
        tool = SendMessageTool(swarm=swarm)
        result = await tool.execute(
            SendMessageInput(agent_id="agent-abc", message="hello"), ctx,
        )
        assert isinstance(result, ToolResult)
        assert "Message sent" in result.output
        swarm.send_message.assert_called_once_with("agent-abc", "hello")

    @pytest.mark.asyncio
    async def test_unknown_agent_returns_error(self):
        """When swarm.send_message returns False, an error is returned."""
        swarm = AsyncMock()
        swarm.send_message = AsyncMock(return_value=False)
        tool = SendMessageTool(swarm=swarm)
        result = await tool.execute(
            SendMessageInput(agent_id="gone", message="hi"), ctx,
        )
        assert result.is_error is True
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# TaskStopTool
# ---------------------------------------------------------------------------

class TestTaskStopTool:
    @pytest.mark.asyncio
    async def test_stops_running_agent(self):
        """TaskStopTool delegates to swarm.stop."""
        swarm = AsyncMock()
        swarm.stop = AsyncMock(return_value=True)
        tool = TaskStopTool(swarm=swarm)
        result = await tool.execute(TaskStopInput(agent_id="agent-abc"), ctx)
        assert isinstance(result, ToolResult)
        assert "Stopped" in result.output
        swarm.stop.assert_called_once_with("agent-abc")

    @pytest.mark.asyncio
    async def test_unknown_agent_returns_error(self):
        """When swarm.stop returns False, an error is returned."""
        swarm = AsyncMock()
        swarm.stop = AsyncMock(return_value=False)
        tool = TaskStopTool(swarm=swarm)
        result = await tool.execute(TaskStopInput(agent_id="gone"), ctx)
        assert result.is_error is True
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# AskUserQuestionTool
# ---------------------------------------------------------------------------

class TestAskUserQuestionTool:
    @pytest.mark.asyncio
    async def test_forwards_question_to_callback(self):
        """AskUserQuestionTool invokes the ask_user callback with the question."""
        async def callback(q):
            return "user answer"
        tool = AskUserQuestionTool(ask_user=callback)
        result = await tool.execute(
            AskUserQuestionToolInput(question="What is your name?"), ctx,
        )
        assert isinstance(result, ToolResult)
        assert result.output == "user answer"

    @pytest.mark.asyncio
    async def test_no_callback_returns_error(self):
        """When no callback is configured, an error is returned."""
        tool = AskUserQuestionTool()
        result = await tool.execute(
            AskUserQuestionToolInput(question="Are you there?"), ctx,
        )
        assert result.is_error is True
        assert "unavailable" in result.output.lower()

    @pytest.mark.asyncio
    async def test_set_callback_at_runtime(self):
        """set_callback allows injecting the callback after construction."""
        tool = AskUserQuestionTool()
        async def callback(q):
            return "runtime answer"
        tool.set_callback(callback)
        result = await tool.execute(
            AskUserQuestionToolInput(question="What?"), ctx,
        )
        assert result.output == "runtime answer"

    def test_is_read_only_true(self):
        """AskUserQuestionTool is read-only."""
        tool = AskUserQuestionTool()
        assert tool.is_read_only(AskUserQuestionToolInput(question="x")) is True
