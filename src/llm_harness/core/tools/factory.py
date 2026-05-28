"""ToolFactory — single source of truth for tool instantiation."""

from __future__ import annotations

import logging
from typing import Any

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.swarm.backend import AgentBackend
from llm_harness.core.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolFactory:
    """Creates tool instances with injected backend dependencies.

    Used by both Harness (full backends) and worker subprocesses
    (LocalSandboxBackend only).
    """

    def __init__(
        self,
        *,
        sandbox: SandboxBackend | None = None,
        memory: MemoryBackend | None = None,
        swarm: AgentBackend | None = None,
        bus: Any = None,
        harness_tool_names: list[str] | None = None,
    ):
        self._sandbox = sandbox
        self._memory = memory
        self._swarm = swarm
        self._bus = bus
        self._harness_tool_names = harness_tool_names or []

    def build(self, name: str) -> BaseTool | None:
        # Sandbox-dependent tools — require sandbox
        sandbox_tools = {"read_file", "write_file", "edit_file", "exec", "glob", "grep"}
        if name in sandbox_tools and self._sandbox is None:
            logger.warning("Refusing to build %s: no sandbox configured", name)
            return None

        if name == "read_file":
            from llm_harness.core.tools.read_file import ReadFileTool
            return ReadFileTool(self._sandbox)
        if name == "write_file":
            from llm_harness.core.tools.write_file import WriteFileTool
            return WriteFileTool(self._sandbox)
        if name == "edit_file":
            from llm_harness.core.tools.edit_file import EditFileTool
            return EditFileTool(self._sandbox)
        if name == "exec":
            from llm_harness.core.tools.exec import ExecTool
            return ExecTool(self._sandbox)
        if name == "glob":
            from llm_harness.core.tools.glob import GlobTool
            return GlobTool(self._sandbox)
        if name == "grep":
            from llm_harness.core.tools.grep import GrepTool
            return GrepTool(self._sandbox)

        # Memory-dependent tools
        if name == "memory_read":
            from llm_harness.core.tools.memory_read import MemoryReadTool
            return MemoryReadTool(self._memory)
        if name == "memory_write":
            from llm_harness.core.tools.memory_write import MemoryWriteTool
            return MemoryWriteTool(self._memory)

        # Swarm-dependent tools
        if name == "agent":
            from llm_harness.core.tools.agent import AgentTool
            return AgentTool(self._swarm, self._bus, self._harness_tool_names)
        if name == "send_message":
            from llm_harness.core.tools.send_message import SendMessageTool
            return SendMessageTool(self._swarm)
        if name == "task_stop":
            from llm_harness.core.tools.task_stop import TaskStopTool
            return TaskStopTool(self._swarm)

        # Independent tools
        if name == "web_search":
            from llm_harness.core.tools.web_search import WebSearchTool
            return WebSearchTool()
        if name == "web_fetch":
            from llm_harness.core.tools.web_fetch import WebFetchTool
            return WebFetchTool()
        if name == "ask_user_question":
            from llm_harness.core.tools.ask_user import AskUserQuestionTool
            return AskUserQuestionTool()

        logger.warning("Unknown tool: %s", name)
        return None
