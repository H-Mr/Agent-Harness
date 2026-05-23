"""Tests for plugin discovery and loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_harness.plugins.loader import (
    _find_manifest,
    discover_plugin_paths,
    load_plugins,
)
from agent_harness.plugins.schemas import PluginManifest
from agent_harness.plugins.types import LoadedPlugin


# ============================================================================
# Helpers
# ============================================================================


def _make_plugin_dir(root: Path, name: str = "example", version: str = "1.0.0",
                     with_skills: bool = False, with_hooks: bool = False) -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True)
    manifest = {"name": name, "version": version, "description": f"{name} plugin"}
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    if with_skills:
        skills_dir = plugin_dir / "skills" / "my-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill\n---\n\n# My Skill\n\nTest content.\n",
            encoding="utf-8",
        )

    if with_hooks:
        hooks = {"PRE_TOOL_USE": [{"type": "command", "command": "echo hooked", "matcher": "test"}]}
        (plugin_dir / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")

    return plugin_dir


# ============================================================================
# Plugin discovery
# ============================================================================


class TestDiscovery:
    def test_finds_plugin_json(self, tmp_path: Path):
        pd = _make_plugin_dir(tmp_path, "my-plugin")
        manifest = _find_manifest(pd)
        assert manifest is not None
        assert manifest.name == "plugin.json"

    def test_finds_dot_claude_plugin_json(self, tmp_path: Path):
        pd = tmp_path / "my-plugin"
        claude_dir = pd / ".claude-plugin"
        claude_dir.mkdir(parents=True)
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": "my-plugin", "version": "1.0.0"})
        )
        manifest = _find_manifest(pd)
        assert manifest is not None

    def test_returns_none_when_no_manifest(self, tmp_path: Path):
        pd = tmp_path / "empty-dir"
        pd.mkdir()
        assert _find_manifest(pd) is None

    def test_discovers_from_extra_roots(self, tmp_path: Path):
        root = tmp_path / "plugins"
        root.mkdir()
        _make_plugin_dir(root, "extra-plugin")
        paths = discover_plugin_paths(config_dir=tmp_path, cwd=tmp_path, extra_roots=[root])
        assert len(paths) >= 1
        names = [p.name for p in paths]
        assert "extra-plugin" in names


# ============================================================================
# PluginManifest
# ============================================================================


class TestManifest:
    def test_parses_minimal_manifest(self):
        m = PluginManifest(name="test")
        assert m.name == "test"
        assert m.version == "0.0.0"
        assert m.enabled_by_default is True

    def test_parses_full_manifest(self):
        data = {
            "name": "full-plugin",
            "version": "2.0.0",
            "description": "Full featured plugin",
            "enabled_by_default": False,
            "skills_dir": "custom-skills",
            "hooks_file": "custom-hooks.json",
        }
        m = PluginManifest.model_validate(data)
        assert m.name == "full-plugin"
        assert m.version == "2.0.0"
        assert m.enabled_by_default is False
        assert m.skills_dir == "custom-skills"
        assert m.hooks_file == "custom-hooks.json"

    def test_default_values(self):
        m = PluginManifest(name="defaults")
        assert m.skills_dir == "skills"
        assert m.hooks_file == "hooks.json"
        assert m.mcp_file == "mcp.json"


# ============================================================================
# load_plugins
# ============================================================================


class TestLoadPlugins:
    def test_loads_single_plugin(self, tmp_path: Path):
        _make_plugin_dir(tmp_path, "test-plugin", with_skills=True)
        plugins = load_plugins_from_dir(tmp_path, tmp_path)
        assert len(plugins) == 1
        assert plugins[0].manifest.name == "test-plugin"
        assert len(plugins[0].skills) >= 1

    def test_plugin_not_enabled_by_config(self, tmp_path: Path):
        _make_plugin_dir(tmp_path, "disabled-plugin")
        plugins = load_plugins_from_dir(tmp_path, tmp_path, enabled_names=[])
        assert len(plugins) == 0

    def test_loads_multiple_plugins(self, tmp_path: Path):
        _make_plugin_dir(tmp_path, "plugin-a")
        _make_plugin_dir(tmp_path, "plugin-b")
        plugins = load_plugins_from_dir(tmp_path, tmp_path)
        assert len(plugins) == 2
        names = {p.manifest.name for p in plugins}
        assert names == {"plugin-a", "plugin-b"}

    def test_loads_plugin_with_hooks(self, tmp_path: Path):
        _make_plugin_dir(tmp_path, "hook-plugin", with_hooks=True)
        plugins = load_plugins_from_dir(tmp_path, tmp_path)
        assert len(plugins) == 1
        assert len(plugins[0].hooks) >= 1


# ============================================================================
# LoadedPlugin
# ============================================================================


class TestLoadedPlugin:
    def test_created_with_manifest_and_path(self, tmp_path: Path):
        m = PluginManifest(name="test")
        lp = LoadedPlugin(manifest=m, path=tmp_path)
        assert lp.manifest.name == "test"
        assert lp.path == tmp_path
        assert lp.enabled is True

    def test_defaults(self, tmp_path: Path):
        m = PluginManifest(name="test")
        lp = LoadedPlugin(manifest=m, path=tmp_path)
        assert lp.skills == []
        assert lp.commands == []
        assert lp.hooks == {}


# ============================================================================
# Helpers
# ============================================================================


def load_plugins_from_dir(
    cwd: Path,
    root: Path,
    *,
    enabled_names: list[str] | None = None,
) -> list[LoadedPlugin]:
    """Simplified loader that only scans a specific root directory."""
    from agent_harness.plugins.loader import _find_manifest
    from agent_harness.skills.loader import load_skills_from_dirs as _load_skills
    from agent_harness.plugins.types import LoadedPlugin

    enabled = enabled_names  # None = all enabled
    plugins: list[LoadedPlugin] = []

    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = _find_manifest(child)
        if manifest_path is None:
            continue
        manifest = PluginManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
        if enabled is not None and manifest.name not in enabled:
            continue

        skills: list = []
        skills_dir = child / manifest.skills_dir
        if skills_dir.exists():
            skills = _load_skills([skills_dir], source=f"plugin:{manifest.name}")

        hooks: dict = {}
        hooks_path = child / manifest.hooks_file
        if hooks_path.exists():
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))

        plugins.append(LoadedPlugin(
            manifest=manifest,
            path=child,
            enabled=True,
            skills=skills,
            hooks=hooks,
        ))

    return plugins
