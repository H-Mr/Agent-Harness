"""Shared utility functions."""

from __future__ import annotations

import re
from pathlib import Path


def strip_think(text: str) -> str:
    """Remove <think>...</think> blocks (DeepSeek-R1, Qwen reasoning)."""
    if not text:
        return ""
    return re.sub(r"<think[\s\S]*?</think>", "", text, flags=re.I).strip()


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """Replace filesystem-unsafe characters with underscores."""
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes."""
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"<svg":
        return "image/svg+xml"
    return None


def build_image_content_blocks(data: bytes, mime: str, path: str, fallback: str) -> list[dict]:
    """Build content blocks including base64-encoded image data."""
    import base64

    b64 = base64.b64encode(data).decode()
    return [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": fallback},
    ]
