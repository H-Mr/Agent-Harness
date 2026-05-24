"""Tool for listing cron jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agent_harness.cron.types import CronJob, CronSchedule
from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

if TYPE_CHECKING:
    from agent_harness.cron.service import CronService


def _format_interval(ms: int) -> str:
    """Format a millisecond duration in a human-friendly way."""
    if ms % 86_400_000 == 0:
        return f"{ms // 86_400_000}d"
    if ms % 3_600_000 == 0:
        return f"{ms // 3_600_000}h"
    if ms % 60_000 == 0:
        return f"{ms // 60_000}m"
    if ms % 1_000 == 0:
        return f"{ms // 1_000}s"
    return f"{ms}ms"


def _format_schedule(schedule: CronSchedule) -> str:
    """Format a CronSchedule as a compact one-line string."""
    if schedule.kind == "every":
        return f"every {_format_interval(schedule.every_ms)}" if schedule.every_ms else "every ?"
    if schedule.kind == "at":
        return f"at {schedule.at_ms}" if schedule.at_ms else "at ?"
    return f"cron {schedule.expr}" if schedule.expr else "cron ?"


def _format_datetime(ts_ms: int | None) -> str:
    """Format a ms timestamp as a human-readable datetime, or ``-``."""
    if ts_ms is None:
        return "-"
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_job(job: CronJob) -> str:
    """Format one CronJob as a single-line string."""
    enabled = "yes" if job.enabled else "no"
    next_run = _format_datetime(job.state.next_run_at_ms)
    schedule = _format_schedule(job.schedule)
    return f"{job.id:<10} {job.name:<20} {enabled:<7} {next_run:<21} {schedule}"


class CronListInput(BaseModel):
    """Arguments for listing cron jobs."""

    include_disabled: bool = Field(
        default=False,
        description="Whether to include disabled jobs in the listing",
    )


class CronListTool(BaseTool):
    """List cron jobs."""

    name = "cron_list"
    description = "List scheduled cron jobs"
    input_model = CronListInput

    def __init__(self, cron_service: "CronService") -> None:
        self._cron = cron_service

    def is_read_only(self, arguments: CronListInput) -> bool:
        del arguments
        return True

    async def execute(
        self, arguments: CronListInput, context: ToolExecutionContext
    ) -> ToolResult:
        del context
        jobs = self._cron.list_jobs(include_disabled=arguments.include_disabled)
        if not jobs:
            return ToolResult(output="(no cron jobs)")

        header = f"{'ID':<10} {'NAME':<20} {'ENABLED':<7} {'NEXT RUN (UTC)':<21} SCHEDULE"
        lines = [header, "-" * 80, *(_format_job(j) for j in jobs)]
        lines.append(f"\n({len(jobs)} job{'s' if len(jobs) != 1 else ''} total)")
        return ToolResult(output="\n".join(lines))
