"""Tests for config loading and migration.

Adapted for agent-harness: uses agent_harness.config.loader and schema.
"""

import json

from agent_harness.config.loader import load_config, save_config


def test_load_config_keeps_max_tokens_and_ignores_legacy_memory_window(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agent": {
                    "max_tokens": 1234,
                    "context_window_tokens": 65_536,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.agent.max_tokens == 1234


def test_save_config_roundtrip(tmp_path) -> None:
    """Config should round-trip correctly through load + save."""
    original = {
        "agent": {
            "model": "test-model",
            "max_tokens": 2222,
            "max_iterations": 40,
            "context_window_tokens": 65_536,
        }
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(original), encoding="utf-8")

    config = load_config(config_path)
    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    agent = saved.get("agent", saved)

    assert agent.get("max_tokens") == 2222
    assert agent.get("model") == "test-model"
