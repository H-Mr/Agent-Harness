"""Skill dependency checking utilities."""

from __future__ import annotations

import os
import shutil


def check_skill_requirements(skill_metadata: dict) -> tuple[bool, list[str]]:
    """Check if required binaries and environment variables are available.

    Parameters
    ----------
    skill_metadata:
        Dict that may contain a ``requires`` key with sub-keys ``bins``
        (list of executable names) and ``env`` (list of env var names).

    Returns
    -------
    A tuple of ``(all_met, missing_items)`` where ``missing_items`` is a
    list of human-readable strings describing what was not found.
    """
    missing: list[str] = []
    requires = skill_metadata.get("requires", {})

    for binary in requires.get("bins", []):
        if not shutil.which(binary):
            missing.append(f"CLI: {binary}")

    for env_var in requires.get("env", []):
        if not os.environ.get(env_var):
            missing.append(f"ENV: {env_var}")

    return len(missing) == 0, missing


def get_missing_requirements(skill_metadata: dict) -> str:
    """Return a comma-separated description of missing requirements."""
    _, missing = check_skill_requirements(skill_metadata)
    return ", ".join(missing)
