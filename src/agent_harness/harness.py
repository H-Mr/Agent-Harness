"""Harness class -- infrastructure container that holds all agent parts.

The Harness is a higher-level container that wires together the various
agent-*harness* subsystems (provider, tools, permissions, memory, sessions,
context, skills, hooks, tracker) and provides sensible defaults for each.

Usage::

    harness = Harness(
        provider=my_provider,
        tools=["read_file", "write_file", "exec", "web_search"],
        permissions="default",
        workspace=Path("~/.my-agent"),
    )

    # Or from config:
    harness = Harness.from_config(config)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent_harness.config.schema import Config, ToolsConfig
from agent_harness.context.base import ContextBuilder, SectionProvider
from agent_harness.hooks.loader import HookRegistry
from agent_harness.memory.store import MemoryStore
from agent_harness.observability.tracker import Tracker
from agent_harness.permissions.checker import PermissionChecker, PermissionDecision
from agent_harness.permissions.modes import PermissionMode
from agent_harness.permissions.settings import PermissionSettings
from agent_harness.prompts.sections import SkillsSection
from agent_harness.providers.base import LLMProvider
from agent_harness.providers.registry import detect_provider, find_by_name
from agent_harness.session.manager import SessionManager
from agent_harness.skills.registry import SkillRegistry
from agent_harness.tools.base import ToolRegistry
from agent_harness.tools.builder import build_tools_from_config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases for pipeline callbacks
# ---------------------------------------------------------------------------

ToolCheckCallback = Callable[
    [str, "BaseTool", Any],  # (tool_name, tool_instance, parsed_args)
    Awaitable[PermissionDecision],
]
"""Signature: async (tool_name, tool_instance, parsed_args) -> PermissionDecision"""

BuildContextCallback = Callable[
    ["InboundMessage", list[dict[str, Any]]],  # (msg, history)
    Awaitable[list[dict[str, Any]]],
]
"""Signature: async (msg, history) -> list[dict[str, Any]]"""

ErrorCallback = Callable[
    [Exception, str],  # (exception, context)
    Awaitable[str | None],  # return user-facing message or None
]
"""Signature: async (exception, context) -> str | None"""


# ---------------------------------------------------------------------------
# Inline helpers (avoid circular / heavy imports at module level)
# ---------------------------------------------------------------------------


def _list_to_tool_registry(tool_names: list[str]) -> ToolRegistry:
    """Build a ToolRegistry from a list of tool name strings."""
    from agent_harness.tools.filesystem import (
        EditFileTool,
        ListDirTool,
        ReadFileTool,
        WriteFileTool,
    )
    from agent_harness.tools.shell import ExecTool
    from agent_harness.tools.web import WebSearchTool, WebFetchTool
    from agent_harness.tools.glob_tool import GlobTool
    from agent_harness.tools.grep_tool import GrepTool
    from agent_harness.tools.notebook_edit_tool import NotebookEditTool
    from agent_harness.tools.message import MessageTool
    from agent_harness.tools.memory import MemoryReadTool, MemoryWriteTool

    _TOOL_FACTORIES: dict[str, type] = {
        "read_file": ReadFileTool,
        "write_file": WriteFileTool,
        "edit_file": EditFileTool,
        "list_dir": ListDirTool,
        "exec": ExecTool,
        "web_search": WebSearchTool,
        "web_fetch": WebFetchTool,
        "glob": GlobTool,
        "grep": GrepTool,
        "notebook_edit": NotebookEditTool,
        "message": MessageTool,
        "memory_read": MemoryReadTool,
        "memory_write": MemoryWriteTool,
    }

    registry = ToolRegistry()
    for name in tool_names:
        factory = _TOOL_FACTORIES.get(name)
        if factory is not None:
            tool = factory()
            if tool is not None:
                registry.register(tool)
        else:
            log.warning("Unknown tool name in shorthand list: %r", name)
    return registry


def _load_skills_from_dir_list(dirs: list[str | Path]) -> SkillRegistry:
    """Load skills from a list of directory paths and return a SkillRegistry."""
    from agent_harness.skills.loader import load_skills_from_dirs

    registry = SkillRegistry()
    for entry in dirs:
        loaded = load_skills_from_dirs([entry])
        for skill in loaded:
            registry.register(skill)
    return registry


def _load_hooks_from_path(path: str | Path) -> HookRegistry:
    """Load hooks from a directory or JSON file path.

    Looks for a ``hooks.json`` file inside the given directory, or loads
    the JSON file directly if *path* points to a file.
    """
    import json

    from pydantic import ValidationError

    from agent_harness.hooks.events import HookEvent
    from agent_harness.hooks.schemas import HookDefinition

    resolved = Path(path).expanduser().resolve()

    if resolved.is_file():
        hook_path = resolved
    elif resolved.is_dir():
        hook_path = resolved / "hooks.json"
    else:
        log.warning("Hooks path %s does not exist, using empty HookRegistry", resolved)
        return HookRegistry()

    if not hook_path.exists():
        log.warning("No hooks file found at %s, using empty HookRegistry", hook_path)
        return HookRegistry()

    try:
        raw = json.loads(hook_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed to parse hooks file %s: %s", hook_path, exc)
        return HookRegistry()

    if not isinstance(raw, dict):
        log.warning("Hooks file %s contains a JSON %s instead of an object; expected {event: [hooks...]}",
                     hook_path, type(raw).__name__)
        return HookRegistry()

    registry = HookRegistry()
    for raw_event, hooks_list in raw.items():
        try:
            event = HookEvent(raw_event)
        except ValueError:
            log.warning("Unknown hook event %r, skipping", raw_event)
            continue
        for hook_data in hooks_list:
            if isinstance(hook_data, dict):
                try:
                    hook = HookDefinition(**hook_data)
                except ValidationError as exc:
                    log.warning("Invalid hook definition %r: %s", hook_data, exc)
                    continue
                registry.register(event, hook)
    return registry


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class Harness:
    """Infrastructure container that holds all agent parts.

    Accepts simplified shorthand forms for all components and resolves
    them to concrete instances.  Designed to work with the Agent class
    that consumes these resolved parts.

    Shorthand resolution table
    ==========================

    =============== ===========================================
    Parameter       Accepted types
    =============== ===========================================
    tools           ``ToolRegistry | ToolsConfig | list[str] | None``
    permissions     ``PermissionChecker | PermissionSettings | str("default"|"plan"|"auto") | None``
    memory          ``MemoryStore | str(path) | Path | None``
    sessions        ``SessionManager | str(path) | Path | None``
    context         ``ContextBuilder | list[SectionProvider] | None``
    skills          ``SkillRegistry | list[str | Path] | None``
    hooks           ``HookRegistry | str(path) | Path | None``
    tracker         ``str(path) | Path | None``
    =============== ===========================================
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        workspace: str | Path = Path.cwd(),
        tools: ToolRegistry | ToolsConfig | list[str] | None = None,
        permissions: PermissionChecker | PermissionSettings | str | None = None,
        memory: MemoryStore | str | Path | None = None,
        sessions: SessionManager | str | Path | None = None,
        context: ContextBuilder | list[SectionProvider] | None = None,
        skills: SkillRegistry | list[str | Path] | None = None,
        hooks: HookRegistry | str | Path | None = None,
        tracker: str | Path | None = None,
        on_tool_check: ToolCheckCallback | None = None,
        on_build_context: BuildContextCallback | None = None,
        on_error: ErrorCallback | None = None,
        context_window_tokens: int = 64_000,
        max_completion_tokens: int = 4096,
    ) -> None:
        workspace = Path(workspace).expanduser().resolve()

        # Resolve all shorthand forms to concrete instances
        self.provider = provider
        self.workspace = workspace
        self.tools = self._resolve_tools(tools)
        self.permissions = self._resolve_permissions(permissions)
        self.memory = self._resolve_memory(memory)
        self.sessions = self._resolve_sessions(sessions)
        self.context = self._resolve_context(context)
        self.skills = self._resolve_skills(skills)
        self.hooks = self._resolve_hooks(hooks)
        self.tracker = self._resolve_tracker(tracker)

        # Pipeline callbacks (defaults assigned if caller passed None)
        self.on_tool_check = on_tool_check or self._default_tool_check
        self.on_build_context = on_build_context or self._default_build_context
        self.on_error = on_error or self._default_on_error

        # Generation / capacity configuration
        self.context_window_tokens = context_window_tokens
        self.max_completion_tokens = max_completion_tokens

        # Auto-inject SkillsSection into context when skills are available
        self._auto_inject_skills()

    # ------------------------------------------------------------------
    # Resolver methods
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_tools(
        tools: ToolRegistry | ToolsConfig | list[str] | None,
    ) -> ToolRegistry:
        """Resolve *tools* to a ``ToolRegistry`` instance."""
        if tools is None:
            return ToolRegistry()
        if isinstance(tools, ToolRegistry):
            return tools
        if isinstance(tools, list):
            return _list_to_tool_registry(tools)
        if isinstance(tools, ToolsConfig):
            return build_tools_from_config(tools)
        raise TypeError(f"Unsupported tools type: {type(tools).__name__}")

    @staticmethod
    def _resolve_permissions(
        permissions: PermissionChecker | PermissionSettings | str | None,
    ) -> PermissionChecker:
        """Resolve *permissions* to a ``PermissionChecker`` instance."""
        if permissions is None:
            return PermissionChecker(PermissionSettings())
        if isinstance(permissions, PermissionChecker):
            return permissions
        if isinstance(permissions, PermissionSettings):
            return PermissionChecker(permissions)
        if isinstance(permissions, str):
            mode_map = {
                "default": PermissionMode.DEFAULT,
                "plan": PermissionMode.PLAN,
                "auto": PermissionMode.FULL_AUTO,
                "full_auto": PermissionMode.FULL_AUTO,
            }
            mode = mode_map.get(permissions.lower())
            if mode is None:
                raise ValueError(
                    f"Unknown permission mode shorthand: {permissions!r}. "
                    f"Expected one of: {', '.join(mode_map)}"
                )
            return PermissionChecker(PermissionSettings(mode=mode))
        raise TypeError(
            f"Unsupported permissions type: {type(permissions).__name__}"
        )

    @staticmethod
    def _resolve_memory(
        memory: MemoryStore | str | Path | None,
    ) -> MemoryStore | None:
        """Resolve *memory* to a ``MemoryStore`` instance, or ``None``."""
        if memory is None:
            return None
        if isinstance(memory, MemoryStore):
            return memory
        if isinstance(memory, (str, Path)):
            return MemoryStore(Path(memory).expanduser().resolve())
        raise TypeError(f"Unsupported memory type: {type(memory).__name__}")

    @staticmethod
    def _resolve_sessions(
        sessions: SessionManager | str | Path | None,
    ) -> SessionManager | None:
        """Resolve *sessions* to a ``SessionManager`` instance, or ``None``."""
        if sessions is None:
            return None
        if isinstance(sessions, SessionManager):
            return sessions
        if isinstance(sessions, (str, Path)):
            return SessionManager(Path(sessions).expanduser().resolve())
        raise TypeError(f"Unsupported sessions type: {type(sessions).__name__}")

    @staticmethod
    def _resolve_context(
        context: ContextBuilder | list[SectionProvider] | None,
    ) -> ContextBuilder:
        """Resolve *context* to a ``ContextBuilder`` instance."""
        if context is None:
            return ContextBuilder()
        if isinstance(context, ContextBuilder):
            return context
        if isinstance(context, list):
            builder = ContextBuilder()
            for provider in context:
                builder.add_provider(provider)
            return builder
        raise TypeError(f"Unsupported context type: {type(context).__name__}")

    @staticmethod
    def _resolve_skills(
        skills: SkillRegistry | list[str | Path] | None,
    ) -> SkillRegistry | None:
        """Resolve *skills* to a ``SkillRegistry`` instance, or ``None``."""
        if skills is None:
            return None
        if isinstance(skills, SkillRegistry):
            return skills
        if isinstance(skills, list):
            return _load_skills_from_dir_list(skills)
        raise TypeError(f"Unsupported skills type: {type(skills).__name__}")

    @staticmethod
    def _resolve_hooks(
        hooks: HookRegistry | str | Path | None,
    ) -> HookRegistry | None:
        """Resolve *hooks* to a ``HookRegistry`` instance, or ``None``."""
        if hooks is None:
            return None
        if isinstance(hooks, HookRegistry):
            return hooks
        if isinstance(hooks, (str, Path)):
            return _load_hooks_from_path(hooks)
        raise TypeError(f"Unsupported hooks type: {type(hooks).__name__}")

    @staticmethod
    def _resolve_tracker(
        tracker: str | Path | None,
    ) -> Tracker | None:
        """Resolve *tracker* to a ``Tracker`` instance, or ``None``."""
        if tracker is None:
            return None
        return Tracker(Path(tracker).expanduser().resolve())

    # ------------------------------------------------------------------
    # Default pipeline callbacks
    # ------------------------------------------------------------------

    async def _default_tool_check(
        self,
        tool_name: str,
        tool: "BaseTool",
        parsed_args: Any,
    ) -> PermissionDecision:
        """Default tool check: delegate to the configured ``PermissionChecker``."""
        return self.permissions.evaluate(
            tool_name,
            is_read_only=tool.is_read_only(parsed_args),
        )

    async def _default_build_context(
        self,
        msg: "InboundMessage",
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Default context builder: assemble system prompt and message list."""
        system = await self.context.build_system_prompt()
        return self.context.build_messages(
            system,
            history,
            msg.content,
            channel=getattr(msg, "channel", None),
            chat_id=getattr(msg, "chat_id", None),
        )

    async def _default_on_error(self, exception: Exception, context: str) -> str | None:
        """Default error handler: log the exception and return a user-facing message."""
        log.exception("Error in %s: %s", context, exception)
        return "Sorry, I encountered an error processing your request."

    # ------------------------------------------------------------------
    # Skills auto-injection
    # ------------------------------------------------------------------

    def _auto_inject_skills(self) -> None:
        """Add a ``SkillsSection`` to the context builder when skills are configured."""
        if self.skills is not None:
            try:
                has_skills = self.skills.list_skills()
            except AttributeError:
                log.warning("Skills object has no list_skills() method, skipping auto-inject")
                has_skills = False
            if has_skills:
                section = SkillsSection(self.skills)
                self.context.add_provider(section)

    # ------------------------------------------------------------------
    # Factory: from_config
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        extra_tools: list | None = None,
    ) -> Harness:
        """Create a ``Harness`` from a :class:`Config <agent_harness.config.schema.Config>` schema object.

        Usage::

            from agent_harness import load_config
            from agent_harness.harness import Harness

            config = load_config()
            harness = Harness.from_config(config)

        Args:
            config: A fully populated ``Config`` instance.
            extra_tools: Optional list of extra ``BaseTool`` instances to register
                on top of the tools declared by *config.tools*.

        Returns:
            A fully configured ``Harness`` instance.
        """
        workspace = config.workspace_path

        # Resolve provider --------------------------------------------------
        provider = cls._provider_from_config(config)
        if provider is None:
            raise ValueError(
                f"Cannot create Harness: unable to resolve LLM provider for model={config.agent.model!r}. "
                f"Set agent.provider explicitly in config, or install the required provider SDK."
            )

        # Resolve tools -----------------------------------------------------
        tools = build_tools_from_config(
            config.tools,
            workspace=workspace,
            extra_tools=extra_tools,
        )

        # Resolve permissions -----------------------------------------------
        permission_settings = PermissionSettings(
            mode=config.permission.mode,
            allowed_tools=config.permission.allowed_tools,
            denied_tools=config.permission.denied_tools,
        )
        permissions = PermissionChecker(permission_settings)

        # Auto-create memory and sessions from workspace --------------------
        memory = MemoryStore(workspace / "memory")
        sessions = SessionManager(workspace)

        # Resolve tracker ---------------------------------------------------
        tracker: str | Path | None = None
        if config.observability and config.observability.track_file:
            tracker = config.observability.track_file

        return cls(
            provider=provider,
            workspace=workspace,
            tools=tools,
            permissions=permissions,
            memory=memory,
            sessions=sessions,
            context=None,
            skills=None,
            hooks=None,
            tracker=tracker,
            context_window_tokens=getattr(config.agent, "context_window_tokens", 64_000),
            max_completion_tokens=config.agent.max_tokens,
        )

    # ------------------------------------------------------------------
    # Provider resolution (internal helper for from_config)
    # ------------------------------------------------------------------

    @staticmethod
    def _provider_from_config(config: Config) -> LLMProvider:
        """Resolve an ``LLMProvider`` from *config*.

        Uses the ``ProviderSpec`` machinery in the provider registry to
        auto-detect the correct provider when ``config.agent.provider``
        is ``"auto"``.

        Raises:
            ValueError: If the provider cannot be resolved or instantiated.
        """
        provider_name = config.agent.provider
        model = config.agent.model
        api_key = config.agent.api_key
        api_base = config.agent.api_base

        # Resolve spec ------------------------------------------------------
        if provider_name and provider_name.lower() != "auto":
            spec = find_by_name(provider_name)
            if spec is None:
                log.warning("Unknown provider %r in config, cannot create provider", provider_name)
                raise ValueError(
                    f"Unknown provider {provider_name!r} in config. "
                    f"Available: anthropic, openai_compat, azure_openai"
                )
        else:
            spec = detect_provider(model, api_key=api_key, api_base=api_base)
            if spec is None:
                log.warning(
                    "Could not auto-detect provider for model=%r, api_key=..., api_base=%r",
                    model,
                    api_base,
                )
                raise ValueError(
                    f"Could not auto-detect provider for model={model!r} with api_base={api_base!r}. "
                    f"Set agent.provider explicitly in config, or install the required provider SDK."
                )

        # Instantiate -------------------------------------------------------
        # Provider implementations are optional dependencies — catch ImportError
        # so users who only have one provider SDK installed aren't forced to
        # install every optional dependency.
        try:
            if spec.backend == "anthropic":
                from agent_harness.providers.anthropic_provider import AnthropicProvider

                return AnthropicProvider(
                    api_key=api_key or None,
                )
            elif spec.backend in ("openai_compat", "azure_openai"):
                from agent_harness.providers.openai_compat_provider import (
                    OpenAICompatProvider,
                )

                return OpenAICompatProvider(
                    api_key=api_key or None,
                    api_base=api_base or spec.default_api_base or None,
                    model=model,
                )
            else:
                log.warning(
                    "Unsupported provider backend: %s (spec=%s)", spec.backend, spec.name
                )
                raise ValueError(
                    f"Unsupported provider backend: {spec.backend} (spec={spec.name}). "
                    f"Supported backends: anthropic, openai_compat, azure_openai"
                )
        except ImportError as exc:
            log.warning(
                "Could not instantiate provider %r (backend=%s): missing optional dependency: %s",
                spec.name,
                spec.backend,
                exc,
            )
            raise ValueError(
                f"Could not instantiate provider {spec.name!r} (backend={spec.backend}): "
                f"missing optional dependency: {exc}"
            )
