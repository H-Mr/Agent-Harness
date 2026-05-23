"""Plugin data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_harness.plugins.schemas import PluginManifest
from agent_harness.skills.types import SkillDefinition


@dataclass
class LoadedPlugin:
    """A loaded plugin with its manifest, skills, and metadata."""

    manifest: PluginManifest
    path: Path
    enabled: bool = True
    skills: list[SkillDefinition] = field(default_factory=list)
    commands: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    hooks: dict = field(default_factory=dict)
    mcp_servers: dict = field(default_factory=dict)
