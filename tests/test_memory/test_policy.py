"""Test consolidation policies."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_harness.memory.policy import MessageCountPolicy, TokenBudgetPolicy
from agent_harness.session.manager import Session


@pytest.fixture
def session():
    s = Session(key="test:policy")
    for i in range(60):
        s.add_message("user", f"msg {i}")
        s.add_message("assistant", f"reply {i}")
    return s


@pytest.fixture
def consolidator():
    c = MagicMock()
    c.estimate_session_prompt_tokens = AsyncMock(return_value=(0, "estimate"))
    c.pick_consolidation_boundary = MagicMock(return_value=None)
    return c


class TestMessageCountPolicy:
    async def test_no_consolidation_under_limit(self, session, consolidator):
        session.last_consolidated = 0
        policy = MessageCountPolicy(max_messages=200)
        result = await policy.should_consolidate(session, consolidator)
        assert result is None

    async def test_triggers_when_over_limit(self, session, consolidator):
        session.last_consolidated = 0
        policy = MessageCountPolicy(max_messages=50)
        result = await policy.should_consolidate(session, policy)
        # 120 messages > 50 -> should return a chunk
        assert result is not None
        assert len(result) > 0


class TestTokenBudgetPolicy:
    async def test_no_consolidation_under_budget(self, session, consolidator):
        consolidator.estimate_session_prompt_tokens.return_value = (5000, "estimate")
        policy = TokenBudgetPolicy(context_window_tokens=200000)
        result = await policy.should_consolidate(session, consolidator)
        assert result is None

    async def test_triggers_when_over_budget(self, session, consolidator):
        consolidator.estimate_session_prompt_tokens.return_value = (195000, "estimate")
        boundary = (session.last_consolidated + 20, 50000)
        consolidator.pick_consolidation_boundary.return_value = boundary
        policy = TokenBudgetPolicy(context_window_tokens=200000)
        result = await policy.should_consolidate(session, consolidator)
        assert result is not None
