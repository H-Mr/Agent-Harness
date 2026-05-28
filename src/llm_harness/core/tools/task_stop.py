"""Tool: TaskStopTool — stop a running agent."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.core.swarm.backend import AgentBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TaskStopInput(BaseModel):
    agent_id: str = Field(description="The agent ID to stop")


class TaskStopTool(BaseTool):
    """Stop a running sub-agent."""

    name: ClassVar[str] = "task_stop"
    description: ClassVar[str] = "Stop a running agent."
    input_model: ClassVar[type[BaseModel]] = TaskStopInput

    def __init__(self, swarm: AgentBackend) -> None:
        self._swarm = swarm

    async def execute(self, arguments: TaskStopInput, context: ToolExecutionContext) -> ToolResult:
        del context
        ok = await self._swarm.stop(arguments.agent_id)
        if not ok:
            return ToolResult(
                output=f"Error: agent '{arguments.agent_id}' not found or not running",
                is_error=True,
            )
        return ToolResult(output=f"Stopped agent {arguments.agent_id}")
