"""Subprocess-based agent backend — each agent as an independent OS process."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

from llm_harness.adapters.observability.emit_helpers import EventEmitter
from llm_harness.adapters.observability.events import SubagentCompleted, SubagentSpawned
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.swarm.backend import AgentBackend, SpawnConfig, SpawnResult
from llm_harness.core.swarm.mailbox import Mailbox

logger = logging.getLogger(__name__)


class SubprocessBackend:
    def __init__(self, bus: MessageBus, workspace_root: Path | None = None, mailbox: Mailbox | None = None, *, emitter: EventEmitter | None = None):
        self.bus = bus
        self._workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        self.mailbox = mailbox or Mailbox(Path.home() / ".llm-harness" / "mail")
        self._emitter = emitter
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._session_keys: dict[str, str] = {}
        self._watch_tasks: dict[str, asyncio.Task] = {}

    async def spawn(self, config: SpawnConfig, origin_session_key: str = "", origin_account: str = "") -> SpawnResult:
        agent_id = f"{config.agent_name}-{os.urandom(4).hex()}"
        account = origin_account or (origin_session_key.split(":", 1)[0] if ":" in origin_session_key else origin_session_key)
        account_ws = self._workspace_root / account

        env = os.environ.copy()
        env["LLM_HARNESS_WORKER"] = "1"
        env["LLM_HARNESS_AGENT_NAME"] = config.agent_name
        env["LLM_HARNESS_ACCOUNT"] = account
        env["LLM_HARNESS_ACCOUNT_WS"] = str(account_ws)

        worker_cmd = [sys.executable, "-m", "llm_harness", "--worker",
                      "--agent-def", config.agent_name,
                      "--tools", ",".join(config.tool_names),
                      "--workspace", str(account_ws)]
        if config.model:
            worker_cmd.extend(["--model", config.model])

        if shutil.which("srt"):
            cmd = ["srt", f"--read={account_ws}", f"--write={account_ws}", "--", *worker_cmd]
        else:
            cmd = worker_cmd

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._processes[agent_id] = proc
            self._session_keys[agent_id] = origin_session_key
            if proc.stdin:
                proc.stdin.write(config.prompt.encode() + b"\n")
                await proc.stdin.drain()
                proc.stdin.close()

            task = asyncio.create_task(self._watch(agent_id, proc))
            self._watch_tasks[agent_id] = task
            task.add_done_callback(lambda t: self._watch_tasks.pop(agent_id, None))
            if self._emitter:
                await self._emitter.send(SubagentSpawned(task_id=agent_id, label=config.agent_name))
            return SpawnResult(agent_id=agent_id)
        except Exception as e:
            return SpawnResult(agent_id=agent_id, success=False, error=str(e))

    async def _watch(self, agent_id: str, proc: asyncio.subprocess.Process) -> None:
        try:
            stdout_bytes, stderr_bytes = await proc.communicate()
            result = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            if stderr_bytes:
                logger.debug("Sub-agent %s stderr: %s", agent_id, stderr_bytes.decode("utf-8", errors="replace")[:500])
            origin_key = self._session_keys.get(agent_id, "")
            msg = InboundMessage(
                channel="system", sender_id=agent_id,
                chat_id=origin_key,
                session_key_override=origin_key,
                content=f"<task-notification><task_id>{agent_id}</task_id><status>{'completed' if proc.returncode==0 else 'failed'}</status><result>{result}</result></task-notification>",
            )
            await self.bus.publish_inbound(msg)
            if self._emitter:
                status = "ok" if proc.returncode == 0 else "error"
                await self._emitter.send(SubagentCompleted(task_id=agent_id, label=agent_id, status=status))
        except Exception:
            logger.exception("Watcher failed for %s", agent_id)
        finally:
            self._processes.pop(agent_id, None)
            self._session_keys.pop(agent_id, None)

    async def send_message(self, agent_id: str, message: str) -> bool:
        if agent_id not in self._processes:
            return False
        self.mailbox.put(agent_id, "user_message", {"content": message})
        return True

    async def stop(self, agent_id: str) -> bool:
        proc = self._processes.pop(agent_id, None)
        if proc is None:
            return False
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        return True
