"""Harness — IoC container. Resolves backends, assembles Agent."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.memory.file import FileMemoryBackend
from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend
from llm_harness.adapters.memory.policy import TokenBudgetPolicy
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.adapters.session.backend import SessionBackend
from llm_harness.adapters.session.file import FileSessionBackend
from llm_harness.adapters.observability.backend import ObservabilityBackend
from llm_harness.adapters.observability.default import DefaultObservabilityBackend
from llm_harness.core.session.manager import SessionManager
from llm_harness.core.swarm.backend import AgentBackend
from llm_harness.core.swarm.subprocess import SubprocessBackend
from llm_harness.core.swarm.in_process import InProcessBackend
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.permissions.checker import PermissionChecker
from llm_harness.core.permissions.settings import PermissionSettings
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.loop import AgentLoop
from llm_harness.core.agent import Agent
from llm_harness.core.swarm.definitions import list_definitions

log = logging.getLogger(__name__)


class Harness:
    def __init__(
        self, *, provider: Any = None, model: str = "",
        workspace: str | Path = Path.cwd(),
        tools: list[str] | None = None,
        permissions: str = "default",
        memory: str | MemoryBackend | None = None,
        sandbox: str | SandboxBackend | None = None,
        swarm: str | AgentBackend | None = None,
        sessions: str | SessionBackend | None = None,
        observability: str | ObservabilityBackend | None = None,
        context_window_tokens: int = 64_000,
        max_completion_tokens: int = 4096,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        self.provider = provider
        self.model = model
        self.bus = MessageBus()

        self.memory = self._resolve_memory(memory)
        self.sandbox = self._resolve_sandbox(sandbox)
        self.swarm = self._resolve_swarm(swarm)
        self._session_backend = self._resolve_sessions_backend(sessions)
        self._session_manager = SessionManager(self._session_backend)
        self._observability = self._resolve_observability(observability)
        self._permissions = self._resolve_permissions(permissions)
        self._tools = self._resolve_tools(tools)
        self.context_window_tokens = context_window_tokens
        self.max_completion_tokens = max_completion_tokens
        self._consolidator = self._build_consolidator() if self.memory else None

    # -- Resolvers -------------------------------------------------------

    def _resolve_memory(self, memory):
        if memory is None:
            return None
        if isinstance(memory, MemoryBackend):
            return memory
        if isinstance(memory, str):
            if memory.startswith("tencentdb://"):
                return TencentDBMemoryBackend(memory.replace("tencentdb://", "http://"))
            if memory.startswith("file://"):
                return FileMemoryBackend(Path(memory.replace("file://", "")))
            return FileMemoryBackend(Path(memory))
        raise TypeError(f"Unsupported memory type: {type(memory).__name__} ({memory!r})")

    def _resolve_sandbox(self, sandbox):
        if sandbox is None:
            return SRTSandboxBackend(self.workspace)
        if isinstance(sandbox, SandboxBackend):
            return sandbox
        if sandbox == "srt":
            return SRTSandboxBackend(self.workspace)
        raise TypeError(f"Unsupported sandbox: {sandbox}")

    def _resolve_swarm(self, swarm):
        if swarm is None:
            return SubprocessBackend(bus=self.bus, workspace_root=self.workspace)
        if isinstance(swarm, AgentBackend):
            return swarm
        if swarm == "subprocess":
            return SubprocessBackend(bus=self.bus, workspace_root=self.workspace)
        if swarm == "in_process":
            return InProcessBackend()
        raise TypeError(f"Unsupported swarm: {swarm}")

    def _resolve_sessions_backend(self, sessions):
        if sessions is None:
            return FileSessionBackend(self.workspace / "sessions")
        if isinstance(sessions, SessionBackend):
            return sessions
        if isinstance(sessions, str):
            return FileSessionBackend(Path(sessions))
        raise TypeError(f"Unsupported sessions: {sessions}")

    def _resolve_observability(self, obs):
        if obs is None:
            return DefaultObservabilityBackend()
        if isinstance(obs, ObservabilityBackend):
            return obs
        if isinstance(obs, str):
            return DefaultObservabilityBackend(Path(obs))
        return DefaultObservabilityBackend()

    def _resolve_permissions(self, permissions):
        if isinstance(permissions, PermissionChecker):
            return permissions
        if isinstance(permissions, str):
            from llm_harness.core.permissions.modes import PermissionMode
            mode_map = {
                "default": PermissionMode.DEFAULT,
                "plan": PermissionMode.PLAN,
                "auto": PermissionMode.FULL_AUTO,
                "full_auto": PermissionMode.FULL_AUTO,
            }
            mode = mode_map.get(permissions.lower(), PermissionMode.DEFAULT)
            return PermissionChecker(PermissionSettings(mode=mode))
        return PermissionChecker(PermissionSettings())

    def _resolve_tools(self, tool_names):
        from llm_harness.core.tools.factory import ToolFactory

        registry = ToolRegistry()
        if not tool_names:
            tool_names = [
                "read_file", "write_file", "edit_file", "exec",
                "web_search", "web_fetch", "glob", "grep",
                "memory_read", "memory_write", "agent",
                "send_message", "task_stop", "ask_user_question",
            ]
        self._harness_tool_names = tool_names
        factory = ToolFactory(
            sandbox=self.sandbox, memory=self.memory,
            swarm=self.swarm, bus=self.bus,
            harness_tool_names=tool_names,
        )
        for name in tool_names:
            tool = factory.build(name)
            if tool:
                registry.register(tool)
        return registry

    def _build_consolidator(self):
        return MemoryConsolidator(
            backend=self.memory,
            sessions=self._session_manager,
            context_window_tokens=self.context_window_tokens,
            max_completion_tokens=self.max_completion_tokens,
            build_messages=self._consolidator_build_messages(),
            get_tool_definitions=lambda: self._tools.to_api_schema("openai"),
        )

    def _consolidator_build_messages(self):
        async def _build(*, history, current_message, channel=None, chat_id=None):
            return [
                {"role": "system", "content": "Memory consolidation"},
                {"role": "user", "content": current_message},
            ]
        return _build

    def create_agent(self) -> Agent:
        async def on_build_context(msg, history):
            parts = [
                "You are a helpful AI assistant.",
                f"Current time: {datetime.now(timezone.utc).isoformat()}",
            ]
            if self.memory:
                ctx = await self.memory.get_context(msg.sender_id)
                if ctx:
                    parts.append(ctx)
            defs = list_definitions()
            if defs:
                agent_list = "\n".join(
                    f"- **{d.name}**: {d.description}" for d in defs
                )
                parts.append(f"## Available Sub-Agents\n{agent_list}")
            system = "\n\n".join(parts)
            messages = [{"role": "system", "content": system}]
            messages.extend(history)
            messages.append({"role": "user", "content": msg.content})
            return messages

        loop = AgentLoop(
            provider=self.provider,
            tools=self._tools,
            model=self.model,
            on_build_context=on_build_context,
            on_tool_check=lambda name, tool, args: self._permissions.evaluate(
                name,
                is_read_only=tool.is_read_only(args) if hasattr(tool, 'is_read_only') else False,
                file_path=getattr(args, 'file_path', None) or getattr(args, 'path', None),
                command=getattr(args, 'command', None),
            ),
            on_error=lambda exc, ctx: log.exception("Error in %s", ctx),
        )
        return Agent(
            loop=loop,
            sessions=self._session_manager,
            consolidator=self._consolidator,
            observability=self._observability,
            workspace_cwd=self.workspace,
        )
