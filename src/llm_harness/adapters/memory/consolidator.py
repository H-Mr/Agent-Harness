"""MemoryConsolidator — owns consolidation policy and session offset management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any, Callable

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.memory.policy import TokenBudgetPolicy
from llm_harness.adapters.observability.emit_helpers import EventEmitter
from llm_harness.adapters.observability.events import MemoryConsolidated
from llm_harness.core.session.session import Session

logger = logging.getLogger(__name__)


def estimate_message_tokens(message: dict) -> int:
    content = message.get("content", "")
    if isinstance(content, str):
        return len(content) // 4
    if isinstance(content, list):
        return sum(len(str(item)) // 4 for item in content)
    return 0


class MemoryConsolidator:
    """Policy-driven memory consolidation — archives session messages to a persistent backend when token budgets are exceeded."""

    MAX_CONSOLIDATION_ROUNDS = 5

    def __init__(
        self,
        backend: MemoryBackend,
        context_window_tokens: int,
        build_messages: Callable[
            ..., list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]
        ],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        max_completion_tokens: int = 4096,
        policy: object = None,
        *,
        on_save: Callable[[Session], Awaitable[None]] | None = None,
        emitter: EventEmitter | None = None,
    ):
        self.backend = backend
        self._on_save = on_save
        self._emitter = emitter
        self.context_window_tokens = context_window_tokens
        self.max_completion_tokens = max_completion_tokens
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self._policy = policy or TokenBudgetPolicy(
            context_window_tokens=context_window_tokens,
            max_completion_tokens=max_completion_tokens,
        )
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock_max_size = 10_000

    def get_lock(self, session_key: str) -> asyncio.Lock:
        if session_key not in self._locks:
            if len(self._locks) >= self._lock_max_size:
                overflow = len(self._locks) - self._lock_max_size + 100
                for stale_key in list(self._locks)[:overflow]:
                    self._locks.pop(stale_key, None)
            self._locks[session_key] = asyncio.Lock()
        return self._locks[session_key]

    def pick_consolidation_boundary(
        self, session: Session, tokens_to_remove: int
    ) -> tuple[int, int] | None:
        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None
        removed = 0
        last = None
        for idx in range(start, len(session.messages)):
            msg = session.messages[idx]
            if idx > start and msg.get("role") == "user":
                last = (idx, removed)
                if removed >= tokens_to_remove:
                    return last
            removed += estimate_message_tokens(msg)
        return last

    async def estimate_session_prompt_tokens(
        self, session: Session
    ) -> tuple[int, str]:
        history = session.get_history(max_messages=0)
        probe = self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=session.channel,
            chat_id=session.chat_id,
        )
        if asyncio.iscoroutine(probe):
            probe = await probe
        msg_tokens = sum(estimate_message_tokens(m) for m in probe)
        tool_tokens = sum(
            len(str(t)) // 4 for t in self._get_tool_definitions()
        )
        active = session.messages[session.last_consolidated:]
        history_tokens = sum(estimate_message_tokens(m) for m in active)
        return msg_tokens + tool_tokens + history_tokens, "estimate"

    async def maybe_consolidate(self, session: Session, *, account: str = "") -> None:
        if not session.messages or self.context_window_tokens <= 0:
            return
        lock = self.get_lock(session.key)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("Consolidation lock timeout for %s, skipping", session.key)
            return
        try:
            for _ in range(self.MAX_CONSOLIDATION_ROUNDS):
                chunk = await self._policy.should_consolidate(session, self)
                if chunk is None or not chunk:
                    return
                logger.info(
                    "Consolidating %s messages for %s", len(chunk), session.key
                )
                namespace = account or session.channel or session.key
                ok = await self.backend.consolidate(namespace, chunk)
                if not ok:
                    return
                session.remove_before(session.last_consolidated + len(chunk))
                if self._on_save:
                    await self._on_save(session)
                if self._emitter:
                    await self._emitter.send(MemoryConsolidated(session_key=session.key, messages_archived=len(chunk)))
        finally:
            lock.release()
