"""Tests for agent_harness.config."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_harness.config.schema import Config, AgentConfig
from agent_harness.config.loader import load_config, save_config, get_default_config_path


class TestAgentConfig:
    """AgentConfig model tests."""

    def test_defaults(self):
        c = AgentConfig()
        assert c.model == "claude-sonnet-4-6"
        assert c.provider == "auto"
        assert c.api_key == ""
        assert c.api_base is None
        assert c.max_tokens == 8192
        assert c.max_iterations == 40
        assert c.temperature == 0.7
        assert c.reasoning_effort is None
        assert c.timezone == "UTC"
        assert c.workspace == "~/.agent-harness/workspace"

    def test_custom_values(self):
        c = AgentConfig(model="gpt-4", provider="openai", api_key="sk-123")
        assert c.model == "gpt-4"
        assert c.provider == "openai"
        assert c.api_key == "sk-123"


class TestConfig:
    """Root Config model tests."""

    def test_defaults(self):
        c = Config()
        assert c.agent.model == "claude-sonnet-4-6"
        assert isinstance(c.agent, AgentConfig)

    def test_workspace_path(self):
        c = Config()
        expected = Path("~/.agent-harness/workspace").expanduser()
        assert c.workspace_path == expected

    def test_nested_override(self):
        c = Config(agent={"model": "gpt-4o"})
        assert c.agent.model == "gpt-4o"
        assert c.agent.provider == "auto"  # other fields remain default


class TestLoadConfig:
    """Config loading tests."""

    def test_default_config(self):
        """Loading without any overrides should return default config."""
        config = load_config()
        assert config.agent.model == "claude-sonnet-4-6"
        assert config.agent.max_tokens == 8192

    def test_cli_overrides(self, monkeypatch):
        """CLI overrides should take precedence over defaults."""
        config = load_config(cli_overrides={
            "model": "cli-model",
            "provider": "anthropic",
            "api_key": "cli-key",
        })
        assert config.agent.model == "cli-model"
        assert config.agent.provider == "anthropic"
        assert config.agent.api_key == "cli-key"

    def test_cli_override_partial(self):
        """Partial CLI overrides should not affect other fields."""
        config = load_config(cli_overrides={"model": "cli-only"})
        assert config.agent.model == "cli-only"
        assert config.agent.provider == "auto"  # unchanged

    def test_env_overrides(self, monkeypatch):
        """Environment variables should override defaults."""
        monkeypatch.setenv("HARNESS_MODEL", "env-model")
        monkeypatch.setenv("HARNESS_API_KEY", "env-key")
        monkeypatch.setenv("HARNESS_MAX_TOKENS", "4096")
        config = load_config()
        assert config.agent.model == "env-model"
        assert config.agent.api_key == "env-key"
        assert config.agent.max_tokens == 4096

    def test_env_overrides_int(self, monkeypatch):
        """Integer env vars should be parsed correctly."""
        monkeypatch.setenv("HARNESS_MAX_ITERATIONS", "100")
        config = load_config()
        assert config.agent.max_iterations == 100

    def test_cli_overrides_env(self, monkeypatch):
        """CLI overrides should take precedence over env vars."""
        monkeypatch.setenv("HARNESS_MODEL", "env-model")
        config = load_config(cli_overrides={"model": "cli-model"})
        assert config.agent.model == "cli-model"

    def test_file_loading(self, tmp_path, monkeypatch):
        """Config file values should be loaded."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"agent": {"model": "file-model", "provider": "file-provider"}}),
            encoding="utf-8",
        )
        config = load_config(config_path=config_file)
        assert config.agent.model == "file-model"
        assert config.agent.provider == "file-provider"

    def test_file_overrides_defaults(self, tmp_path):
        """Config file should override defaults but not CLI."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"agent": {"model": "file-model", "max_tokens": 4096}}),
            encoding="utf-8",
        )
        config = load_config(config_path=config_file, cli_overrides={"model": "cli-model"})
        assert config.agent.model == "cli-model"  # CLI wins
        assert config.agent.max_tokens == 4096  # from file

    def test_missing_file(self, tmp_path, monkeypatch):
        """Non-existent config file should be silently ignored."""
        fake_path = tmp_path / "nonexistent" / "config.json"
        config = load_config(config_path=fake_path)
        assert config.agent.model == "claude-sonnet-4-6"

    def test_get_default_config_path_env(self, monkeypatch):
        """HARNESS_CONFIG_PATH env var should be respected."""
        monkeypatch.setenv("HARNESS_CONFIG_PATH", "/custom/path/config.json")
        path = get_default_config_path()
        assert path == Path("/custom/path/config.json")

    def test_get_default_config_path_default(self, monkeypatch):
        """Default config path should be under home directory."""
        monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
        path = get_default_config_path()
        assert path == Path.home() / ".agent-harness" / "config.json"


class TestSaveConfig:
    """Config persistence tests."""

    def test_save_and_reload(self, tmp_path):
        """Saved config should be reloadable."""
        config_path = tmp_path / "config.json"
        config = Config(agent=AgentConfig(model="saved-model", provider="saved-provider"))
        save_config(config, config_path=config_path)

        assert config_path.exists()
        loaded = load_config(config_path=config_path)
        assert loaded.agent.model == "saved-model"
        assert loaded.agent.provider == "saved-provider"

    def test_save_creates_parent_dir(self, tmp_path):
        """save_config should create parent directories."""
        config_path = tmp_path / "subdir" / "nested" / "config.json"
        config = Config()
        save_config(config, config_path=config_path)
        assert config_path.exists()
