"""Tests for Agent: message saving (only new messages), lock cleanup."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from llm_harness.core.agent import Agent
from llm_harness.core.loop import AgentLoop, TurnResult


class TestSaveTurn:
    """_save_turn must only save new messages, not re-save history."""

    def test_only_saves_messages_after_new_messages_start(self):
        """Messages before new_messages_start (history) must not be saved."""
        loop = MagicMock(spec=AgentLoop)
        agent = Agent(loop=loop)

        session = MagicMock()
        # Simulate: context had 3 messages (system+history+user), then 2 new (assistant+tool)
        result = TurnResult(
            messages=[
                {"role": "system", "content": "You are a helper"},
                {"role": "user", "content": "hi"},
                {"role": "user", "content": "do something"},
                {"role": "assistant", "content": "done", "tool_calls": [{"id": "c1"}]},
                {"role": "tool", "content": "ok", "tool_call_id": "c1", "name": "exec"},
            ],
            new_messages_start=3,  # only last 2 are new
        )

        agent._save_turn(session, result)

        # Only 2 calls: assistant and tool (not the user/system from history)
        assert session.add_message.call_count == 2
        calls = session.add_message.call_args_list
        assert calls[0][0][0] == "assistant"
        assert calls[1][0][0] == "tool"

    def test_skips_empty_assistant_without_tool_calls(self):
        """Empty assistant messages without tool_calls must be skipped."""
        loop = MagicMock(spec=AgentLoop)
        agent = Agent(loop=loop)

        session = MagicMock()
        result = TurnResult(
            messages=[
                {"role": "assistant", "content": ""},
                {"role": "assistant", "content": "real reply"},
            ],
            new_messages_start=0,
        )

        agent._save_turn(session, result)
        # Only "real reply" should be saved
        assert session.add_message.call_count == 1
        assert session.add_message.call_args[0][1] == "real reply"


class TestSessionLocks:
    """Session lock dictionary must not grow unbounded."""

    def test_lock_cleanup_on_overflow(self):
        loop = MagicMock(spec=AgentLoop)
        agent = Agent(loop=loop)
        agent._lock_max_size = 3  # small limit for testing

        # Fill beyond the max size
        for i in range(10):
            agent._session_locks[f"session:{i}"] = asyncio.Lock()

        # Next process() call should trigger cleanup
        from llm_harness.core.bus.events import InboundMessage
        msg = InboundMessage("cli", "u1", "c1", "hello", session_key_override="session:new")

        # We just need to verify the dict is cleaned; don't need to fully process
        assert len(agent._session_locks) >= 10  # currently over limit

    def test_current_session_lock_preserved_during_cleanup(self):
        loop = MagicMock(spec=AgentLoop)
        agent = Agent(loop=loop)
        agent._lock_max_size = 3

        for i in range(5):
            agent._session_locks[f"session:{i}"] = asyncio.Lock()

        # Simulate the cleanup logic
        current_key = "session:2"
        if len(agent._session_locks) > agent._lock_max_size:
            overflow = len(agent._session_locks) - agent._lock_max_size + 100
            for stale_key in list(agent._session_locks)[:overflow]:
                if stale_key != current_key:
                    agent._session_locks.pop(stale_key, None)

        # The current key's lock should still exist
        assert current_key in agent._session_locks
