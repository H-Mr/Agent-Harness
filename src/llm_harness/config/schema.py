"""Configuration schema via Pydantic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    provider: str = "auto"
    api_key: str = ""
    api_base: str = ""
    max_tokens: int = 4096
    context_window_tokens: int = 64_000


class ToolsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: [
        "read_file", "write_file", "edit_file", "exec",
        "web_search", "web_fetch", "glob", "grep",
        "memory_read", "memory_write",
        "agent", "send_message", "task_stop",
        "task_create", "task_list", "task_update",
        "cron_create", "cron_list", "cron_delete",
        "ask_user_question",
    ])
    disabled: list[str] = Field(default_factory=list)


class PermissionConfig(BaseModel):
    mode: str = "default"
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)


class SandboxConfig(BaseModel):
    backend: str = "opensandbox"
    base_url: str = "http://localhost:8080"


class MemoryConfig(BaseModel):
    backend: str = "tencentdb"
    base_url: str = "http://localhost:8420"


class ObservabilityConfig(BaseModel):
    track_file: str = ""


class ChannelConfig(BaseModel):
    type: str = "cli"
    settings: dict[str, Any] = Field(default_factory=dict)


class Config(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    permission: PermissionConfig = Field(default_factory=PermissionConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    channels: list[ChannelConfig] = Field(default_factory=list)
    workspace: str = "."

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser().resolve()
