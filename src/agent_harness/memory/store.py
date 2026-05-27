"""Per-session memory store: AGENTS.md, SOUL.md, MEMORY.md, USER.md, history.jsonl."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORY_FILES = ("MEMORY.md", "AGENTS.md", "SOUL.md", "USER.md")


class MemoryStore:
    """Per-session memory with five structured files.

    Directory layout::

        memory/{session_key}/
            MEMORY.md      ← facts, decisions (LLM overwrites)
            AGENTS.md      ← project rules, conventions (LLM overwrites)
            SOUL.md        ← personality, tone, behavior (LLM overwrites)
            USER.md        ← user profile, preferences (LLM overwrites)
            history.jsonl  ← archived conversation + summaries (append-only)

    Backward-compatible: passing a plain ``memory_dir`` without a session key
    creates a flat store with the old MEMORY.md / HISTORY.md behaviour.
    """

    def __init__(self, memory_dir: Path, session_key: str | None = None):
        if session_key:
            from agent_harness.session.manager import safe_filename

            self.memory_dir = memory_dir / safe_filename(session_key.replace(":", "_"))
        else:
            self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.agents_file = self.memory_dir / "AGENTS.md"
        self.soul_file = self.memory_dir / "SOUL.md"
        self.user_file = self.memory_dir / "USER.md"
        self.history_file = self.memory_dir / "history.jsonl"

    # ------------------------------------------------------------------
    # Per-file read / write
    # ------------------------------------------------------------------

    def read_file(self, name: str) -> str:
        """Read the full content of a memory file by logical name.

        *name* must be one of ``MEMORY.md``, ``AGENTS.md``, ``SOUL.md``, ``USER.md``.
        """
        path = self._path_for(name)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def write_file(self, name: str, content: str) -> None:
        """Overwrite a memory file with new content."""
        self._path_for(name).write_text(content, encoding="utf-8")

    def _path_for(self, name: str) -> Path:
        mapping = {
            "MEMORY.md": self.memory_file,
            "AGENTS.md": self.agents_file,
            "SOUL.md": self.soul_file,
            "USER.md": self.user_file,
        }
        path = mapping.get(name)
        if path is None:
            raise ValueError(f"Unknown memory file: {name}")
        return path

    # ------------------------------------------------------------------
    # History (append-only)
    # ------------------------------------------------------------------

    def append_history(self, entry: str) -> None:
        """Append a text entry to history.jsonl (grep-searchable log)."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def append_raw_messages(self, messages: list[dict]) -> None:
        """Append raw conversation messages to history.jsonl for traceability."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            f.write("\n")

    # ------------------------------------------------------------------
    # Multi-file snapshot (for consolidation prompt)
    # ------------------------------------------------------------------

    def get_all_files(self) -> dict[str, str]:
        """Return current content of all memory files."""
        return {name: self.read_file(name) for name in _MEMORY_FILES}

    def get_context(self) -> str:
        """Return all memory files formatted as a context block for prompts."""
        blocks: list[str] = []
        for name in ("AGENTS.md", "SOUL.md", "MEMORY.md", "USER.md"):
            content = self.read_file(name)
            blocks.append(f"## {name}\n{content}" if content else f"## {name}\n(empty)")
        return "\n\n".join(blocks)

    # ------------------------------------------------------------------
    # Backward-compatible API (delegates to MEMORY.md / history.jsonl)
    # ------------------------------------------------------------------

    def read_long_term(self) -> str:
        """Backward-compatible: read MEMORY.md."""
        return self.read_file("MEMORY.md")

    def write_long_term(self, content: str) -> None:
        """Backward-compatible: overwrite MEMORY.md."""
        self.write_file("MEMORY.md", content)

    def get_memory_context(self) -> str:
        """Backward-compatible: return multi-file context."""
        return self.get_context()
