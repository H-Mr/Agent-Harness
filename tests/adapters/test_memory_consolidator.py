"""Tests for MemoryConsolidator -- session-level memory consolidation orchestration."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_harness.adapters.memory.consolidator import (
    MemoryConsolidator,
    estimate_message_tokens,
)
from llm_harness.adapters.memory.policy import TokenBudgetPolicy
from llm_harness.core.session.session import Session


def _build_stub_messages(*, history, current_message, channel, chat_id, **kwargs):
    """A stub build_messages that returns a predictable list."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": current_message or "hello"},
    ]


def _stub_tool_defs():
    return [{"type": "function", "function": {"name": "test_tool"}}]


@pytest.fixture
def stub_consolidator(tmp_workspace: Path) -> MemoryConsolidator:
    """Create a MemoryConsolidator with stubs and a mock backend."""
    backend = AsyncMock()
    backend.consolidate = AsyncMock(return_value=True)
    cons = MemoryConsolidator(
        backend=backend,
        context_window_tokens=128_000,
        build_messages=_build_stub_messages,
        get_tool_definitions=_stub_tool_defs,
        on_save=AsyncMock(),
    )
    return cons


class TestMemoryConsolidator:
    """MemoryConsolidator: estimate, boundary detection, and consolidation flow."""

    # ------------------------------------------------------------------
    # estimate_session_prompt_tokens
    # ------------------------------------------------------------------

    async def test_estimate_returns_positive_int(self, stub_consolidator) -> None:
        """estimate_session_prompt_tokens must return (int, str) with a positive int."""
        session = Session(key="test:abc123")
        session.add_message("user", "hello world")
        estimated, mode = await stub_consolidator.estimate_session_prompt_tokens(session)
        assert isinstance(estimated, int)
        assert estimated > 0
        assert mode == "estimate"

    # ------------------------------------------------------------------
    # pick_consolidation_boundary
    # ------------------------------------------------------------------

    def test_pick_boundary_finds_user_message(self) -> None:
        """pick_consolidation_boundary must find the first user-message boundary after
        the required token count is reached."""
        session = Session(key="test", last_consolidated=0)
        # Add messages with known token counts (~len//4)
        session.add_message("user", "a" * 40)     # ~10 tokens
        session.add_message("assistant", "b" * 40)  # ~10 tokens
        session.add_message("user", "c" * 40)     # ~10 tokens
        session.add_message("assistant", "d" * 40)  # ~10 tokens

        consolidator = MagicMock(spec=MemoryConsolidator)
        boundary = MemoryConsolidator.pick_consolidation_boundary(
            consolidator, session, tokens_to_remove=15
        )
        # After removing 15 tokens we expect the boundary at index 2 (second user msg)
        assert boundary is not None
        assert boundary[0] == 2  # index of second user message

    def test_pick_boundary_returns_none_when_no_user_message(self) -> None:
        """If there are no user messages after last_consolidated, return None."""
        session = Session(key="test", last_consolidated=0)
        session.add_message("assistant", "hello")
        session.add_message("assistant", "world")

        consolidator = MagicMock(spec=MemoryConsolidator)
        boundary = MemoryConsolidator.pick_consolidation_boundary(
            consolidator, session, tokens_to_remove=5
        )
        assert boundary is None

    # ------------------------------------------------------------------
    # maybe_consolidate
    # ------------------------------------------------------------------

    async def test_maybe_consolidate_does_nothing_under_budget(
        self, stub_consolidator,
    ) -> None:
        """When the session is well within the context window, no consolidation occurs."""
        session = Session(key="test:small")
        session.add_message("user", "hi")
        backend = stub_consolidator.backend

        await stub_consolidator.maybe_consolidate(session)

        backend.consolidate.assert_not_called()

    async def test_maybe_consolidate_triggers_when_over_budget(
        self, tmp_workspace: Path,
    ) -> None:
        """When the session exceeds the token budget, consolidation must be triggered."""
        backend = AsyncMock()
        backend.consolidate = AsyncMock(return_value=True)

        # Use a very small budget so the session is trivially over budget
        cons = MemoryConsolidator(
            backend=backend,
            context_window_tokens=100,        # tiny window
            build_messages=_build_stub_messages,
            get_tool_definitions=_stub_tool_defs,
            max_completion_tokens=10,
            on_save=AsyncMock(),
        )
        session = Session(key="test:over")
        # Add enough messages to exceed the budget
        for i in range(5):
            session.add_message("user", "x" * 200)  # ~50 tokens each

        await cons.maybe_consolidate(session)

        backend.consolidate.assert_called_once()

    async def test_maybe_consolidate_skips_empty_session(
        self, stub_consolidator,
    ) -> None:
        """An empty session must not trigger any consolidation."""
        session = Session(key="test:empty")
        backend = stub_consolidator.backend

        await stub_consolidator.maybe_consolidate(session)

        backend.consolidate.assert_not_called()

    # ------------------------------------------------------------------
    # estimate_message_tokens helper
    # ------------------------------------------------------------------

    def test_estimate_message_tokens_string(self) -> None:
        """estimate_message_tokens must return len(content)//4 for string content."""
        tokens = estimate_message_tokens({"content": "a" * 40})
        assert tokens == 10  # 40 // 4

    def test_estimate_message_tokens_list(self) -> None:
        """estimate_message_tokens must sum over content list items."""
        tokens = estimate_message_tokens({"content": ["abc", "defgh"]})
        # each item: len(str(item)) // 4, so 3//4 + 5//4 = 0 + 1 = 1
        assert tokens == 1

    # ------------------------------------------------------------------
    # lock management
    # ------------------------------------------------------------------

    def test_get_lock_returns_same_object(self, stub_consolidator) -> None:
        """get_lock must return the same asyncio.Lock for the same session key."""
        lock1 = stub_consolidator.get_lock("session:abc")
        lock2 = stub_consolidator.get_lock("session:abc")
        assert lock1 is lock2

    def test_get_lock_different_keys_different_locks(self, stub_consolidator) -> None:
        """Different session keys must get different locks."""
        lock_a = stub_consolidator.get_lock("session:a")
        lock_b = stub_consolidator.get_lock("session:b")
        assert lock_a is not lock_b

    def test_locks_is_plain_dict(self, stub_consolidator) -> None:
        """_locks must be a plain dict (not WeakValueDictionary) to prevent GC races."""
        from weakref import WeakValueDictionary
        assert not isinstance(stub_consolidator._locks, WeakValueDictionary)
        assert isinstance(stub_consolidator._locks, dict)
