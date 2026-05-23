"""Agent Harness — reusable agent infrastructure base.

Usage:
    from agent_harness import AgentLoop, LoopCallbacks, TurnResult
    from agent_harness import BaseTool, ToolRegistry, ToolResult, ToolExecutionContext
    from agent_harness import LLMProvider, LLMResponse, ProviderSpec, detect_provider
    from agent_harness import MessageBus, InboundMessage, OutboundMessage
    from agent_harness import ContextBuilder, SectionProvider
    from agent_harness import MemoryStore, SkillRegistry, SkillDefinition
    from agent_harness import Config, load_config, CronService, CronJob
"""

from agent_harness._version import __version__

# Tools
from agent_harness.tools.base import (
    BaseTool,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
)

# Providers
from agent_harness.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)
from agent_harness.providers.registry import (
    PROVIDERS,
    ProviderSpec,
    detect_provider,
    find_by_name,
)

# Bus
from agent_harness.bus.events import InboundMessage, OutboundMessage
from agent_harness.bus.queue import MessageBus

# Loop
from agent_harness.loop.agent import AgentLoop, LoopCallbacks, TurnResult

# Context
from agent_harness.context.base import ContextBuilder, SectionProvider

# Memory
from agent_harness.memory.store import MemoryStore

# Skills
from agent_harness.skills.loader import load_skills_from_dirs, parse_skill_markdown
from agent_harness.skills.registry import SkillRegistry
from agent_harness.skills.types import SkillDefinition

# Cron
from agent_harness.cron.service import CronService
from agent_harness.cron.types import CronJob, CronPayload, CronSchedule, CronStore

# Permissions
from agent_harness.permissions.checker import PermissionChecker
from agent_harness.permissions.modes import PermissionMode
from agent_harness.permissions.settings import PermissionSettings

# Config
from agent_harness.config.loader import get_default_config_path, load_config, save_config
from agent_harness.config.schema import AgentConfig, Config, ObservabilityConfig, ToolsConfig
from agent_harness.tools.builder import build_tools_from_config

# Observability
from agent_harness.observability.tracker import start_tracker_from_config

# MCP
from agent_harness.mcp.client import MCPToolWrapper, connect_mcp_servers

__all__ = [
    "__version__",
    # Tools
    "BaseTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    # Providers
    "GenerationSettings",
    "LLMProvider",
    "LLMResponse",
    "ToolCallRequest",
    "PROVIDERS",
    "ProviderSpec",
    "detect_provider",
    "find_by_name",
    # Bus
    "InboundMessage",
    "OutboundMessage",
    "MessageBus",
    # Loop
    "AgentLoop",
    "LoopCallbacks",
    "TurnResult",
    # Context
    "ContextBuilder",
    "SectionProvider",
    # Memory
    "MemoryStore",
    # Skills
    "SkillDefinition",
    "SkillRegistry",
    "load_skills_from_dirs",
    "parse_skill_markdown",
    # Cron
    "CronJob",
    "CronPayload",
    "CronSchedule",
    "CronStore",
    "CronService",
    # Permissions
    "PermissionChecker",
    "PermissionMode",
    "PermissionSettings",
    # Config
    "AgentConfig",
    "Config",
    "ObservabilityConfig",
    "ToolsConfig",
    "build_tools_from_config",
    "get_default_config_path",
    "load_config",
    "save_config",
    # Observability
    "start_tracker_from_config",
    # MCP
    "MCPToolWrapper",
    "connect_mcp_servers",
    # Provider implementations (lazy, depends on optional SDKs)
    "AnthropicProvider",
    "OpenAICompatProvider",
]


def __getattr__(name: str):
    """Lazy-load provider implementations (optional SDKs: anthropic, openai)."""
    if name == "AnthropicProvider":
        from agent_harness.providers.anthropic_provider import AnthropicProvider as _cls
        return _cls
    if name == "OpenAICompatProvider":
        from agent_harness.providers.openai_compat_provider import OpenAICompatProvider as _cls
        return _cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
