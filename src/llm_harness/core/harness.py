"""Harness — IoC container. Resolves backends, assembles Agent."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.memory.file import FileMemoryBackend
from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend
from llm_harness.adapters.memory.policy import TokenBudgetPolicy
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.adapters.sandbox.opensandbox import OpenSandboxBackend
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
        return FileMemoryBackend(Path(memory))

    def _resolve_sandbox(self, sandbox):
        if sandbox is None:
            return None
        if isinstance(sandbox, SandboxBackend):
            return sandbox
        if isinstance(sandbox, str):
            if sandbox == "none":
                return None
            if sandbox.startswith("opensandbox://"):
                return OpenSandboxBackend(sandbox.replace("opensandbox://", "http://"))
            if sandbox == "opensandbox":
                return OpenSandboxBackend()
        raise TypeError(f"Unsupported sandbox: {sandbox}")

    def _resolve_swarm(self, swarm):
        if swarm is None:
            return SubprocessBackend(bus=self.bus)
        if isinstance(swarm, AgentBackend):
            return swarm
        if swarm == "subprocess":
            return SubprocessBackend(bus=self.bus)
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
        registry = ToolRegistry()
        if not tool_names:
            tool_names = [
                "read_file", "write_file", "edit_file", "exec",
                "web_search", "web_fetch", "glob", "grep",
                "memory_read", "memory_write", "agent",
                "send_message", "task_stop", "ask_user_question",
            ]
        for name in tool_names:
            tool = self._build_tool(name)
            if tool:
                registry.register(tool)
        return registry

    def _build_tool(self, name: str):
        from llm_harness.core.tools.read_file import ReadFileTool
        from llm_harness.core.tools.write_file import WriteFileTool
        from llm_harness.core.tools.edit_file import EditFileTool
        from llm_harness.core.tools.exec import ExecTool
        from llm_harness.core.tools.glob import GlobTool
        from llm_harness.core.tools.grep import GrepTool
        from llm_harness.core.tools.web_search import WebSearchTool
        from llm_harness.core.tools.web_fetch import WebFetchTool
        from llm_harness.core.tools.memory_read import MemoryReadTool
        from llm_harness.core.tools.memory_write import MemoryWriteTool
        from llm_harness.core.tools.agent import AgentTool
        from llm_harness.core.tools.send_message import SendMessageTool
        from llm_harness.core.tools.task_stop import TaskStopTool
        from llm_harness.core.tools.ask_user import AskUserQuestionTool

        DEP_MAP = {
            "read_file": lambda: ReadFileTool(self.sandbox),
            "write_file": lambda: WriteFileTool(self.sandbox),
            "edit_file": lambda: EditFileTool(self.sandbox),
            "exec": lambda: ExecTool(self.sandbox),
            "glob": lambda: GlobTool(self.sandbox),
            "grep": lambda: GrepTool(self.sandbox),
            "memory_read": lambda: MemoryReadTool(self.memory),
            "memory_write": lambda: MemoryWriteTool(self.memory),
            "agent": lambda: AgentTool(self.swarm, self.bus),
            "send_message": lambda: SendMessageTool(self.swarm),
            "task_stop": lambda: TaskStopTool(self.swarm),
        }
        INDEP_MAP = {
            "web_search": WebSearchTool,
            "web_fetch": WebFetchTool,
            "ask_user_question": AskUserQuestionTool,
        }
        factory = DEP_MAP.get(name)
        if factory:
            return factory()
        fac_class = INDEP_MAP.get(name)
        if fac_class:
            return fac_class()
        log.warning("Unknown tool: %s", name)
        return None

    def _build_consolidator(self):
        return MemoryConsolidator(
            backend=self.memory,
            sessions=self._session_manager,
            context_window_tokens=64_000,
            max_completion_tokens=4096,
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
                f"Current time: {__import__('datetime').datetime.now().isoformat()}",
            ]
            if self.memory:
                ctx = await self.memory.get_context(msg.session_key)
                if ctx:
                    parts.append(ctx)
            from llm_harness.core.swarm.definitions import list_definitions as ld
            defs = ld()
            if defs:
                agent_list = "\n".join(
                    f"- **{d.name}**: {d.description}" for d in defs
                )
                parts.append(f"## Available Sub-Agents\n{agent_list}")
            system = "\n\n".join(parts)
            return [
                {"role": "system", "content": system},
                {"role": "user", "content": msg.content},
            ]

        loop = AgentLoop(
            provider=self.provider,
            tools=self._tools,
            model=self.model,
            on_build_context=on_build_context,
            on_tool_check=lambda name, tool, args: self._permissions.evaluate(
                name,
                is_read_only=tool.is_read_only(args) if hasattr(tool, 'is_read_only') else False,
            ),
            on_error=lambda exc, ctx: log.exception("Error in %s", ctx),
        )
        return Agent(
            loop=loop,
            sessions=self._session_manager,
            consolidator=self._consolidator,
            observability=self._observability,
        )
