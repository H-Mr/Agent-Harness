"""Tests for Session: get_history field preservation, max_messages, add_message."""

import pytest
from llm_harness.core.session.session import Session


class TestGetHistory:
    """get_history() must preserve tool_calls, tool_call_id, and name fields."""

    def test_preserves_tool_call_id(self):
        """Tool result messages must retain tool_call_id for API correlation."""
        s = Session(key="test")
        s.add_message("user", "run cmd")
        s.add_message("assistant", "", tool_calls=[{"id": "c1", "function": {"name": "exec"}}])
        s.add_message("tool", "ok", tool_call_id="c1", name="exec")

        history = s.get_history()
        tool_msg = [m for m in history if m["role"] == "tool"][0]
        assert tool_msg["tool_call_id"] == "c1"
        assert tool_msg["name"] == "exec"

    def test_preserves_tool_calls(self):
        """Assistant messages must retain tool_calls for multi-turn tool use."""
        s = Session(key="test")
        s.add_message("user", "hello")
        s.add_message("assistant", "thinking...", tool_calls=[{"id": "tc1", "function": {"name": "read"}}])

        history = s.get_history()
        asst_msg = [m for m in history if m["role"] == "assistant"][0]
        assert "tool_calls" in asst_msg
        assert asst_msg["tool_calls"][0]["id"] == "tc1"

    def test_max_messages_zero_returns_empty(self):
        """max_messages=0 must return an empty list, not all messages."""
        s = Session(key="test")
        s.add_message("user", "msg1")
        s.add_message("user", "msg2")
        assert s.get_history(max_messages=0) == []

    def test_max_messages_negative_returns_empty(self):
        """Negative max_messages should also return empty."""
        s = Session(key="test")
        s.add_message("user", "msg1")
        assert s.get_history(max_messages=-1) == []

    def test_max_messages_limits_count(self):
        """max_messages=N returns at most N messages (starting from last user)."""
        s = Session(key="test")
        s.add_message("user", "q1")
        s.add_message("assistant", "a1")
        s.add_message("user", "q2")
        s.add_message("assistant", "a2")
        s.add_message("user", "q3")
        s.add_message("assistant", "a3")
        # With max_messages=3, should get the last 3 from the last user msg
        history = s.get_history(max_messages=3)
        assert len(history) <= 3
        assert history[0]["role"] == "user"

    def test_no_user_message_returns_empty(self):
        """If there's no user message, get_history returns []."""
        s = Session(key="test")
        s.add_message("assistant", "orphan")
        assert s.get_history() == []


class TestAddMessage:
    """add_message must include UTC timestamps."""

    def test_timestamp_is_utc_isoformat(self):
        s = Session(key="test")
        s.add_message("user", "hello")
        ts = s.messages[0]["timestamp"]
        assert "+00:00" in ts or "Z" in ts

    def test_utc_datetime_fields(self):
        s = Session(key="test")
        assert s.created_at.tzinfo is not None
        assert s.updated_at.tzinfo is not None
