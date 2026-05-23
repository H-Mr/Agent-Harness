"""Hooks subsystem — lifecycle event hooks for agent-harness."""

from agent_harness.hooks.events import HookEvent
from agent_harness.hooks.schemas import (
    AgentHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HttpHookDefinition,
    PromptHookDefinition,
)
from agent_harness.hooks.types import AggregatedHookResult, HookResult
from agent_harness.hooks.loader import HookRegistry, load_hook_registry
from agent_harness.hooks.executor import HookExecutor, HookExecutionContext

__all__ = [
    "HookEvent",
    "CommandHookDefinition",
    "PromptHookDefinition",
    "HttpHookDefinition",
    "AgentHookDefinition",
    "HookDefinition",
    "HookResult",
    "AggregatedHookResult",
    "HookRegistry",
    "load_hook_registry",
    "HookExecutor",
    "HookExecutionContext",
]
