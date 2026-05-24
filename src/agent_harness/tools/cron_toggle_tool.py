"""Tool for enabling/disabling cron jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

if TYPE_CHECKING:
    from agent_harness.cron.service import CronService


class CronToggleInput(BaseModel):
    """Arguments for toggling a cron job."""

    job_id: str = Field(description="Identifier of the job to toggle")
    enabled: bool = Field(description="Whether the job should be enabled")


class CronToggleTool(BaseTool):
    """Enable or disable a cron job."""

    name = "cron_toggle"
    description = "Enable or disable a cron job"
    input_model = CronToggleInput

    def __init__(self, cron_service: "CronService") -> None:
        self._cron = cron_service

    async def execute(
        self, arguments: CronToggleInput, context: ToolExecutionContext
    ) -> ToolResult:
        del context
        job = self._cron.enable_job(arguments.job_id, enabled=arguments.enabled)
        if job is None:
            return ToolResult(
                output=f"Job not found: {arguments.job_id}",
                is_error=True,
            )
        status = "enabled" if arguments.enabled else "disabled"
        return ToolResult(output=f"Job {job.id} {status}")
