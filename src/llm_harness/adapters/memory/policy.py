"""Consolidation policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llm_harness.core.session.session import Session


@dataclass
class TokenBudgetPolicy:
    context_window_tokens: int
    max_completion_tokens: int = 4096
    safety_buffer: int = 1024

    async def should_consolidate(
        self, session: Session, consolidator: Any
    ) -> list[dict[str, Any]] | None:
        budget = self.context_window_tokens - self.max_completion_tokens - self.safety_buffer
        estimated, _ = await consolidator.estimate_session_prompt_tokens(session)
        if estimated < budget:
            return None
        boundary = consolidator.pick_consolidation_boundary(
            session, max(1, estimated - budget // 2)
        )
        if boundary is None:
            return None
        chunk = session.messages[session.last_consolidated : boundary[0]]
        return chunk if chunk else None


@dataclass
class MessageCountPolicy:
    max_messages: int = 50

    async def should_consolidate(
        self, session: Session, consolidator: Any
    ) -> list[dict[str, Any]] | None:
        active = session.messages[session.last_consolidated :]
        if len(active) <= self.max_messages:
            return None
        target = len(session.messages) - self.max_messages
        cut = session.last_consolidated
        for i in range(target, len(session.messages)):
            if session.messages[i].get("role") == "user":
                cut = i
                break
        if cut <= session.last_consolidated:
            return None
        return session.messages[session.last_consolidated:cut]
