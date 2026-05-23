"""Tests for lazy provider exports from agent_harness.providers."""

from __future__ import annotations

import importlib
import sys


def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "agent_harness.providers", raising=False)
    monkeypatch.delitem(sys.modules, "agent_harness.providers.anthropic_provider", raising=False)
    monkeypatch.delitem(sys.modules, "agent_harness.providers.openai_compat_provider", raising=False)

    providers = importlib.import_module("agent_harness.providers")

    assert "agent_harness.providers.anthropic_provider" not in sys.modules
    assert "agent_harness.providers.openai_compat_provider" not in sys.modules


def test_explicit_provider_import_still_works(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "agent_harness.providers", raising=False)
    monkeypatch.delitem(sys.modules, "agent_harness.providers.anthropic_provider", raising=False)

    from agent_harness.providers.anthropic_provider import AnthropicProvider

    assert AnthropicProvider.__name__ == "AnthropicProvider"
    assert "agent_harness.providers.anthropic_provider" in sys.modules
