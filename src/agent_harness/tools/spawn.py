"""Spawn tool for creating background subagents.

Ported from nanobot with interface adapted to agent-harness BaseTool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

if TYPE_CHECKING:
    from agent_harness.coordinator.subagent import SubagentManager


# ---------------------------------------------------------------------------
# Pydantic input model
# ---------------------------------------------------------------------------


class SpawnInput(BaseModel):
    """Input for the spawn tool."""

    task: str = Field(description="The task for the subagent to complete")
    label: str | None = Field(
        default=None, description="Optional short label for the task (for display)"
    )


# ---------------------------------------------------------------------------
# SpawnTool
# ---------------------------------------------------------------------------


class SpawnTool(BaseTool):
    """Tool to spawn a subagent for background task execution."""

    name: str = "spawn"
    description: str = (
        "Spawn a subagent to handle a task in the background. "
        "Use this for complex or time-consuming tasks that can run independently. "
        "The subagent will complete the task and report back when done. "
        "For deliverables or existing projects, inspect the workspace first "
        "and use a dedicated subdirectory when helpful."
    )
    input_model: type[BaseModel] = SpawnInput

    def __init__(self, manager: SubagentManager):
        self._manager = manager
        self._origin_channel: str = "cli"
        self._origin_chat_id: str = "direct"
        self._session_key: str = "cli:direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    async def execute(
        self, arguments: SpawnInput, context: ToolExecutionContext
    ) -> ToolResult:
        """Spawn a subagent to execute the given task."""
        del context
        result = await self._manager.spawn(
            task=arguments.task,
            label=arguments.label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
        )
        return ToolResult(output=result)
