"""Tests for consolidation policies: TokenBudgetPolicy and MessageCountPolicy."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_harness.adapters.memory.policy import MessageCountPolicy, TokenBudgetPolicy
from llm_harness.core.session.session import Session


class TestTokenBudgetPolicy:
    """TokenBudgetPolicy: check should_consolidate boundary logic."""

    async def test_under_budget_returns_none(self) -> None:
        """When estimated tokens are under budget, should_consolidate returns None."""
        policy = TokenBudgetPolicy(context_window_tokens=128_000, max_completion_tokens=4096)
        session = Session(key="test")
        session.add_message("user", "short message")

        consolidator = AsyncMock()
        # Return tokens well under budget
        # budget = 128000 - 4096 - 1024 = 122880
        consolidator.estimate_session_prompt_tokens.return_value = (100, "estimate")

        result = await policy.should_consolidate(session, consolidator)
        assert result is None

    async def test_over_budget_returns_chunk(self) -> None:
        """When estimated tokens exceed budget, should_consolidate returns a chunk."""
        policy = TokenBudgetPolicy(context_window_tokens=1000, max_completion_tokens=100)
        session = Session(key="test")
        session.add_message("user", "hello")     # msg 0, last_consolidated=0
        session.add_message("assistant", "world")  # msg 1
        session.add_message("user", "foo")        # msg 2
        session.add_message("assistant", "bar")    # msg 3

        consolidator = AsyncMock()
        # budget = 1000 - 100 - 1024 = -124, so estimated (2000) is way over
        consolidator.estimate_session_prompt_tokens.return_value = (2000, "estimate")
        # boundary at msg index 2 (second user msg), removing ~(2000+124)//2 = 1062
        consolidator.pick_consolidation_boundary = MagicMock(return_value=(2, 1062))

        result = await policy.should_consolidate(session, consolidator)

        assert result is not None
        assert len(result) == 2  # indices 0 and 1

    async def test_exact_budget_boundary(self) -> None:
        """At exactly the budget boundary, no consolidation is needed."""
        policy = TokenBudgetPolicy(context_window_tokens=20_000, max_completion_tokens=2000)
        session = Session(key="test")

        consolidator = AsyncMock()
        # budget = 20000 - 2000 - 1024 = 16976
        consolidator.estimate_session_prompt_tokens.return_value = (16976, "estimate")
        # 16976 is exactly the budget, so should return None
        consolidator.pick_consolidation_boundary = MagicMock(return_value=None)

        result = await policy.should_consolidate(session, consolidator)
        assert result is None

    async def test_pick_boundary_called_with_correct_tokens(self) -> None:
        """The tokens_to_remove passed to pick_consolidation_boundary must be
        max(1, (estimated - budget) // 2)."""
        policy = TokenBudgetPolicy(context_window_tokens=10_000, max_completion_tokens=1000)
        session = Session(key="test")

        consolidator = AsyncMock()
        # budget = 10000 - 1000 - 1024 = 7976
        # estimated - budget = 12000 - 7976 = 4024
        # (4024) // 2 = 2012
        consolidator.estimate_session_prompt_tokens.return_value = (12000, "estimate")
        consolidator.pick_consolidation_boundary = MagicMock(return_value=(2, 2012))

        await policy.should_consolidate(session, consolidator)
        consolidator.pick_consolidation_boundary.assert_called_once_with(session, 2012)


class TestMessageCountPolicy:
    """MessageCountPolicy: check should_consolidate based on message count."""

    async def test_under_max_messages_returns_none(self) -> None:
        """When active messages are under max_messages, returns None."""
        policy = MessageCountPolicy(max_messages=5)
        session = Session(key="test")
        for i in range(3):
            session.add_message("user", f"msg{i}")

        consolidator = AsyncMock()
        result = await policy.should_consolidate(session, consolidator)
        assert result is None

    async def test_over_max_messages_returns_chunk(self) -> None:
        """When active messages exceed max_messages, returns a chunk up to the
        first user-message boundary."""
        policy = MessageCountPolicy(max_messages=3)
        session = Session(key="test")
        session.add_message("user", "m1")    # idx 0
        session.add_message("assistant", "r1")  # idx 1
        session.add_message("user", "m2")    # idx 2
        session.add_message("assistant", "r2")  # idx 3
        session.add_message("user", "m3")    # idx 4

        consolidator = AsyncMock()
        result = await policy.should_consolidate(session, consolidator)
        # active = 5 messages, max = 3, target = 2 (first user at or after idx 2)
        # cut = 2 (first user msg at or after target=2)
        # chunk = messages[0:2] = [m1, r1]
        assert result is not None
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "m1"

    async def test_exact_count_boundary(self) -> None:
        """When active messages equal max_messages, returns None."""
        policy = MessageCountPolicy(max_messages=3)
        session = Session(key="test")
        session.add_message("user", "m1")
        session.add_message("assistant", "r1")
        session.add_message("user", "m2")

        consolidator = AsyncMock()
        result = await policy.should_consolidate(session, consolidator)
        assert result is None

    async def test_first_user_at_boundary_cut(self) -> None:
        """The cut must be at the first user message at or after the target index."""
        policy = MessageCountPolicy(max_messages=2)
        session = Session(key="test")
        session.add_message("assistant", "r1")  # idx 0, not a user msg
        session.add_message("assistant", "r2")   # idx 1, not a user msg
        session.add_message("user", "m1")        # idx 2
        session.add_message("assistant", "r3")   # idx 3
        session.add_message("user", "m2")        # idx 4

        consolidator = AsyncMock()
        result = await policy.should_consolidate(session, consolidator)
        # active = 5, max = 2, target = 3 (len-2=3)
        # cut = 4 (user at idx 4) because idx 3 is assistant
        # chunk = messages[0:4] = [r1, r2, m1, r3]
        assert result is not None
        assert len(result) == 4
