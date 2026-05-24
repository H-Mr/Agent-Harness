"""Tool for deleting cron jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

if TYPE_CHECKING:
    from agent_harness.cron.service import CronService


class CronDeleteInput(BaseModel):
    """Arguments for deleting a cron job."""

    job_id: str = Field(description="Identifier of the job to delete")


class CronDeleteTool(BaseTool):
    """Delete (remove) a cron job."""

    name = "cron_delete"
    description = "Delete a cron job by ID"
    input_model = CronDeleteInput

    def __init__(self, cron_service: "CronService") -> None:
        self._cron = cron_service

    async def execute(
        self, arguments: CronDeleteInput, context: ToolExecutionContext
    ) -> ToolResult:
        del context
        removed = self._cron.remove_job(arguments.job_id)
        if not removed:
            return ToolResult(
                output=f"Job not found: {arguments.job_id}",
                is_error=True,
            )
        return ToolResult(output=f"Job deleted: {arguments.job_id}")
