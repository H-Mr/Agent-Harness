"""Agent — harness + model = runnable agent. Orchestrates session, memory, loop."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from llm_harness.core.bus.events import InboundMessage, OutboundMessage
from llm_harness.core.loop import AgentLoop
from llm_harness.core.session.manager import SessionManager
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.observability.backend import ObservabilityBackend

logger = logging.getLogger(__name__)


class Agent:
    def __init__(
        self,
        loop: AgentLoop,
        sessions: SessionManager | None = None,
        consolidator: MemoryConsolidator | None = None,
        observability: ObservabilityBackend | None = None,
        workspace_cwd: Path | None = None,
    ):
        self._loop = loop
        self._sessions = sessions
        self._consolidator = consolidator
        self._observability = observability
        self._workspace_cwd = workspace_cwd or Path("/workspace")
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._lock_max_size = 10_000

    async def process(self, msg: InboundMessage) -> OutboundMessage | None:
        session_key = msg.session_key
        account = msg.sender_id
        chat_id = msg.chat_id

        # {base}/{account}/sessions/{channel}/{chat_id}/files/
        session_ws = (self._workspace_cwd / account / "sessions" / msg.channel / chat_id / "files").resolve()
        if not str(session_ws).startswith(str(self._workspace_cwd.resolve())):
            raise PermissionError(f"Session workspace traversal: {session_key}")
        session_ws.mkdir(parents=True, exist_ok=True)

        lock = self._session_locks.setdefault(session_key, asyncio.Lock())

        if len(self._session_locks) > self._lock_max_size:
            overflow = len(self._session_locks) - self._lock_max_size + 100
            for stale_key in list(self._session_locks)[:overflow]:
                if stale_key != session_key:
                    self._session_locks.pop(stale_key, None)

        async with lock:
            try:
                if self._observability:
                    await self._observability.emit("message:received", {"session_key": session_key, "content": msg.content[:200]})

                session = None
                history: list[dict[str, Any]] = []
                if self._sessions:
                    session = await self._sessions.get_or_create(session_key)
                    history = session.get_history()
                    session.add_message("user", msg.content)
                    await self._sessions.save(session)

                if self._consolidator and session:
                    await self._consolidator.maybe_consolidate(session, account=account)

                result = await self._loop.run(msg, history, cwd=session_ws)

                if session:
                    self._save_turn(session, result)
                    await self._sessions.save(session)

                if self._observability:
                    await self._observability.emit("message:sent", {"session_key": session_key})

                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=result.final_content or "")

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Error processing message for %s", session_key)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                       content=f"Sorry, I encountered an error: {exc}")

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
