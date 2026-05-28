"""Config loader: CLI args > env vars > YAML file > defaults."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from llm_harness.config.schema import Config


def load_config(
    config_path: str | Path | None = None,
    *, model: str | None = None, provider: str | None = None,
) -> Config:
    config = Config()
    path = config_path or os.environ.get("LLM_HARNESS_CONFIG")
    if path and Path(path).exists():
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if data:
            config = Config(**data)
    for env_key, field in [
        ("LLM_HARNESS_MODEL", "model"), ("LLM_HARNESS_PROVIDER", "provider"),
        ("LLM_HARNESS_API_KEY", "api_key"), ("LLM_HARNESS_API_BASE", "api_base"),
    ]:
        if os.environ.get(env_key):
            setattr(config.agent, field, os.environ[env_key])
    if os.environ.get("LLM_HARNESS_WORKSPACE"):
        config.workspace = os.environ["LLM_HARNESS_WORKSPACE"]
    if model:
        config.agent.model = model
    if provider:
        config.agent.provider = provider
    return config
