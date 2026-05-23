"""Plugin discovery and loading."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from agent_harness.plugins.schemas import PluginManifest
from agent_harness.plugins.types import LoadedPlugin
from agent_harness.skills.loader import parse_skill_markdown
from agent_harness.skills.types import SkillDefinition

logger = logging.getLogger(__name__)


def get_user_plugins_dir(config_dir: Path) -> Path:
    """Return the user plugin directory."""
    path = config_dir / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_plugins_dir(cwd: str | Path) -> Path:
    """Return the project plugin directory."""
    path = Path(cwd).resolve() / ".agent-harness" / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_manifest(plugin_dir: Path) -> Path | None:
    """Find plugin.json in standard or .claude-plugin/ locations."""
    for candidate in [
        plugin_dir / "plugin.json",
        plugin_dir / ".claude-plugin" / "plugin.json",
    ]:
        if candidate.exists():
            return candidate
    return None


def discover_plugin_paths(
    config_dir: Path,
    cwd: str | Path,
    extra_roots: Iterable[str | Path] | None = None,
) -> list[Path]:
    """Find plugin directories from user and project locations."""
    roots = [get_user_plugins_dir(config_dir), get_project_plugins_dir(cwd)]
    if extra_roots:
        for root in extra_roots:
            path = Path(root).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            roots.append(path)
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.iterdir()):
            if p.is_dir() and _find_manifest(p) is not None and p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


def load_plugins(
    config_dir: Path,
    cwd: str | Path,
    enabled_plugins: dict[str, bool] | None = None,
    extra_roots: Iterable[str | Path] | None = None,
) -> list[LoadedPlugin]:
    """Load plugins from disk."""
    if enabled_plugins is None:
        enabled_plugins = {}
    plugins: list[LoadedPlugin] = []
    for path in discover_plugin_paths(config_dir, cwd, extra_roots=extra_roots):
        plugin = load_plugin(path, enabled_plugins)
        if plugin is not None:
            plugins.append(plugin)
    return plugins


def load_plugin(path: Path, enabled_plugins: dict[str, bool]) -> LoadedPlugin | None:
    """Load one plugin directory."""
    manifest_path = _find_manifest(path)
    if manifest_path is None:
        return None
    try:
        manifest = PluginManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed to load plugin manifest from %s: %s", manifest_path, exc)
        return None
    enabled = enabled_plugins.get(manifest.name, manifest.enabled_by_default)

    skills = _load_plugin_skills(path / manifest.skills_dir)

    return LoadedPlugin(
        manifest=manifest,
        path=path,
        enabled=enabled,
        skills=skills,
    )


def _load_plugin_skills(path: Path) -> list[SkillDefinition]:
    """Load plugin skills using Claude Code's directory SKILL.md layout."""
    if not path.exists():
        return []
    skills: list[SkillDefinition] = []
    direct_skill = path / "SKILL.md"
    if direct_skill.exists():
        content = direct_skill.read_text(encoding="utf-8")
        name, description = parse_skill_markdown(path.name, content)
        skills.append(
            SkillDefinition(
                name=name,
                description=description,
                content=content,
                source="plugin",
                path=str(direct_skill),
            )
        )
        return skills
    for child in sorted(path.iterdir()):
        if not child.is_dir():
            continue
        skill_path = child / "SKILL.md"
        if not skill_path.exists():
            continue
        content = skill_path.read_text(encoding="utf-8")
        name, description = parse_skill_markdown(child.name, content)
        skills.append(
            SkillDefinition(
                name=name,
                description=description,
                content=content,
                source="plugin",
                path=str(skill_path),
            )
        )
    return skills
