"""Tests for Agent: _save_turn message filtering."""

from unittest.mock import MagicMock
from llm_harness.core.agent import Agent
from llm_harness.core.loop import AgentLoop, TurnResult


class TestSaveTurn:
    """_save_turn must only save new messages, not re-save history."""

    def test_only_saves_messages_after_new_messages_start(self):
        """Messages before new_messages_start (history) must not be saved."""
        loop = MagicMock(spec=AgentLoop)
        agent = Agent(loop=loop)

        session = MagicMock()
        result = TurnResult(
            messages=[
                {"role": "system", "content": "You are a helper"},
                {"role": "user", "content": "hi"},
                {"role": "user", "content": "do something"},
                {"role": "assistant", "content": "done", "tool_calls": [{"id": "c1"}]},
                {"role": "tool", "content": "ok", "tool_call_id": "c1", "name": "exec"},
            ],
            new_messages_start=3,
        )

        agent._save_turn(session, result)

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
        assert session.add_message.call_count == 1
        assert session.add_message.call_args[0][1] == "real reply"
