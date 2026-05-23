"""Tests for config path resolution.

Adapted for agent-harness: uses agent_harness.config.loader functions instead
of nanobot.config.paths (which was not ported).
"""

from pathlib import Path

from agent_harness.config.loader import get_default_config_path


def test_default_config_path_uses_env_var(monkeypatch) -> None:
    """HARNESS_CONFIG_PATH env var should be respected."""
    monkeypatch.setenv("HARNESS_CONFIG_PATH", "/custom/path/config.json")
    assert get_default_config_path() == Path("/custom/path/config.json")


def test_default_config_path_is_dot_agent_harness(monkeypatch) -> None:
    """Without env var, default is ~/.agent-harness/config.json."""
    monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
    assert get_default_config_path() == Path.home() / ".agent-harness" / "config.json"
