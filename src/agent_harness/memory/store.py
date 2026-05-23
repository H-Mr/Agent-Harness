"""Two-layer persistent memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        """Read the current long-term memory contents."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """Overwrite long-term memory with new content."""
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        """Append an entry to the history log."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        """Return long-term memory formatted as a context block for prompts."""
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""
