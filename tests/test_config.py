"""Tests for config loading: env var mapping, workspace env var."""

import os
import pytest
from pathlib import Path
from llm_harness.config.loader import load_config


class TestEnvVarMapping:
    """LLM_HARNESS_* env vars must map to the correct config fields."""

    def test_model_env_var(self, monkeypatch):
        monkeypatch.setenv("LLM_HARNESS_MODEL", "test-model-v1")
        cfg = load_config()
        assert cfg.agent.model == "test-model-v1"

    def test_provider_env_var(self, monkeypatch):
        monkeypatch.setenv("LLM_HARNESS_PROVIDER", "openai")
        cfg = load_config()
        assert cfg.agent.provider == "openai"

    def test_api_key_env_var(self, monkeypatch):
        monkeypatch.setenv("LLM_HARNESS_API_KEY", "sk-test123")
        cfg = load_config()
        assert cfg.agent.api_key == "sk-test123"

    def test_workspace_env_var(self, monkeypatch):
        """LLM_HARNESS_WORKSPACE must set config.workspace, not config.agent.workspace."""
        monkeypatch.setenv("LLM_HARNESS_WORKSPACE", "/custom/workspace")
        cfg = load_config()
        assert cfg.workspace == "/custom/workspace"

    def test_workspace_default(self, monkeypatch):
        """Without env var, workspace should default to current dir."""
        # Ensure env var is not set
        monkeypatch.delenv("LLM_HARNESS_WORKSPACE", raising=False)
        cfg = load_config()
        assert cfg.workspace == "."


class TestCliOverride:
    """CLI arguments must override env vars."""

    def test_model_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("LLM_HARNESS_MODEL", "env-model")
        cfg = load_config(model="cli-model")
        assert cfg.agent.model == "cli-model"

    def test_provider_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("LLM_HARNESS_PROVIDER", "env-provider")
        cfg = load_config(provider="cli-provider")
        assert cfg.agent.provider == "cli-provider"
