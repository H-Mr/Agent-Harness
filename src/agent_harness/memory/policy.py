"""Pluggable consolidation policies.

A policy is called before each LLM turn.  It receives the current session
and the consolidator and returns the message chunk to archive (or ``None``
to skip).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_harness.memory.consolidator import MemoryConsolidator
    from agent_harness.session.manager import Session


@dataclass
class TokenBudgetPolicy:
    """Consolidate when estimated prompt tokens exceed a safe budget.

    This replicates the default behaviour of the legacy ``maybe_consolidate_by_tokens``.
    """

    context_window_tokens: int
    max_completion_tokens: int = 4096
    _SAFETY_BUFFER: int = 1024

    async def should_consolidate(
        self,
        session: Session,
        consolidator: MemoryConsolidator,
    ) -> list[dict[str, Any]] | None:
        budget = self.context_window_tokens - self.max_completion_tokens - self._SAFETY_BUFFER
        estimated, _ = await consolidator.estimate_session_prompt_tokens(session)
        if estimated < budget:
            return None

        target = budget // 2
        boundary = consolidator.pick_consolidation_boundary(
            session, max(1, estimated - target),
        )
        if boundary is None:
            return None

        end_idx = boundary[0]
        chunk = session.messages[session.last_consolidated : end_idx]
        return chunk if chunk else None


@dataclass
class MessageCountPolicy:
    """Consolidate when the number of unconsolidated messages exceeds a threshold.

    Messages are counted from *last_consolidated*.  The boundary is always
    at a user-turn to avoid splitting assistant/tool-call pairs.
    """

    max_messages: int = 50

    async def should_consolidate(
        self,
        session: Session,
        consolidator: MemoryConsolidator,
    ) -> list[dict[str, Any]] | None:
        active = session.messages[session.last_consolidated :]
        if len(active) <= self.max_messages:
            return None

        # Find a user-turn boundary that leaves at most max_messages unconsolidated.
        # We cut so that the remaining session length is <= max_messages.
        target_start = len(session.messages) - self.max_messages
        if target_start <= session.last_consolidated:
            return None

        cut_idx = session.last_consolidated
        for i in range(target_start, len(session.messages)):
            if session.messages[i].get("role") == "user":
                cut_idx = i
                break

        if cut_idx <= session.last_consolidated:
            return None

        return session.messages[session.last_consolidated : cut_idx]
