"""Shared path-sanitization utility for filesystem backends."""

from __future__ import annotations

import re
from pathlib import Path

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def resolve_safe_path(base_dir: Path, name: str, *, suffix: str = "") -> Path:
    """Sanitize *name* into a safe sub-path under *base_dir*, appending optional *suffix*.

    Raises ValueError if the resolved path escapes *base_dir*.
    """
    safe = _UNSAFE_CHARS.sub("_", name).replace("..", "__")
    resolved = (base_dir / f"{safe}{suffix}").resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ValueError(f"Path traversal detected for: {name!r}")
    return resolved
