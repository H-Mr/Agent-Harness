"""ToolFactory — single-source tool instantiation with dependency injection."""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.swarm.backend import AgentBackend
from llm_harness.core.tools.base import BaseTool

logger = logging.getLogger(__name__)

BuilderFn = Any  # () -> BaseTool | None


_SANDBOX_TOOLS = frozenset({"read_file", "write_file", "edit_file", "exec", "glob", "grep"})


class ToolFactory:
    """Creates tool instances with injected backend dependencies.

    Third parties can extend the factory by calling :meth:`register`
    to add custom tool builders.
    """

    def __init__(
        self,
        *,
        sandbox: SandboxBackend | None = None,
        memory: MemoryBackend | None = None,
        swarm: AgentBackend | None = None,
        bus: Any = None,
        skills: Any = None,
        harness_tool_names: list[str] | None = None,
    ):
        self._sandbox = sandbox
        self._memory = memory
        self._swarm = swarm
        self._bus = bus
        self._skills = skills
        self._harness_tool_names = harness_tool_names or []
        self._builders: dict[str, BuilderFn] = OrderedDict()
        self._init_builders()

    def _init_builders(self) -> None:
        s, m, sw = self._sandbox, self._memory, self._swarm
        hn = self._harness_tool_names

        self._builders["read_file"]       = lambda: _import_tool("read_file", "ReadFileTool")(s)
        self._builders["write_file"]      = lambda: _import_tool("write_file", "WriteFileTool")(s)
        self._builders["edit_file"]       = lambda: _import_tool("edit_file", "EditFileTool")(s)
        self._builders["exec"]            = lambda: _import_tool("exec", "ExecTool")(s)
        self._builders["glob"]            = lambda: _import_tool("glob", "GlobTool")(s)
        self._builders["grep"]            = lambda: _import_tool("grep", "GrepTool")(s)
        self._builders["memory_read"]     = lambda: _import_tool("memory_read", "MemoryReadTool")(m)
        self._builders["memory_write"]    = lambda: _import_tool("memory_write", "MemoryWriteTool")(m)
        self._builders["agent"]           = lambda: _import_tool("agent", "AgentTool")(sw, self._bus, hn)
        self._builders["send_message"]    = lambda: _import_tool("send_message", "SendMessageTool")(sw)
        self._builders["task_stop"]       = lambda: _import_tool("task_stop", "TaskStopTool")(sw)
        self._builders["skill"]           = lambda: _import_tool("skill", "SkillTool")(self._skills) if self._skills else None
        self._builders["web_search"]      = lambda: _import_tool("web_search", "WebSearchTool")()
        self._builders["web_fetch"]       = lambda: _import_tool("web_fetch", "WebFetchTool")()
        self._builders["ask_user_question"] = lambda: _import_tool("ask_user", "AskUserQuestionTool")()

    def register(self, name: str, builder: BuilderFn) -> None:
        """Register a custom tool builder, overriding existing if present."""
        self._builders[name] = builder

    def build(self, name: str) -> BaseTool | None:
        if name in _SANDBOX_TOOLS and self._sandbox is None:
            logger.warning("Refusing to build %s: no sandbox configured", name)
            return None

        builder = self._builders.get(name)
        if builder is None:
            logger.warning("Unknown tool: %s", name)
            return None

        try:
            return builder()
        except Exception:
            logger.exception("Failed to build tool %s", name)
            return None


def _import_tool(module_name: str, class_name: str) -> type:
    import importlib
    mod = importlib.import_module(f"llm_harness.core.tools.{module_name}")
    return getattr(mod, class_name)
