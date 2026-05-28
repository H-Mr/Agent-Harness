"""Hooks subsystem — lifecycle event hooks for llm-harness."""

from llm_harness.extensions.hooks.events import HookEvent
from llm_harness.extensions.hooks.schemas import (
    AgentHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HttpHookDefinition,
    PromptHookDefinition,
)
from llm_harness.extensions.hooks.types import AggregatedHookResult, HookResult
from llm_harness.extensions.hooks.loader import HookRegistry, load_hook_registry
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext

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
