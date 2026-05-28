"""Tests for swarm module — agent definitions, mailbox, and backends."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_harness.core.swarm.definitions import (
    AgentDefinition, get_definition, list_definitions, register_definition,
)
from llm_harness.core.swarm.mailbox import Mailbox
from llm_harness.core.swarm.backend import SpawnConfig, SpawnResult
from llm_harness.core.swarm.in_process import InProcessBackend


# ---------------------------------------------------------------------------
# AgentDefinition registry
# ---------------------------------------------------------------------------

class TestAgentDefinitions:
    def test_get_definition_exists(self):
        """get_definition returns the definition for a known name."""
        defn = get_definition("general-purpose")
        assert defn is not None
        assert defn.name == "general-purpose"

    def test_get_definition_missing(self):
        """get_definition returns None for an unknown name."""
        assert get_definition("nonexistent") is None

    def test_list_definitions_contains_all_builtins(self):
        """All 5 built-in definitions are present in list_definitions."""
        defns = list_definitions()
        names = {d.name for d in defns}
        expected = {"general-purpose", "researcher", "planner", "executor", "reviewer"}
        assert names == expected

    def test_register_definition_adds_and_overwrites(self):
        """register_definition adds a new entry or overwrites an existing one."""
        new_def = AgentDefinition(
            name="test-agent", description="test", system_prompt="you are test",
        )
        register_definition(new_def)
        assert get_definition("test-agent") is new_def
        # Cleanup: remove from registry
        from llm_harness.core.swarm.definitions import _BUILTIN
        _BUILTIN.pop("test-agent", None)

    def test_definition_has_optional_fields(self):
        """AgentDefinition allows optional model and tool lists."""
        defn = AgentDefinition(
            name="custom", description="custom agent",
            system_prompt="custom prompt",
            tools_allow=["read_file"],
            tools_deny=["exec"],
            tools_extra=["web_search"],
            model="gpt-4",
        )
        assert defn.tools_allow == ["read_file"]
        assert defn.tools_deny == ["exec"]
        assert defn.tools_extra == ["web_search"]
        assert defn.model == "gpt-4"


# ---------------------------------------------------------------------------
# Mailbox
# ---------------------------------------------------------------------------

class TestMailbox:
    def test_put_and_poll_returns_messages_in_order(self, tmp_workspace):
        """Mailbox.poll returns stored messages sorted by timestamp."""
        mb = Mailbox(tmp_workspace)
        mb.put("agent1", "text", {"content": "first"})
        mb.put("agent1", "text", {"content": "second"})
        messages = mb.poll("agent1")
        assert len(messages) == 2
        assert messages[0]["payload"]["content"] == "first"
        assert messages[1]["payload"]["content"] == "second"

    def test_poll_reads_without_deleting(self, tmp_workspace):
        """Mailbox.poll reads messages without deleting them."""
        mb = Mailbox(tmp_workspace)
        mb.put("agent1", "text", {"content": "msg"})
        assert len(mb.poll("agent1")) == 1
        # Second poll returns same message (not deleted)
        assert len(mb.poll("agent1")) == 1

    def test_ack_deletes_messages(self, tmp_workspace):
        """Mailbox.ack deletes the first N messages after processing."""
        mb = Mailbox(tmp_workspace)
        mb.put("agent1", "text", {"content": "msg1"})
        mb.put("agent1", "text", {"content": "msg2"})
        mb.put("agent1", "text", {"content": "msg3"})
        assert len(mb.poll("agent1")) == 3
        mb.ack("agent1", 2)
        assert len(mb.poll("agent1")) == 1

    def test_poll_empty_inbox(self, tmp_workspace):
        """Polling a non-existent inbox returns an empty list."""
        mb = Mailbox(tmp_workspace)
        assert mb.poll("nonexistent") == []

    def test_concurrent_writes_unique_filenames(self, tmp_workspace):
        """Concurrent writes produce unique filenames via urandom suffix."""
        mb = Mailbox(tmp_workspace)
        # Simulate concurrent writes by putting many messages rapidly
        for i in range(20):
            mb.put("agent1", "text", {"content": str(i)})
        messages = mb.poll("agent1")
        assert len(messages) == 20


# ---------------------------------------------------------------------------
# SpawnConfig / SpawnResult data classes
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_spawn_config_defaults(self):
        """SpawnConfig has sensible defaults for model."""
        config = SpawnConfig(agent_name="test", prompt="do it", tool_names=[])
        assert config.model == ""

    def test_spawn_result_defaults(self):
        """SpawnResult defaults to success=True and error=None."""
        result = SpawnResult(agent_id="a1")
        assert result.success is True
        assert result.error is None


# ---------------------------------------------------------------------------
# InProcessBackend
# ---------------------------------------------------------------------------

class TestInProcessBackend:
    @pytest.mark.asyncio
    async def test_spawn_without_loop_fn_returns_error(self):
        """spawn returns failure when no loop_fn is configured."""
        backend = InProcessBackend()
        config = SpawnConfig(agent_name="test", prompt="hi", tool_names=[])
        result = await backend.spawn(config)
        assert result.success is False
        assert "No loop_fn" in (result.error or "")

    @pytest.mark.asyncio
    async def test_agent_contexts_cleanup_after_stop(self):
        """Stopping an agent removes it from _tasks."""
        backend = InProcessBackend()
        backend.set_loop_fn(lambda p, a, n, t: asyncio.sleep(999))
        config = SpawnConfig(agent_name="test", prompt="hi", tool_names=[])
        result = await backend.spawn(config)
        assert result.success
        assert result.agent_id in backend._tasks
        await backend.stop(result.agent_id)
        assert result.agent_id not in backend._tasks

    @pytest.mark.asyncio
    async def test_send_message_to_nonexistent_agent(self):
        """send_message returns False for unknown agent."""
        backend = InProcessBackend()
        result = await backend.send_message("no-such-agent", "hello")
        assert result is False
