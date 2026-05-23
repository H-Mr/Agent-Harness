"""Structured observability — events, bus, and track file writer."""

from agent_harness.observability.bus import EventBus, emit, get_event_bus
from agent_harness.observability.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ConfigChanged,
    CronJobCompleted,
    CronJobTriggered,
    ErrorEvent,
    McpConnectionChanged,
    MemoryConsolidated,
    PluginLoaded,
    SessionClosed,
    SessionOpened,
    StatusEvent,
    StreamEvent,
    SubagentCompleted,
    SubagentSpawned,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from agent_harness.observability.tracker import Tracker, start_tracker_from_config

__all__ = [
    # Bus
    "EventBus",
    "emit",
    "get_event_bus",
    # Tracker
    "Tracker",
    # Loop events
    "AssistantTextDelta",
    "AssistantTurnComplete",
    "ErrorEvent",
    "StatusEvent",
    "StreamEvent",
    "ToolExecutionCompleted",
    "ToolExecutionStarted",
    # System events
    "SessionOpened",
    "SessionClosed",
    "SubagentSpawned",
    "SubagentCompleted",
    "CronJobTriggered",
    "CronJobCompleted",
    "MemoryConsolidated",
    "McpConnectionChanged",
    "PluginLoaded",
    "ConfigChanged",
]
