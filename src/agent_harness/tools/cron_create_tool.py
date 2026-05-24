"""Tool for creating cron jobs."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from agent_harness.cron.types import CronSchedule
from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

if TYPE_CHECKING:
    from agent_harness.cron.service import CronService

_INTERVAL_RE = re.compile(r"^(\d+)(ms|s|m|h|d)?$")


def _parse_interval(text: str) -> int:
    """Parse a human-readable interval string into milliseconds.

    Supports formats like ``30s``, ``5m``, ``1h``, ``1d``, or a raw
    number of seconds (e.g. ``3600``).
    """
    m = _INTERVAL_RE.match(text.strip())
    if not m:
        raise ValueError(
            f"Invalid interval: {text!r}. "
            f"Use e.g. '30s', '5m', '1h', '1d' or a raw number of seconds."
        )
    value = int(m.group(1))
    unit = m.group(2) or "s"
    multipliers = {"ms": 1, "s": 1000, "m": 60000, "h": 3_600_000, "d": 86_400_000}
    return value * multipliers[unit]


def _parse_at_timestamp(text: str) -> int:
    """Parse an ISO 8601 datetime or unix-milliseconds string into ms since epoch.

    Naive datetimes are assumed to be UTC.
    """
    text = text.strip()
    # Raw ms timestamp
    try:
        return int(text)
    except ValueError:
        pass
    # ISO 8601
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(
            f"Invalid timestamp: {text!r}. "
            f"Use ISO 8601 (e.g. '2026-05-25T09:00:00Z') or unix ms."
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class CronCreateInput(BaseModel):
    """Arguments for creating a cron job."""

    name: str = Field(description="Name for the cron job")
    schedule_kind: Literal["at", "every", "cron"] = Field(
        description="Type of schedule: 'at' (one-shot), 'every' (repeating), 'cron' (cron expression)"
    )
    schedule_expr: str = Field(
        description=(
            "Schedule expression whose meaning depends on *schedule_kind*:\n"
            "- ``cron``: a cron expression such as ``'0 9 * * *'``\n"
            "- ``every``: a human interval such as ``'30s'``, ``'5m'``, ``'1h'``, ``'1d'``\n"
            "- ``at``: an ISO 8601 datetime such as ``'2026-05-25T09:00:00Z'`` or unix ms"
        )
    )
    message: str = Field(description="Message content delivered when the job fires")
    channel: str | None = Field(default=None, description="Channel name for delivery (e.g. 'whatsapp')")
    chat_id: str | None = Field(default=None, description="Recipient / chat identifier")
    tz: str | None = Field(default=None, description="Timezone name (only meaningful for 'cron' schedules)")


class CronCreateTool(BaseTool):
    """Create a new scheduled cron job."""

    name = "cron_create"
    description = "Create a new scheduled cron job"
    input_model = CronCreateInput

    def __init__(self, cron_service: "CronService") -> None:
        self._cron = cron_service

    async def execute(
        self, arguments: CronCreateInput, context: ToolExecutionContext
    ) -> ToolResult:
        del context
        try:
            schedule = self._build_schedule(arguments)
            deliver = bool(arguments.channel or arguments.chat_id)
            job = self._cron.add_job(
                name=arguments.name,
                schedule=schedule,
                message=arguments.message,
                deliver=deliver,
                channel=arguments.channel,
                to=arguments.chat_id,
            )
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Job created: {job.id}")

    @staticmethod
    def _build_schedule(args: CronCreateInput) -> CronSchedule:
        kind = args.schedule_kind
        expr = args.schedule_expr
        if kind == "cron":
            return CronSchedule(kind="cron", expr=expr, tz=args.tz)
        if kind == "every":
            return CronSchedule(kind="every", every_ms=_parse_interval(expr))
        # kind == "at"
        return CronSchedule(kind="at", at_ms=_parse_at_timestamp(expr))
