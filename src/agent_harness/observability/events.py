"""Structured observability events.

Loop events (emitted inside run_react_loop):
  AssistantTextDelta, AssistantTurnComplete, ToolExecutionStarted,
  ToolExecutionCompleted, ErrorEvent, StatusEvent

System events (emitted by infrastructure modules):
  SessionOpened, SessionClosed, SubagentSpawned, SubagentCompleted,
  CronJobTriggered, CronJobCompleted, MemoryConsolidated, McpConnectionChanged,
  PluginLoaded, ConfigChanged
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---- base ----

def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---- loop events ----


@dataclass(frozen=True)
class AssistantTextDelta:
    text: str
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class AssistantTurnComplete:
    content: str | None
    usage: dict[str, int]
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class ToolExecutionStarted:
    tool_name: str
    tool_input: dict[str, Any]
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class ToolExecutionCompleted:
    tool_name: str
    output: str
    is_error: bool = False
    duration_ms: float | None = None
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class ErrorEvent:
    message: str
    recoverable: bool = True
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class StatusEvent:
    message: str
    timestamp: str = field(default_factory=_now)


# ---- system events ----


@dataclass(frozen=True)
class SessionOpened:
    session_key: str
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class SessionClosed:
    session_key: str
    message_count: int = 0
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class SubagentSpawned:
    task_id: str
    label: str
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class SubagentCompleted:
    task_id: str
    label: str
    status: str  # "ok" | "error"
    duration_ms: float | None = None
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class CronJobTriggered:
    job_id: str
    job_name: str
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class CronJobCompleted:
    job_id: str
    job_name: str
    status: str  # "ok" | "error"
    duration_ms: float | None = None
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class MemoryConsolidated:
    session_key: str
    messages_archived: int
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class McpConnectionChanged:
    server_name: str
    connected: bool
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class PluginLoaded:
    plugin_name: str
    timestamp: str = field(default_factory=_now)


@dataclass(frozen=True)
class ConfigChanged:
    key: str
    timestamp: str = field(default_factory=_now)


# ---- union types ----

LoopEvent = (
    AssistantTextDelta
    | AssistantTurnComplete
    | ToolExecutionStarted
    | ToolExecutionCompleted
    | ErrorEvent
    | StatusEvent
)

SystemEvent = (
    SessionOpened
    | SessionClosed
    | SubagentSpawned
    | SubagentCompleted
    | CronJobTriggered
    | CronJobCompleted
    | MemoryConsolidated
    | McpConnectionChanged
    | PluginLoaded
    | ConfigChanged
)

# Full union for type-checking
StreamEvent = LoopEvent | SystemEvent
