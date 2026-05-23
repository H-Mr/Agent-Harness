"""Agent Harness configuration schema."""

from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict


class AgentConfig(BaseModel):
    """Core agent settings."""
    model: str = "claude-sonnet-4-6"
    provider: str = "auto"  # "auto" means auto-detect from model/key
    api_key: str = ""
    api_base: str | None = None
    workspace: str = "~/.agent-harness/workspace"
    max_tokens: int = 8192
    max_iterations: int = 40
    temperature: float = 0.7
    reasoning_effort: str | None = None
    timezone: str = "UTC"

    model_config = ConfigDict(env_prefix="HARNESS_AGENT__")


class PermissionConfig(BaseModel):
    """Permission and approval mode settings."""
    mode: str = "default"  # default, plan, full_auto
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)


class SandboxConfig(BaseModel):
    """Sandboxed command execution settings."""
    enabled: bool = False
    fail_if_unavailable: bool = False


class ToolsConfig(BaseModel):
    """Tool execution settings and per-tool enable/disable."""
    exec_timeout: int = 60
    exec_enable: bool = True
    web_search_provider: str = "duckduckgo"
    web_search_max_results: int = 5
    # Per-tool enable flags. "*" enables all, "none" enables none.
    # Otherwise, list the tools to enable by name.
    enabled: list[str] = Field(default_factory=lambda: ["*"])
    disabled: list[str] = Field(default_factory=list)
    # Tool-specific options
    workspace: str | None = None
    restrict_to_workspace: bool = False


class ObservabilityConfig(BaseModel):
    """Observability settings."""
    # Track file path — when set, Tracker auto-starts and writes JSONL
    track_file: str | None = None  # e.g. "~/.agent-harness/track.jsonl"


class Config(BaseModel):
    """Root configuration for an agent harness application."""
    agent: AgentConfig = Field(default_factory=AgentConfig)
    permission: PermissionConfig = Field(default_factory=PermissionConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    model_config = ConfigDict(env_prefix="HARNESS_")

    @property
    def workspace_path(self) -> Path:
        return Path(self.agent.workspace).expanduser()
