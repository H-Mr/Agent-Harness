"""In-process agent backend — asyncio Task with ContextVar isolation."""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
from pathlib import Path

from llm_harness.core.swarm.backend import AgentBackend, SpawnConfig, SpawnResult
from llm_harness.core.swarm.mailbox import Mailbox

logger = logging.getLogger(__name__)

_ctx_agent_id: contextvars.ContextVar[str] = contextvars.ContextVar("agent_id", default="")


class InProcessBackend:
    def __init__(self, mailbox: Mailbox | None = None):
        self.mailbox = mailbox or Mailbox(Path.home() / ".llm-harness" / "mail")
        self._tasks: dict[str, asyncio.Task] = {}
        self._loop_fn: callable | None = None

    def set_loop_fn(self, fn: callable) -> None:
        self._loop_fn = fn

    async def spawn(self, config: SpawnConfig, origin_session_key: str = "", origin_account: str = "") -> SpawnResult:
        if self._loop_fn is None:
            return SpawnResult(agent_id="", success=False, error="No loop_fn configured")
        agent_id = f"{config.agent_name}-{os.urandom(4).hex()}"
        task = asyncio.create_task(self._loop_fn(config.prompt, agent_id, config.agent_name, config.tool_names))
        self._tasks[agent_id] = task
        return SpawnResult(agent_id=agent_id)

    async def send_message(self, agent_id: str, message: str) -> bool:
        if agent_id not in self._tasks or self._tasks[agent_id].done():
            return False
        self.mailbox.put(agent_id, "user_message", {"content": message})
        return True

    async def stop(self, agent_id: str) -> bool:
        task = self._tasks.pop(agent_id, None)
        if task and not task.done():
            task.cancel()
        return task is not None
