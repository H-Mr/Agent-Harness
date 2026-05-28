"""Tool: SendMessageTool — send a message to a running agent."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.core.swarm.backend import AgentBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class SendMessageInput(BaseModel):
    agent_id: str = Field(description="The target agent ID")
    message: str = Field(description="The message content to send")


class SendMessageTool(BaseTool):
    """Send a message to a running sub-agent."""

    name: ClassVar[str] = "send_message"
    description: ClassVar[str] = "Send a message to a running agent."
    input_model: ClassVar[type[BaseModel]] = SendMessageInput

    def __init__(self, swarm: AgentBackend) -> None:
        self._swarm = swarm

    async def execute(self, arguments: SendMessageInput, context: ToolExecutionContext) -> ToolResult:
        del context
        ok = await self._swarm.send_message(arguments.agent_id, arguments.message)
        if not ok:
            return ToolResult(
                output=f"Error: agent '{arguments.agent_id}' not found or not running",
                is_error=True,
            )
        return ToolResult(output=f"Message sent to {arguments.agent_id}")
