"""Integration test: Agent triggers consolidation via MessageCountPolicy."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_harness.agent import Agent
from agent_harness.bus.events import InboundMessage
from agent_harness.harness import Harness
from agent_harness.memory.policy import MessageCountPolicy
from agent_harness.memory.store import MemoryStore
from agent_harness.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from agent_harness.session.manager import SessionManager


class _ConsolidationMockProvider(LLMProvider):
    """Mock provider: returns save_memory when consolidating, read_file tool calls, then text."""

    def __init__(self):
        super().__init__(api_key="mock")
        self.consolidation_calls = 0
        self.read_file_calls = 0

    async def chat(self, messages, tools=None, model=None, **kwargs):
        # If tools include "save_memory", this is consolidation call
        if tools and any(
            t.get("function", {}).get("name") == "save_memory" for t in (tools or [])
        ):
            self.consolidation_calls += 1
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="mem_1",
                        name="save_memory",
                        arguments={
                            "agents_update": None,
                            "soul_update": None,
                            "memory_update": "Test: user asked a question.",
                            "user_update": None,
                            "history_entry": "[2026-05-27 10:00] Test session",
                        },
                    )
                ],
                finish_reason="tool_calls",
            )

        self.read_file_calls += 1
        if self.read_file_calls <= 2:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "/tmp/test.txt"},
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            content="I've completed the task.",
            finish_reason="stop",
        )

    async def chat_stream(self, messages, tools=None, model=None, on_content_delta=None, **kwargs):
        return await self.chat(messages, tools, model, **kwargs)

    def get_default_model(self):
        return "mock-model"


@pytest.mark.asyncio
async def test_agent_with_message_count_policy_triggers_consolidation(tmp_path):
    """Agent with MessageCountPolicy(max_messages=6) triggers consolidation after 6+ msgs."""
    workspace = tmp_path / "workspace"
    memory_dir = workspace / "memory"
    sessions_dir = workspace / "sessions"

    harness = Harness(
        provider=_ConsolidationMockProvider(),
        memory=memory_dir,
        sessions=SessionManager(workspace),
        tools=[],
    )

    agent = Agent(
        harness,
        model="mock-model",
        consolidation_policy=MessageCountPolicy(max_messages=6),
    )

    msg = InboundMessage(
        channel="cli", sender_id="user", chat_id="c1",
        content="test message",
    )

    result = await agent.process(msg)
    assert result is not None
    assert result.content == "I've completed the task."


@pytest.mark.asyncio
async def test_agent_default_policy_still_works(tmp_path):
    """Agent without explicit policy (default TokenBudgetPolicy) still functions."""
    workspace = tmp_path / "workspace"

    harness = Harness(
        provider=_ConsolidationMockProvider(),
        memory=workspace / "memory",
        sessions=SessionManager(workspace),
        tools=[],
    )

    agent = Agent(harness, model="mock-model")

    msg = InboundMessage(
        channel="cli", sender_id="user", chat_id="c2",
        content="hello",
    )

    result = await agent.process(msg)
    assert result is not None
    assert result.content == "I've completed the task."


@pytest.mark.asyncio
async def test_agent_without_sessions_skips_consolidation(tmp_path):
    """Agent without sessions config skips consolidation entirely (no crash)."""
    harness = Harness(
        provider=_ConsolidationMockProvider(),
        memory=None,
        sessions=None,
        tools=[],
    )

    agent = Agent(harness, model="mock-model")

    msg = InboundMessage(
        channel="cli", sender_id="user", chat_id="c3",
        content="hello",
    )

    result = await agent.process(msg)
    assert result is not None
    assert result.content == "I've completed the task."
