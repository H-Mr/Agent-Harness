"""Build a ToolRegistry from configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_harness.tools.base import ToolRegistry
from agent_harness.config.schema import ToolsConfig

# All known tools with their factory functions.
# Each entry: (name, factory(workspace: Path | None, config: ToolsConfig) -> BaseTool | None)
_TOOL_REGISTRY: dict[str, Any] = {}


def _register_all() -> None:
    """Lazily register all known tool factories. Called once on first build."""
    if _TOOL_REGISTRY:
        return

    from agent_harness.tools.filesystem import (
        EditFileTool, ListDirTool, ReadFileTool, WriteFileTool,
    )
    from agent_harness.tools.shell import ExecTool
    from agent_harness.tools.web import WebSearchTool, WebFetchTool
    from agent_harness.tools.glob_tool import GlobTool
    from agent_harness.tools.grep_tool import GrepTool
    from agent_harness.tools.notebook_edit_tool import NotebookEditTool
    from agent_harness.tools.message import MessageTool
    from agent_harness.tools.memory import MemoryReadTool, MemoryWriteTool
    from agent_harness.tools.spawn import SpawnTool

    def _no_args(cls):
        return lambda ws, cfg: cls()

    def _fs_tool(cls):
        def factory(ws, cfg):
            allowed = Path(ws).resolve() if ws and cfg.restrict_to_workspace else None
            return cls(workspace=Path(ws) if ws else None, allowed_dir=allowed)
        return factory

    def _exec(cfg: ToolsConfig, ws):
        if not cfg.exec_enable:
            return None
        return ExecTool(
            working_dir=str(ws) if ws else None,
            timeout=cfg.exec_timeout,
            restrict_to_workspace=cfg.restrict_to_workspace,
        )

    def _web_search(cfg: ToolsConfig):
        return WebSearchTool(
            provider=cfg.web_search_provider,
            max_results=cfg.web_search_max_results,
        )

    _TOOL_REGISTRY.update({
        "read_file":     _fs_tool(ReadFileTool),
        "write_file":    _fs_tool(WriteFileTool),
        "edit_file":     _fs_tool(EditFileTool),
        "list_dir":      _fs_tool(ListDirTool),
        "exec":          lambda ws, cfg: _exec(cfg, ws),
        "web_search":    lambda ws, cfg: _web_search(cfg),
        "web_fetch":     lambda ws, cfg: WebFetchTool(),
        "glob":          _no_args(GlobTool),
        "grep":          _no_args(GrepTool),
        "notebook_edit": _no_args(NotebookEditTool),
        "message":       _no_args(MessageTool),
        "write_memory":  lambda ws, cfg: MemoryWriteTool(None),
        "read_memory":   lambda ws, cfg: MemoryReadTool(None),
        "spawn":         lambda ws, cfg: None,  # requires SubagentManager — app registers
        "ask_user_question": lambda ws, cfg: None,  # requires callback — app registers
        "todo_write":    _no_args(lambda: __import__("agent_harness.tools.todo_write_tool", fromlist=["TodoWriteTool"]).TodoWriteTool()),
        "tool_search":   _no_args(lambda: __import__("agent_harness.tools.tool_search_tool", fromlist=["ToolSearchTool"]).ToolSearchTool()),
        "skill":         _no_args(lambda: __import__("agent_harness.tools.skill_tool", fromlist=["SkillTool"]).SkillTool()),
    })


def _is_enabled(tool_name: str, config: ToolsConfig) -> bool:
    """Check if a tool is enabled by config."""
    enabled = config.enabled
    disabled = config.disabled

    if tool_name in disabled:
        return False
    if "*" in enabled:
        return True
    if "none" in enabled:
        return False
    return tool_name in enabled


def build_tools_from_config(
    config: ToolsConfig,
    *,
    workspace: str | Path | None = None,
    extra_tools: list | None = None,
) -> ToolRegistry:
    """Build a ToolRegistry from a ToolsConfig.

    Usage:
        config = load_config()
        tools = build_tools_from_config(config.tools, workspace=config.agent.workspace)

    Tools that need runtime injection (message with send callback, spawn with
    SubagentManager, memory with MemoryStore) return None from the factory and
    should be registered manually by the app after build.
    """
    _register_all()

    registry = ToolRegistry()
    ws = workspace or (
        Path(config.workspace).expanduser()
        if config.workspace
        else None
    )

    for name, factory in _TOOL_REGISTRY.items():
        if not _is_enabled(name, config):
            continue
        try:
            tool = factory(ws, config)
        except Exception:
            tool = None
        if tool is not None:
            registry.register(tool)

    for tool in (extra_tools or []):
        registry.register(tool)

    return registry
