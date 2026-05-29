"""Agent — pure stateless engine. Caller provides session, workspace, and state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_harness.core.bus.events import InboundMessage, OutboundMessage
from llm_harness.core.loop import AgentLoop, TurnResult
from llm_harness.core.session.session import Session
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.observability.emit_helpers import EventEmitter
from llm_harness.adapters.observability.events import SessionClosed, SessionOpened


class Agent:
    """Pure stateless engine — zero side effects, zero internal state.

    The caller is responsible for:
    - Loading / persisting the :class:`Session` (pass it to each call).
    - Resolving the session working directory.
    - Managing concurrency (create one Agent per thread, or serialize).

    Usage::

        session = Session(key="alice:chat1")
        agent = Agent(loop, consolidator=cons, emitter=events)
        result = await agent.process(msg, session=session, cwd=Path("/data/alice/sessions/chat1/files"))
    """

    def __init__(
        self,
        loop: AgentLoop,
        consolidator: MemoryConsolidator | None = None,
        emitter: EventEmitter | None = None,
    ):
        self._loop = loop
        self._consolidator = consolidator
        self._emitter = emitter

    async def process(
        self,
        msg: InboundMessage,
        *,
        session: Session,
        cwd: Path,
        account: str = "",
    ) -> TurnResult:
        """Run one turn against *session* in *cwd*."""
        if self._emitter:
            await self._emitter.send(SessionOpened(session_key=session.key))

        history = session.get_history()
        session.add_message("user", msg.content)

        if self._consolidator:
            await self._consolidator.maybe_consolidate(session, account=account)

        result = await self._loop.run(msg, history, cwd=cwd)
        self._save_turn(session, result)

        if self._emitter:
            await self._emitter.send(
                SessionClosed(session_key=session.key, message_count=len(session.messages))
            )

        return result

    async def close(self) -> None:
        """Release resources held by sub-components (consolidator locks, etc.)."""
        pass  # stateless engine — nothing to release currently

    def _save_turn(self, session, result) -> None:
        for msg in result.messages[result.new_messages_start:]:
            role = msg.get("role", "")
            if role not in ("assistant", "tool"):
                continue
            content = msg.get("content", "")
            if role == "assistant" and not content and not msg.get("tool_calls"):
                continue
            extra = {}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in msg:
                    extra[k] = msg[k]
            session.add_message(role, content, **extra)
