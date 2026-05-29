"""Harness — pure assembler. Wires components, returns an Agent."""

from __future__ import annotations

import logging
from typing import Any

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.observability.backend import ObservabilityBackend
from llm_harness.adapters.observability.emit_helpers import EventEmitter
from llm_harness.adapters.providers.base import LLMProvider
from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.loop import AgentLoop
from llm_harness.core.agent import Agent
from llm_harness.core.permissions.checker import PermissionChecker
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.extensions.skills.registry import SkillRegistry

log = logging.getLogger(__name__)


class Harness:
    """Assembles components into a ready-to-use :class:`Agent`.

    All parameters are **required** — no defaults, no filesystem side-effects.
    Inject the exact instances your application needs.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        tools: ToolRegistry,
        sandbox: SandboxBackend,
        memory: MemoryBackend | None = None,
        swarm: Any = None,
        permissions: PermissionChecker | None = None,
        skills: SkillRegistry | None = None,
        observability: ObservabilityBackend | None = None,
        system_prompt: str = "",
        context_window_tokens: int = 64_000,
        max_completion_tokens: int = 4096,
    ):
        self.provider = provider
        self.model = model
        self._sandbox = sandbox
        self._memory = memory
        self._swarm = swarm
        self._observability = observability
        self._permissions = permissions
        self._skills = skills or SkillRegistry()
        self._system_prompt = system_prompt
        self.context_window_tokens = context_window_tokens
        self.max_completion_tokens = max_completion_tokens
        self._tools = tools
        self._consolidator = self._build_consolidator() if memory else None

    def _build_consolidator(self):
        return MemoryConsolidator(
            backend=self._memory,
            context_window_tokens=self.context_window_tokens,
            max_completion_tokens=self.max_completion_tokens,
            build_messages=lambda **kw: [
                {"role": "system", "content": "Memory consolidation"},
                {"role": "user", "content": kw.get("current_message", "")},
            ],
            get_tool_definitions=lambda: self._tools.to_api_schema("openai"),
            emitter=EventEmitter(self._observability) if self._observability else None,
        )

    def create_agent(self) -> Agent:
        emitter = EventEmitter(self._observability) if self._observability else None
        loop = AgentLoop(
            provider=self.provider,
            tools=self._tools,
            model=self.model,
            on_build_context=lambda msg, history: [
                *self._build_system(msg), *history, {"role": "user", "content": msg.content}
            ],
            on_tool_check=lambda name, tool, args: (
                self._permissions.evaluate(
                    name,
                    is_read_only=tool.is_read_only(args) if hasattr(tool, 'is_read_only') else False,
                    file_path=getattr(args, 'file_path', None) or getattr(args, 'path', None),
                    command=getattr(args, 'command', None),
                )
                if self._permissions
                else type("OK", (), {"allowed": True})()
            ),
            on_error=lambda exc, ctx: log.exception("Error in %s", ctx),
            emitter=emitter,
        )
        return Agent(loop, consolidator=self._consolidator, emitter=emitter)

    def _build_system(self, msg):
        from datetime import datetime, timezone
        from llm_harness.core.swarm.definitions import list_definitions

        parts = [
            self._system_prompt or "You are a helpful AI assistant.",
            f"Current time: {datetime.now(timezone.utc).isoformat()}",
        ]
        if self._memory:
            ctx = msg.content  # caller provides pre-loaded context if needed
        defs = list_definitions()
        if defs:
            agent_list = "\n".join(f"- **{d.name}**: {d.description}" for d in defs)
            parts.append(f"## Available Sub-Agents\n{agent_list}")
        skills = self._skills.list_skills()
        if skills:
            skill_list = "\n".join(f"- **{s.name}**: {s.description}" for s in skills)
            parts.append(f"## Available Skills (use the `skill` tool to load)\n{skill_list}")
        return [{"role": "system", "content": "\n\n".join(parts)}]
