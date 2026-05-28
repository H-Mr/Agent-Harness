"""Permission settings model."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm_harness.core.permissions.modes import PermissionMode


class PathRuleConfig(BaseModel):
    """A glob-based path permission rule configuration."""

    pattern: str
    allow: bool = True


class PermissionSettings(BaseModel):
    """Configuration for permission checking."""

    mode: PermissionMode = PermissionMode.DEFAULT
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    path_rules: list[PathRuleConfig] = Field(default_factory=list)
    denied_commands: list[str] = Field(default_factory=list)
