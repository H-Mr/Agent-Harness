"""Config loading with CLI/env/file precedence.

Resolution order: CLI overrides > env vars > config file > defaults
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_harness.config.schema import Config


def get_default_config_path() -> Path:
    """Return the default config file path."""
    env_path = os.environ.get("HARNESS_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".agent-harness" / "config.json"


def load_config(
    config_path: Path | None = None,
    *,
    cli_overrides: dict[str, str] | None = None,
) -> Config:
    """Load config from file + env + optional CLI overrides.

    1. Start with defaults (Config())
    2. Layer on config file values (if exists)
    3. Layer on env var overrides (HARNESS_*)
    4. Layer on CLI key=value overrides (if provided)
    """
    config = Config()

    path = config_path or get_default_config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            file_config = Config.model_validate(data)
            config = file_config
        except Exception:
            pass

    # Env var overrides are handled by pydantic-settings ConfigDict(env_prefix="HARNESS_")
    # But for simplicity, manually apply key env vars:
    if os.environ.get("HARNESS_MODEL"):
        config.agent.model = os.environ["HARNESS_MODEL"]
    if os.environ.get("HARNESS_API_KEY"):
        config.agent.api_key = os.environ["HARNESS_API_KEY"]
    if os.environ.get("HARNESS_API_BASE"):
        config.agent.api_base = os.environ["HARNESS_API_BASE"]
    if os.environ.get("HARNESS_MAX_TOKENS"):
        config.agent.max_tokens = int(os.environ["HARNESS_MAX_TOKENS"])
    if os.environ.get("HARNESS_MAX_ITERATIONS"):
        config.agent.max_iterations = int(os.environ["HARNESS_MAX_ITERATIONS"])

    # CLI overrides (key=value pairs)
    if cli_overrides:
        for key, value in cli_overrides.items():
            if key == "model":
                config.agent.model = value
            elif key == "provider":
                config.agent.provider = value
            elif key == "api_key":
                config.agent.api_key = value
            elif key == "api_base":
                config.agent.api_base = value
            elif key == "workspace":
                config.agent.workspace = value

    return config


def save_config(config: Config, config_path: Path | None = None) -> None:
    """Persist config to file."""
    path = config_path or get_default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        config.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
