"""Tool: AgentTool — spawn a sub-agent via AgentBackend."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.swarm.backend import AgentBackend, SpawnConfig
from llm_harness.core.swarm.definitions import get_definition
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class AgentInput(BaseModel):
    name: str = Field(description="Agent definition name to use")
    prompt: str = Field(description="The task prompt for the sub-agent")
    model: str = Field(default="", description="Optional model override")


class AgentTool(BaseTool):
    """Spawn a sub-agent to handle a task.

    Looks up the agent definition by name, computes the effective tool set,
    and delegates to the AgentBackend to spawn the agent.
    """

    name: ClassVar[str] = "agent"
    description: ClassVar[str] = (
        "Spawn a sub-agent to handle a task. "
        "The sub-agent runs independently and can use sandbox tools."
    )
    input_model: ClassVar[type[BaseModel]] = AgentInput

    def __init__(self, swarm: AgentBackend, bus: MessageBus | None = None, harness_tool_names: list[str] | None = None) -> None:
        self._swarm = swarm
        self._bus = bus
        self._harness_tool_names = harness_tool_names or []

    async def execute(self, arguments: AgentInput, context: ToolExecutionContext) -> ToolResult:
        # Look up agent definition
        defn = get_definition(arguments.name)
        if defn is None:
            return ToolResult(
                output=f"Error: Unknown agent definition '{arguments.name}'. "
                       f"Available: {', '.join(name for name in ['general-purpose', 'researcher', 'planner', 'executor', 'reviewer'])}",
                is_error=True,
            )

        # Compute effective tool set: (harness_tools & allow) - deny + extra
        harness_tools: list[str] = self._harness_tool_names
        allowed = [t for t in harness_tools if t in defn.tools_allow] if defn.tools_allow else list(harness_tools)
        denied = {t for t in allowed if t in defn.tools_deny}
        effective = [t for t in allowed if t not in denied] + list(defn.tools_extra)
        tool_names = list(dict.fromkeys(effective))  # deduplicate preserving order

        model = arguments.model or defn.model

        config = SpawnConfig(
            agent_name=defn.name,
            prompt=arguments.prompt,
            tool_names=tool_names,
            model=model,
        )

        session_key = context.metadata.get("session_key", "")
        result = await self._swarm.spawn(config, origin_session_key=session_key)

        if not result.success:
            return ToolResult(
                output=f"Error spawning agent: {result.error}",
                is_error=True,
            )

        return ToolResult(output=f"Agent spawned: {result.agent_id}")
